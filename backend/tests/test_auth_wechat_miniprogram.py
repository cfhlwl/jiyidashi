from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.auth_models import (
    AuthIdentity,
    AuthProvider,
    AuthSession,
    WechatMiniProgramExchange,
)
from app.core.config import get_settings
from app.core.db import SessionLocal, create_schema
from app.services.wechat_miniprogram_login_service import (
    WechatMiniProgramLoginError,
    exchange_wechat_miniprogram_code,
)
from app.services.wechat_miniprogram_provider import (
    FakeWechatMiniProgramProvider,
    VerifiedWechatMiniProgramResult,
    WechatMiniProgramProviderError,
)

create_schema()


def _settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_enabled", False)
    monkeypatch.setattr(settings, "auth_wechat_miniprogram_provider", "fake")
    monkeypatch.setattr(settings, "auth_wechat_miniprogram_app_id", "wx-mini-test")
    monkeypatch.setattr(
        settings,
        "auth_wechat_miniprogram_fingerprint_secret",
        "mini-fingerprint-secret",
    )
    monkeypatch.setattr(settings, "auth_wechat_miniprogram_live_enabled", False)
    return settings


def _provider(openid="openid-1", app_id="wx-mini-test"):
    return FakeWechatMiniProgramProvider(
        VerifiedWechatMiniProgramResult(
            app_id=app_id,
            openid=openid,
            unionid="unionid-must-not-link",
            verified_at=datetime.now(UTC),
        )
    )


def _exchange(settings, provider, *, code="code-1", request_id=None, device="mini-device"):
    with SessionLocal() as db:
        return exchange_wechat_miniprogram_code(
            db,
            code=code,
            request_id=request_id or uuid4(),
            device_id=device,
            client_platform="miniprogram",
            device_name="test",
            client_ip="127.0.0.1",
            provider=provider,
            settings=settings,
        )


def test_mini_identity_isolated_and_same_openid_reuses_user(monkeypatch):
    settings = _settings(monkeypatch)
    first = _exchange(settings, _provider(), code="mini-code-a")
    second = _exchange(settings, _provider(), code="mini-code-b")
    assert first.tokens.user_id == second.tokens.user_id
    with SessionLocal() as db:
        identities = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.WECHAT_MINIPROGRAM
                )
            )
        )
        assert [identity.subject for identity in identities] == ["openid:wx-mini-test:openid-1"]
        assert not db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == AuthProvider.WECHAT,
                AuthIdentity.subject.like("%unionid-must-not-link%"),
            )
        )


def test_same_code_is_replay_rejected_without_second_session(monkeypatch):
    settings = _settings(monkeypatch)
    provider = _provider()
    request_id = uuid4()
    first = _exchange(settings, provider, code="replayed-code", request_id=request_id)
    with pytest.raises(WechatMiniProgramLoginError, match="CODE_REPLAYED"):
        _exchange(settings, provider, code="replayed-code", request_id=uuid4())
    with SessionLocal() as db:
        assert db.scalar(
            select(WechatMiniProgramExchange).where(
                WechatMiniProgramExchange.request_id == request_id
            )
        ).state == "COMPLETED"
        assert db.scalar(
            select(AuthSession).where(AuthSession.user_id == first.tokens.user_id)
        ) is not None
    assert provider.calls == 1


def test_same_request_different_code_conflicts(monkeypatch):
    settings = _settings(monkeypatch)
    request_id = uuid4()
    _exchange(settings, _provider(), code="code-a", request_id=request_id)
    with pytest.raises(WechatMiniProgramLoginError, match="CONFLICT"):
        _exchange(settings, _provider(), code="code-b", request_id=request_id)


def test_missing_live_configuration_fails_closed_without_provider_call(monkeypatch):
    settings = _settings(monkeypatch)
    provider = _provider()
    monkeypatch.setattr(settings, "auth_wechat_miniprogram_fingerprint_secret", "")
    with pytest.raises(WechatMiniProgramLoginError, match="UNAVAILABLE"):
        _exchange(settings, provider, code="disabled-code")
    assert provider.calls == 0


def test_provider_timeout_marks_receipt_unknown_and_never_retries(monkeypatch):
    settings = _settings(monkeypatch)

    class TimeoutProvider:
        available = True
        calls = 0

        def exchange_code(self, *, code, request_id):
            self.calls += 1
            raise WechatMiniProgramProviderError("TIMEOUT", ambiguous=True)

    provider = TimeoutProvider()
    request_id = uuid4()
    with pytest.raises(WechatMiniProgramLoginError, match="TIMEOUT"):
        _exchange(settings, provider, code="timeout-code", request_id=request_id)
    with pytest.raises(WechatMiniProgramLoginError, match="REPLAYED"):
        _exchange(settings, provider, code="timeout-code", request_id=uuid4())
    with SessionLocal() as db:
        receipt = db.scalar(
            select(WechatMiniProgramExchange).where(
                WechatMiniProgramExchange.request_id == request_id
            )
        )
        assert receipt is not None
        assert receipt.state == "PROVIDER_UNKNOWN"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_miniprogram_endpoint_uses_token_response_and_separate_capability(
    client, monkeypatch
):
    settings = _settings(monkeypatch)
    monkeypatch.setattr(settings, "auth_wechat_miniprogram_provider", "fake")
    provider = _provider(openid="endpoint-openid")
    monkeypatch.setattr(
        "app.services.wechat_miniprogram_login_service.get_wechat_miniprogram_provider",
        lambda _settings: provider,
    )
    monkeypatch.setattr("app.api.auth.get_wechat_miniprogram_provider", lambda: provider)
    response = await client.get("/v1/auth/capabilities")
    assert response.status_code == 200
    assert response.json()["wechat_miniprogram"] == "DISABLED"

    monkeypatch.setattr(settings, "auth_wechat_miniprogram_provider", "wechat_miniprogram")
    monkeypatch.setattr(settings, "auth_wechat_miniprogram_live_enabled", True)
    response = await client.get("/v1/auth/capabilities")
    assert response.status_code == 200
    assert response.json()["wechat_miniprogram"] == "AVAILABLE"

    response = await client.post(
        "/v1/auth/wechat-mini/exchange",
        json={
            "code": "endpoint-code",
            "request_id": str(uuid4()),
            "device_id": "mini-endpoint-device",
            "client_platform": "miniprogram",
        },
    )
    assert response.status_code == 200
    assert response.json()["user_id"]
    assert "openid" not in response.text
    assert "session_key" not in response.text
