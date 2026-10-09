from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api import auth as auth_api
from app.auth_models import AuthIdentity, AuthProvider
from app.core.config import get_settings
from app.core.db import SessionLocal, create_schema
from app.models import User
from app.services import wechat_login_service
from app.services.wechat_auth_provider import (
    FakeWechatAuthProvider,
    VerifiedWechatResult,
)
from app.services.wechat_login_service import (
    WechatLoginError,
    exchange_wechat_credential,
)

create_schema()


def _settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_enabled", False)
    monkeypatch.setattr(
        settings, "auth_wechat_fingerprint_secret", "test-wechat-fingerprint-secret"
    )
    monkeypatch.setattr(settings, "auth_wechat_provider", "fake")
    return settings


def _provider() -> FakeWechatAuthProvider:
    return FakeWechatAuthProvider(
        VerifiedWechatResult(
            app_id="wx-test-app",
            scope="wx-test-group",
            openid="openid-1",
            unionid="unionid-1",
            verified_at=datetime.now(UTC),
            provider_request_id="provider-test-1",
        )
    )


def test_verified_wechat_resolves_scoped_unionid_and_openid_aliases(monkeypatch):
    provider = _provider()
    settings = _settings(monkeypatch)
    request_id = uuid4()
    with SessionLocal() as db:
        result = exchange_wechat_credential(
            db,
            credential="opaque-code-1",
            request_id=request_id,
            device_id="device-a",
            client_platform="flutter",
            device_name="test",
            client_ip="127.0.0.1",
            provider=provider,
            settings=settings,
        )
        identities = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.user_id == result.tokens.user_id,
                    AuthIdentity.provider == AuthProvider.WECHAT,
                )
            )
        )
        assert {identity.subject for identity in identities} == {
            "unionid:wx-test-group:unionid-1",
            "openid:wx-test-app:openid-1",
        }
        assert result.device_id == "device-a"
        assert provider.calls == 1


def test_same_request_retry_recovers_once_without_second_provider_call(monkeypatch):
    provider = _provider()
    settings = _settings(monkeypatch)
    request_id = uuid4()
    with SessionLocal() as db:
        first = exchange_wechat_credential(
            db,
            credential="opaque-code-retry",
            request_id=request_id,
            device_id="device-a",
            client_platform="flutter",
            device_name=None,
            client_ip="127.0.0.1",
            provider=provider,
            settings=settings,
        )
        recovered = exchange_wechat_credential(
            db,
            credential="opaque-code-retry",
            request_id=request_id,
            device_id="device-b",
            client_platform="flutter",
            device_name=None,
            client_ip="127.0.0.1",
            provider=provider,
            settings=settings,
        )
        assert recovered.tokens.user_id == first.tokens.user_id
        assert recovered.device_id == "device-a"
        assert provider.calls == 1


def test_same_credential_different_request_is_replay_rejected(monkeypatch):
    provider = _provider()
    settings = _settings(monkeypatch)
    with SessionLocal() as db:
        exchange_wechat_credential(
            db,
            credential="opaque-code-replay",
            request_id=uuid4(),
            device_id="device-a",
            client_platform=None,
            device_name=None,
            client_ip="127.0.0.1",
            provider=provider,
            settings=settings,
        )
        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_CREDENTIAL_REPLAYED"):
            exchange_wechat_credential(
                db,
                credential="opaque-code-replay",
                request_id=uuid4(),
                device_id="device-a",
                client_platform=None,
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )
        assert provider.calls == 1


def test_bare_openid_or_cross_user_alias_conflict_fails_closed(monkeypatch):
    provider = FakeWechatAuthProvider(
        VerifiedWechatResult(
            app_id="wx-conflict-app",
            scope="wx-conflict-group",
            openid="openid-conflict",
            unionid="unionid-conflict",
            verified_at=datetime.now(UTC),
        )
    )
    settings = _settings(monkeypatch)
    with SessionLocal() as db:
        user = User(nickname="wechat-conflict")
        db.add(user)
        db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.WECHAT,
                subject="openid:wx-conflict-app:openid-conflict",
                verified_at=datetime.now(UTC),
            )
        )
        other = User(nickname="wechat-conflict-other")
        db.add(other)
        db.flush()
        db.add(
            AuthIdentity(
                user_id=other.id,
                provider=AuthProvider.WECHAT,
                subject="unionid:wx-conflict-group:unionid-conflict",
                verified_at=datetime.now(UTC),
            )
        )
        db.commit()
        with pytest.raises(WechatLoginError, match="AUTH_IDENTITY_CONFLICT"):
            exchange_wechat_credential(
                db,
                credential="opaque-code-conflict",
                request_id=uuid4(),
                device_id="device-a",
                client_platform=None,
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )


async def test_wechat_capability_is_provider_neutral_and_fail_closed(client, monkeypatch):
    monkeypatch.setattr(auth_api.settings, "auth_wechat_provider", "wechat")
    monkeypatch.setattr(auth_api, "get_wechat_provider", lambda: _provider())
    response = await client.get("/v1/auth/capabilities")
    assert response.status_code == 200
    assert response.json()["wechat"] == "AVAILABLE"
    assert "unionid" not in response.text
    assert "secret" not in response.text.lower()


@pytest.mark.asyncio
async def test_wechat_exchange_endpoint_uses_existing_token_response_and_hides_provider_data(
    client, monkeypatch
):
    settings = _settings(monkeypatch)
    monkeypatch.setattr(auth_api.settings, "auth_wechat_provider", "fake")
    monkeypatch.setattr(
        auth_api.settings,
        "auth_wechat_fingerprint_secret",
        settings.auth_wechat_fingerprint_secret,
    )
    provider = _provider()
    monkeypatch.setattr(wechat_login_service, "get_wechat_provider", lambda _: provider)
    response = await client.post(
        "/v1/auth/wechat/exchange",
        json={
            "credential": "opaque-endpoint-code",
            "request_id": str(uuid4()),
            "device_id": "wechat-endpoint-device",
            "client_platform": "flutter",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert "openid" not in response.text
    assert "unionid" not in response.text
    assert "opaque-endpoint-code" not in response.text
    assert provider.calls == 1
