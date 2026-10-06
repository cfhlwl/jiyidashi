from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.security_models import (
    SecurityAlert,
    SecurityAlertDeliveryStatus,
    SecuritySeverity,
    SecuritySignalCode,
)
from app.services import security_alerting
from app.services.security_alert_human_delivery import (
    FeishuWebhookAdapter,
    HumanDeliveryResult,
    SecurityAlertHumanMessage,
    feishu_signature,
    validate_feishu_webhook_url,
)
from app.services.security_alerting import (
    SecurityScope,
    begin_security_alert_delivery_attempt,
    deliver_security_alert,
    finalize_security_alert_delivery_attempt,
    record_security_signal,
)


def _engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _alert(
    engine,
    *,
    severity: SecuritySeverity,
    status: SecurityAlertDeliveryStatus = SecurityAlertDeliveryStatus.PENDING,
) -> SecurityAlert:
    now = datetime.now(UTC)
    row = SecurityAlert(
        dedupe_key=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
        rule_code=SecuritySignalCode.AUTH_LOGIN_FAILURE_BURST.value,
        severity=severity.value,
        correlation_digest="a" * 64,
        scope=SecurityScope.AUTH_LOGIN_ACCOUNT_IP.value,
        window_started_at=now,
        window_seconds=900,
        signal_count=5,
        delivery_status=status.value,
        delivery_attempts=0,
        delivery_revision=0,
        created_at=now,
        updated_at=now,
    )
    with Session(engine) as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    return row


class _Adapter:
    provider_name = "fake"

    def __init__(self, result: HumanDeliveryResult):
        self.result = result
        self.messages: list[SecurityAlertHumanMessage] = []

    def deliver(self, message: SecurityAlertHumanMessage) -> HumanDeliveryResult:
        self.messages.append(message)
        return self.result


def test_feishu_signature_matches_reviewed_algorithm() -> None:
    timestamp = 1_700_000_000
    secret = "sec017-signing-secret"
    signing_key = f"{timestamp}\n{secret}".encode()
    expected = base64.b64encode(
        hmac.new(signing_key, digestmod=hashlib.sha256).digest()
    ).decode()
    assert feishu_signature(timestamp=timestamp, secret=secret) == expected


@pytest.mark.parametrize(
    ("url", "valid"),
    (
        ("https://open.feishu.cn/open-apis/bot/v2/hook/abc", True),
        ("http://open.feishu.cn/open-apis/bot/v2/hook/abc", False),
        ("https://evil.example/open-apis/bot/v2/hook/abc", False),
        ("https://open.feishu.cn/open-apis/bot/v1/hook/abc", False),
        ("https://open.feishu.cn/open-apis/bot/v2/hook/abc?token=secret", False),
        ("https://open.feishu.cn/open-apis/bot/v2/hook/abc/extra", False),
    ),
)
def test_feishu_url_validation(url: str, valid: bool) -> None:
    assert validate_feishu_webhook_url(url) is valid


def test_feishu_message_is_allowlisted_and_requires_provider_ack(monkeypatch) -> None:
    captured: dict = {}
    secret = "SUPER_SECRET_SENTINEL"

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"code": 0, "msg": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = FeishuWebhookAdapter(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        secret=secret,
        timeout_seconds=2,
        client=client,
    )
    monkeypatch.setattr("app.services.security_alert_human_delivery.time.time", lambda: 1700000000)

    result = adapter.deliver(
        SecurityAlertHumanMessage(
            alert_id="alert-safe-id",
            severity="HIGH",
            rule_code="AUTH_LOGIN_FAILURE_BURST",
            scope="AUTH_LOGIN_ACCOUNT_IP",
            signal_count=5,
            window_seconds=900,
            created_at=datetime(2026, 10, 6, 8, 0, tzinfo=UTC),
            correlation_digest="b" * 64,
        )
    )
    assert result.delivered is True
    assert captured["timestamp"] == 1700000000
    assert captured["sign"] == feishu_signature(timestamp=1700000000, secret=secret)
    body = json.dumps(captured, ensure_ascii=False)
    assert "alert-safe-id" in body
    assert "AUTH_LOGIN_FAILURE_BURST" in body
    assert secret not in body
    for forbidden in (
        "raw-ip-sentinel",
        "user@example.test",
        "Bearer ",
        "signed-url",
        "memory-content",
    ):
        assert forbidden not in body


@pytest.mark.parametrize(
    ("response", "delivered", "retryable", "error_code"),
    (
        (
            httpx.Response(200, json={"code": 19021, "msg": "secret body"}),
            False,
            False,
            "FEISHU_PROVIDER_19021",
        ),
        (
            httpx.Response(200, json={"code": 99999, "msg": "unknown body"}),
            False,
            True,
            "FEISHU_PROVIDER_UNKNOWN",
        ),
        (
            httpx.Response(200, content=b"not-json"),
            False,
            True,
            "FEISHU_RESPONSE_INVALID",
        ),
        (httpx.Response(408), False, True, "FEISHU_HTTP_408"),
        (httpx.Response(500), False, True, "FEISHU_HTTP_500"),
    ),
)
def test_feishu_provider_classification(
    response: httpx.Response,
    delivered: bool,
    retryable: bool,
    error_code: str,
) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: response))
    adapter = FeishuWebhookAdapter(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        secret="test-secret",
        timeout_seconds=2,
        client=client,
    )
    result = adapter.deliver(
        SecurityAlertHumanMessage(
            alert_id="alert-id",
            severity="HIGH",
            rule_code="RULE",
            scope="SCOPE",
            signal_count=1,
            window_seconds=60,
            created_at=datetime.now(UTC),
            correlation_digest="c" * 64,
        )
    )
    assert result.delivered is delivered
    assert result.retryable is retryable
    assert result.error_code == error_code
    assert "secret body" not in (result.error_code or "")
    assert "unknown body" not in (result.error_code or "")


def test_feishu_429_retry_after_is_bounded() -> None:
    response = httpx.Response(429, headers={"Retry-After": "999999"})
    adapter = FeishuWebhookAdapter(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        secret="test-secret",
        timeout_seconds=2,
        client=httpx.Client(transport=httpx.MockTransport(lambda _: response)),
    )
    result = adapter.deliver(
        SecurityAlertHumanMessage(
            alert_id="alert-id",
            severity="HIGH",
            rule_code="RULE",
            scope="SCOPE",
            signal_count=1,
            window_seconds=60,
            created_at=datetime.now(UTC),
            correlation_digest="d" * 64,
        )
    )
    assert result.retryable is True
    assert result.retry_after_seconds == 900


def test_feishu_timeout_is_retryable_without_exception_text() -> None:
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("SECRET_PROVIDER_EXCEPTION_SENTINEL")

    adapter = FeishuWebhookAdapter(
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test-token",
        secret="test-secret",
        timeout_seconds=2,
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    )
    result = adapter.deliver(
        SecurityAlertHumanMessage(
            alert_id="alert-id",
            severity="HIGH",
            rule_code="RULE",
            scope="SCOPE",
            signal_count=1,
            window_seconds=60,
            created_at=datetime.now(UTC),
            correlation_digest="e" * 64,
        )
    )
    assert result.retryable is True
    assert result.error_code == "FEISHU_TIMEOUT"
    assert "SECRET_PROVIDER_EXCEPTION_SENTINEL" not in result.error_code


def test_medium_delivery_remains_log_only(monkeypatch) -> None:
    engine = _engine()
    row = _alert(engine, severity=SecuritySeverity.MEDIUM)
    adapter = _Adapter(HumanDeliveryResult(delivered=False, retryable=False))
    monkeypatch.setattr(
        security_alerting,
        "emit_security_alert_event_checked",
        lambda **_: True,
    )

    assert deliver_security_alert(
        engine,
        alert_id=str(row.id),
        human_adapter=adapter,
        worker_execution=True,
    )
    assert adapter.messages == []
    with Session(engine) as db:
        current = db.get(SecurityAlert, row.id)
        assert current is not None
        assert current.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value


def test_high_requires_human_ack_even_when_log_succeeds(monkeypatch) -> None:
    engine = _engine()
    row = _alert(engine, severity=SecuritySeverity.HIGH)
    adapter = _Adapter(
        HumanDeliveryResult(
            delivered=False,
            retryable=True,
            error_code="FEISHU_TIMEOUT",
        )
    )
    monkeypatch.setattr(
        security_alerting,
        "emit_security_alert_event_checked",
        lambda **_: True,
    )

    assert not deliver_security_alert(
        engine,
        alert_id=str(row.id),
        human_adapter=adapter,
        worker_execution=True,
    )
    assert len(adapter.messages) == 1
    with Session(engine) as db:
        current = db.get(SecurityAlert, row.id)
        assert current is not None
        assert current.delivery_status == SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
        assert current.delivery_error_code == "FEISHU_TIMEOUT"


def test_stale_attempt_cannot_finalize_newer_attempt() -> None:
    engine = _engine()
    row = _alert(engine, severity=SecuritySeverity.HIGH)
    first = begin_security_alert_delivery_attempt(engine, alert_id=row.id)
    second = begin_security_alert_delivery_attempt(engine, alert_id=row.id)
    assert first is not None and second is not None
    assert first.token != second.token
    assert first.revision + 1 == second.revision

    assert not finalize_security_alert_delivery_attempt(
        engine,
        attempt=first,
        result=HumanDeliveryResult(delivered=True, retryable=False),
    )
    assert finalize_security_alert_delivery_attempt(
        engine,
        attempt=second,
        result=HumanDeliveryResult(delivered=True, retryable=False),
    )
    with Session(engine) as db:
        current = db.get(SecurityAlert, row.id)
        assert current is not None
        assert current.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value


def test_business_signal_does_not_call_human_delivery(monkeypatch) -> None:
    engine = _engine()
    monkeypatch.setattr(
        security_alerting,
        "deliver_security_alert",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("human delivery ran on business path")
        ),
    )
    monkeypatch.setattr(
        security_alerting,
        "emit_security_alert_event_checked",
        lambda **_: True,
    )
    policy = security_alerting.RULES[SecuritySignalCode.AUTH_REFRESH_REPLAY]
    alert_id = None
    for index in range(policy.threshold):
        alert_id = record_security_signal(
            engine,
            signal_code=SecuritySignalCode.AUTH_REFRESH_REPLAY,
            correlation_kind="refresh",
            correlation_value=str(uuid4()),
            scope=SecurityScope.AUTH_REFRESH_SESSION,
            now=datetime.now(UTC) + timedelta(seconds=index),
        )
    assert alert_id is not None
