from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
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


def test_delivery_failure_is_bounded_and_business_signal_still_persists(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        security_alerting,
        "emit_operational_event",
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

    monkeypatch.setattr(security_alerting, "emit_operational_event", capture)
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
