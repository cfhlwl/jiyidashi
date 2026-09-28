from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.core.observability import configure_observability_log_level
from app.security_models import (
    SecurityAlert,
    SecurityAlertDeliveryStatus,
    SecuritySeverity,
    SecuritySignalCode,
    SecuritySignalWindow,
)
from app.services import security_alerting
from app.services.security_alerting import (
    RULES,
    SecurityScope,
    record_security_signal,
    security_correlation_digest,
)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[SecuritySignalWindow.__table__, SecurityAlert.__table__],
    )
    return engine


def test_rule_taxonomy_and_severity_are_deterministic() -> None:
    assert RULES[SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST].severity == SecuritySeverity.HIGH
    assert RULES[SecuritySignalCode.FAMILY_SENSITIVE_READ_DENIED].threshold == 5
    assert RULES[SecuritySignalCode.FAMILY_SENSITIVE_DOWNLOAD_DENIED].threshold == 3
    assert RULES[SecuritySignalCode.DESTRUCTIVE_OPERATION_RETRY_BURST].threshold == 3
    assert RULES[SecuritySignalCode.STORAGE_CAPABILITY_FAILURE_BURST].threshold == 5


def test_correlation_is_deterministic_and_one_way() -> None:
    raw = "203.0.113.7\nuser@example.test"
    first = security_correlation_digest("login_account_ip", raw)
    second = security_correlation_digest("login_account_ip", raw)
    assert first == second
    assert len(first) == 64
    assert "203.0.113.7" not in first
    assert "user@example.test" not in first


def test_below_threshold_then_one_alert_and_cooldown_dedupe() -> None:
    engine = _engine()
    base = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    raw = f"network\n{uuid4()}@example.test"

    for offset in range(4):
        assert (
            record_security_signal(
                engine,
                signal_code=SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST,
                correlation_kind="login_account_ip",
                correlation_value=raw,
                scope=SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
                now=base + timedelta(seconds=offset),
            )
            is None
        )

    alert_id = record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST,
        correlation_kind="login_account_ip",
        correlation_value=raw,
        scope=SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
        now=base + timedelta(seconds=4),
    )
    assert alert_id is not None

    record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST,
        correlation_kind="login_account_ip",
        correlation_value=raw,
        scope=SecurityScope.AUTH_LOGIN_ACCOUNT_IP,
        now=base + timedelta(seconds=5),
    )

    with Session(engine) as db:
        alerts = list(db.scalars(select(SecurityAlert)))
        windows = list(db.scalars(select(SecuritySignalWindow)))
    assert len(alerts) == 1
    assert alerts[0].signal_count == 6
    assert len(windows) == 1
    assert windows[0].signal_count == 6


def test_new_cooldown_allows_new_alert() -> None:
    engine = _engine()
    base = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    raw = str(uuid4())
    for index in range(5):
        record_security_signal(
            engine,
            signal_code=SecuritySignalCode.STORAGE_CAPABILITY_FAILURE_BURST,
            correlation_kind="media_owner",
            correlation_value=raw,
            scope=SecurityScope.MEDIA_DOWNLOAD,
            now=base + timedelta(seconds=index),
        )
    for index in range(5):
        record_security_signal(
            engine,
            signal_code=SecuritySignalCode.STORAGE_CAPABILITY_FAILURE_BURST,
            correlation_kind="media_owner",
            correlation_value=raw,
            scope=SecurityScope.MEDIA_DOWNLOAD,
            now=base + timedelta(seconds=601 + index),
        )
    with Session(engine) as db:
        assert len(list(db.scalars(select(SecurityAlert)))) == 2


def test_cooldown_crosses_wall_clock_bucket_without_second_alert() -> None:
    engine = _engine()
    first = datetime(2026, 9, 28, 12, 9, 59, tzinfo=UTC)
    raw = f"cooldown-boundary-{uuid4()}"

    first_id = record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value=raw,
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=first,
    )
    second_id = record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value=raw,
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=first + timedelta(seconds=1),
    )
    assert first_id == second_id

    with Session(engine) as db:
        assert len(list(db.scalars(select(SecurityAlert)))) == 1

    third_id = record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value=raw,
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=first + timedelta(seconds=600),
    )
    assert third_id != first_id
    with Session(engine) as db:
        assert len(list(db.scalars(select(SecurityAlert)))) == 2


def test_delivery_failure_is_bounded_and_business_signal_still_persists(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        security_alerting,
        "emit_operational_event_checked",
        lambda **_: False,
    )
    alert_id = record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value="198.51.100.22",
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
    )
    assert alert_id is not None
    with Session(engine) as db:
        alert = db.scalar(select(SecurityAlert))
        assert alert is not None
        assert alert.delivery_status == SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
        assert alert.delivery_attempts == 1
        assert alert.next_retry_at is not None


def test_security_alert_event_contains_only_safe_correlation(monkeypatch) -> None:
    engine = _engine()
    captured: list[dict[str, object]] = []

    def capture(**kwargs):
        captured.append(kwargs)
        return True

    monkeypatch.setattr(security_alerting, "emit_operational_event_checked", capture)
    sentinel = "raw-ip=192.0.2.55;email=sentinel@example.test;Authorization=Bearer-secret"
    record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value=sentinel,
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
    )
    assert len(captured) == 1
    rendered = repr(captured[0])
    assert "192.0.2.55" not in rendered
    assert "sentinel@example.test" not in rendered
    assert "Bearer-secret" not in rendered
    assert captured[0]["event"] == "security.alert.triggered"
    assert len(str(captured[0]["correlation_id"])) == 64


def _drive_rule_to_threshold(
    engine,
    *,
    code: SecuritySignalCode,
    scope: SecurityScope,
    correlation_kind: str,
    correlation_value: str,
    base: datetime,
) -> None:
    policy = RULES[code]
    for index in range(policy.threshold):
        record_security_signal(
            engine,
            signal_code=code,
            correlation_kind=correlation_kind,
            correlation_value=correlation_value,
            scope=scope,
            now=base + timedelta(seconds=index),
        )


def test_required_v1_rule_families_reach_exact_threshold_once() -> None:
    engine = _engine()
    base = datetime(2026, 9, 28, 13, 0, tzinfo=UTC)
    cases = (
        (
            SecuritySignalCode.FAMILY_SENSITIVE_READ_DENIED,
            SecurityScope.FAMILY_MEMORY,
            "family_actor",
        ),
        (
            SecuritySignalCode.FAMILY_SENSITIVE_DOWNLOAD_DENIED,
            SecurityScope.FAMILY_PHOTO_DOWNLOAD,
            "family_actor",
        ),
        (
            SecuritySignalCode.DESTRUCTIVE_OPERATION_FAILURE,
            SecurityScope.DATA_DELETE,
            "deletion_request",
        ),
        (
            SecuritySignalCode.DESTRUCTIVE_OPERATION_RETRY_BURST,
            SecurityScope.ACCOUNT_DELETE,
            "deletion_request",
        ),
        (
            SecuritySignalCode.STORAGE_CAPABILITY_FAILURE_BURST,
            SecurityScope.MEDIA_DOWNLOAD,
            "media_owner",
        ),
    )
    for offset, (code, scope, kind) in enumerate(cases):
        raw = f"required-rule-{offset}-{uuid4()}"
        _drive_rule_to_threshold(
            engine,
            code=code,
            scope=scope,
            correlation_kind=kind,
            correlation_value=raw,
            base=base + timedelta(hours=offset),
        )
        digest = security_correlation_digest(kind, raw)
        with Session(engine) as db:
            alerts = list(
                db.scalars(
                    select(SecurityAlert).where(
                        SecurityAlert.correlation_digest == digest,
                        SecurityAlert.rule_code == code.value,
                    )
                )
            )
        assert len(alerts) == 1, (code, alerts)
        assert alerts[0].signal_count == RULES[code].threshold


def test_family_sensitive_access_burst_uses_shared_cross_resource_scope() -> None:
    engine = _engine()
    base = datetime(2026, 9, 28, 18, 0, tzinfo=UTC)
    raw = f"family-cross-resource-{uuid4()}"
    policy = RULES[SecuritySignalCode.FAMILY_SENSITIVE_ACCESS_BURST]
    for index in range(policy.threshold):
        record_security_signal(
            engine,
            signal_code=SecuritySignalCode.FAMILY_SENSITIVE_ACCESS_BURST,
            correlation_kind="family_actor",
            correlation_value=raw,
            scope=SecurityScope.FAMILY_SENSITIVE_ACCESS,
            now=base + timedelta(seconds=index),
        )

    digest = security_correlation_digest("family_actor", raw)
    with Session(engine) as db:
        alerts = list(
            db.scalars(
                select(SecurityAlert).where(
                    SecurityAlert.correlation_digest == digest,
                    SecurityAlert.rule_code
                    == SecuritySignalCode.FAMILY_SENSITIVE_ACCESS_BURST.value,
                )
            )
        )
    assert len(alerts) == 1
    assert alerts[0].scope == SecurityScope.FAMILY_SENSITIVE_ACCESS.value


def test_delivery_retry_reaches_terminal_after_five_attempts(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(security_alerting, "emit_operational_event_checked", lambda **_: False)
    base = datetime(2026, 9, 28, 19, 0, tzinfo=UTC)
    alert_id = record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value=f"retry-terminal-{uuid4()}",
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=base,
    )
    assert alert_id is not None

    for attempt in range(2, security_alerting.MAX_DELIVERY_ATTEMPTS + 1):
        security_alerting.deliver_security_alert(
            engine,
            alert_id=alert_id,
            now=base + timedelta(minutes=attempt),
        )

    with Session(engine) as db:
        alert = db.scalar(select(SecurityAlert).where(SecurityAlert.id == UUID(alert_id)))
        assert alert is not None
        assert alert.delivery_attempts == security_alerting.MAX_DELIVERY_ATTEMPTS
        assert (
            alert.delivery_status
            == SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value
        )
        assert alert.next_retry_at is None


class _FailingObservabilityStream:
    def write(self, _: str) -> int:
        raise OSError("simulated observability sink failure")

    def flush(self) -> None:
        raise OSError("simulated observability sink flush failure")


def test_real_checked_sink_failure_keeps_alert_retryable() -> None:
    engine = _engine()
    logger = logging.getLogger("jiyidashi.observability")
    configure_observability_log_level("INFO")
    handler = next(
        item
        for item in logger.handlers
        if getattr(item, "_jiyidashi_observability_sink", False)
    )
    original_stream = handler.stream
    handler.stream = _FailingObservabilityStream()
    try:
        alert_id = record_security_signal(
            engine,
            signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
            correlation_kind="register_ip",
            correlation_value=f"real-sink-failure-{uuid4()}",
            scope=SecurityScope.AUTH_REGISTER_IP,
            now=datetime(2026, 9, 28, 20, 0, tzinfo=UTC),
        )
    finally:
        handler.stream = original_stream

    assert alert_id is not None
    with Session(engine) as db:
        alert = db.scalar(
            select(SecurityAlert).where(SecurityAlert.id == UUID(alert_id))
        )
        assert alert is not None
        assert alert.delivery_status == SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
        assert alert.delivery_attempts == 1
        assert alert.next_retry_at is not None


def test_pending_alert_is_recovered_by_bounded_retry_scanner(monkeypatch) -> None:
    engine = _engine()
    now = datetime(2026, 9, 28, 21, 0, tzinfo=UTC)
    alert = SecurityAlert(
        dedupe_key=f"{uuid4().hex}{uuid4().hex}",
        rule_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED.value,
        severity=SecuritySeverity.MEDIUM.value,
        correlation_digest="a" * 64,
        scope=SecurityScope.AUTH_REGISTER_IP.value,
        window_started_at=now,
        window_seconds=600,
        signal_count=1,
        delivery_status=SecurityAlertDeliveryStatus.PENDING.value,
        delivery_attempts=0,
        created_at=now,
        updated_at=now,
    )
    with Session(engine) as db:
        db.add(alert)
        db.commit()
        alert_id = alert.id

    monkeypatch.setattr(
        security_alerting,
        "emit_operational_event_checked",
        lambda **_: True,
    )
    delivered = security_alerting.retry_due_security_alerts(engine, now=now, limit=25)
    assert delivered == 1

    with Session(engine) as db:
        recovered = db.get(SecurityAlert, alert_id)
        assert recovered is not None
        assert recovered.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value
        assert recovered.delivery_attempts == 1


def test_retry_before_next_retry_at_does_not_consume_attempt(monkeypatch) -> None:
    engine = _engine()
    base = datetime(2026, 9, 28, 22, 0, tzinfo=UTC)
    monkeypatch.setattr(
        security_alerting,
        "emit_operational_event_checked",
        lambda **_: False,
    )
    alert_id = record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value=f"retry-slot-{uuid4()}",
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=base,
    )
    assert alert_id is not None

    security_alerting.deliver_security_alert(
        engine,
        alert_id=alert_id,
        now=base + timedelta(seconds=1),
    )
    with Session(engine) as db:
        alert = db.get(SecurityAlert, UUID(alert_id))
        assert alert is not None
        assert alert.delivery_attempts == 1

    security_alerting.deliver_security_alert(
        engine,
        alert_id=alert_id,
        now=base + timedelta(seconds=31),
    )
    with Session(engine) as db:
        alert = db.get(SecurityAlert, UUID(alert_id))
        assert alert is not None
        assert alert.delivery_attempts == 2
        assert alert.next_retry_at == base + timedelta(seconds=91)
