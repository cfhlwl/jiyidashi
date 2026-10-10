from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import auth as auth_api
from app.auth_models import AuthIdentity, AuthProvider, AuthSession, WechatLoginExchange
from app.core.config import get_settings
from app.core.db import SessionLocal, create_schema
from app.models import User
from app.services import wechat_login_service
from app.services.auth_session_service import PublicAuthError
from app.services.wechat_auth_provider import FakeWechatAuthProvider, VerifiedWechatResult
from app.services.wechat_login_service import WechatLoginError, exchange_wechat_credential

create_schema()


def _settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_rate_limit_enabled", False)
    monkeypatch.setattr(
        settings, "auth_wechat_fingerprint_secret", "test-wechat-fingerprint-secret"
    )
    monkeypatch.setattr(settings, "auth_wechat_provider", "fake")
    monkeypatch.setattr(settings, "auth_wechat_app_id", "wx-test-app")
    monkeypatch.setattr(settings, "auth_wechat_subject_scope", "wx-test-group")
    return settings


def _provider(suffix: str = "1") -> FakeWechatAuthProvider:
    return FakeWechatAuthProvider(
        VerifiedWechatResult(
            app_id="wx-test-app",
            scope="wx-test-group",
            openid=f"openid-{suffix}",
            unionid=f"unionid-{suffix}",
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


def test_same_request_retry_is_replayed_without_reissuing_session(monkeypatch):
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
        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_CREDENTIAL_REPLAYED"):
            exchange_wechat_credential(
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
        session = db.scalar(select(AuthSession).where(AuthSession.id == first.tokens.session_id))
        receipt = db.scalar(
            select(WechatLoginExchange).where(WechatLoginExchange.request_id == request_id)
        )
        assert session is not None and session.revoked_at is None
        assert receipt is not None and str(receipt.state) == "COMPLETED"
        assert receipt.recovery_count == 0
        assert provider.calls == 1


def test_expected_identity_unique_race_terminalizes_receipt(monkeypatch):
    settings = _settings(monkeypatch)
    provider = _provider("integrity-race")

    def raise_expected_integrity(*args, **kwargs):
        raise IntegrityError(
            "insert",
            {},
            RuntimeError("uq_auth_identities_provider_subject"),
        )

    monkeypatch.setattr(
        wechat_login_service, "_resolve_verified_identity", raise_expected_integrity
    )
    request_id = uuid4()
    with SessionLocal() as db:
        with pytest.raises(WechatLoginError, match="AUTH_IDENTITY_CONFLICT"):
            exchange_wechat_credential(
                db,
                credential="opaque-integrity-race",
                request_id=request_id,
                device_id="device-a",
                client_platform="flutter",
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )
        receipt = db.scalar(
            select(WechatLoginExchange).where(WechatLoginExchange.request_id == request_id)
        )
        assert receipt is not None
        assert str(receipt.state) == "PROVIDER_REJECTED"
        assert receipt.error_code == "AUTH_IDENTITY_CONFLICT"
        assert receipt.resolved_user_id is None
    assert provider.calls == 1


def test_same_request_retry_from_different_device_is_rejected(monkeypatch):
    provider = _provider()
    settings = _settings(monkeypatch)
    request_id = uuid4()
    with SessionLocal() as db:
        exchange_wechat_credential(
            db,
            credential="opaque-code-device-fence",
            request_id=request_id,
            device_id="device-a",
            client_platform="flutter",
            device_name=None,
            client_ip="127.0.0.1",
            provider=provider,
            settings=settings,
        )
        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_CREDENTIAL_REPLAYED"):
            exchange_wechat_credential(
                db,
                credential="opaque-code-device-fence",
                request_id=request_id,
                device_id="device-b",
                client_platform="flutter",
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )
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
    monkeypatch.setattr(settings, "auth_wechat_app_id", "wx-conflict-app")
    monkeypatch.setattr(settings, "auth_wechat_subject_scope", "wx-conflict-group")
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


def test_provider_result_app_and_scope_must_match_server_binding(monkeypatch):
    settings = _settings(monkeypatch)
    for field, value in (("app_id", "wrong-app"), ("scope", "wrong-scope")):
        kwargs = {
            "app_id": "wx-test-app",
            "scope": "wx-test-group",
            "openid": f"openid-{field}",
            "unionid": f"unionid-{field}",
            "verified_at": datetime.now(UTC),
        }
        kwargs[field] = value
        provider = FakeWechatAuthProvider(VerifiedWechatResult(**kwargs))
        with SessionLocal() as db:
            with pytest.raises(WechatLoginError, match="AUTH_WECHAT_PROVIDER_ERROR"):
                exchange_wechat_credential(
                    db,
                    credential=f"opaque-wrong-{field}",
                    request_id=uuid4(),
                    device_id="device-a",
                    client_platform=None,
                    device_name=None,
                    client_ip="127.0.0.1",
                    provider=provider,
                    settings=settings,
                )
            assert not db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.subject
                    == f"unionid:{settings.auth_wechat_subject_scope}:unionid-{field}"
                )
            )


def test_missing_server_app_binding_is_unavailable_before_provider(monkeypatch):
    settings = _settings(monkeypatch)
    monkeypatch.setattr(settings, "auth_wechat_app_id", "")
    provider = _provider()
    with SessionLocal() as db:
        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_UNAVAILABLE"):
            exchange_wechat_credential(
                db,
                credential="opaque-missing-binding",
                request_id=uuid4(),
                device_id="device-a",
                client_platform=None,
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )
    assert provider.calls == 0


def test_malformed_provider_subject_has_no_identity_side_effect(monkeypatch):
    settings = _settings(monkeypatch)
    provider = FakeWechatAuthProvider(
        VerifiedWechatResult(
            app_id="wx-test-app",
            scope="wx-test-group",
            openid="bad openid",
            unionid=None,
            verified_at=datetime.now(UTC),
        )
    )
    with SessionLocal() as db:
        with pytest.raises(WechatLoginError, match="AUTH_WECHAT_PROVIDER_ERROR"):
            exchange_wechat_credential(
                db,
                credential="opaque-malformed-subject",
                request_id=uuid4(),
                device_id="device-a",
                client_platform=None,
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )
        assert (
            db.scalar(
                select(AuthIdentity).where(AuthIdentity.subject == "openid:wx-test-app:bad openid")
            )
            is None
        )


def test_session_issue_failure_rolls_back_new_identity_and_keeps_receipt(monkeypatch):
    settings = _settings(monkeypatch)
    provider = _provider("rollback-new")

    def fail_session(*args, **kwargs):
        raise PublicAuthError("AUTH_SESSION_ISSUE_FAILED", 503)

    monkeypatch.setattr(
        wechat_login_service,
        "issue_authenticated_session_in_transaction",
        fail_session,
    )
    request_id = uuid4()
    with SessionLocal() as db:
        with pytest.raises(WechatLoginError, match="AUTH_SESSION_ISSUE_FAILED"):
            exchange_wechat_credential(
                db,
                credential="opaque-rollback-new",
                request_id=request_id,
                device_id="device-a",
                client_platform=None,
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )
        assert (
            db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.subject == "unionid:wx-test-group:unionid-rollback-new"
                )
            )
            is None
        )
        receipt = db.scalar(
            select(wechat_login_service.WechatLoginExchange).where(
                wechat_login_service.WechatLoginExchange.request_id == request_id
            )
        )
        assert receipt is not None
        assert str(receipt.state) == "PROVIDER_REJECTED"


def test_session_issue_failure_rolls_back_new_alias_for_existing_user(monkeypatch):
    settings = _settings(monkeypatch)
    provider = _provider("rollback-alias")
    with SessionLocal() as db:
        user = User(nickname="wechat-existing-alias")
        db.add(user)
        db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.WECHAT,
                subject="unionid:wx-test-group:unionid-rollback-alias",
                verified_at=datetime.now(UTC),
            )
        )
        db.commit()

    def fail_session(*args, **kwargs):
        raise PublicAuthError("AUTH_SESSION_ISSUE_FAILED", 503)

    monkeypatch.setattr(
        wechat_login_service,
        "issue_authenticated_session_in_transaction",
        fail_session,
    )
    with SessionLocal() as db:
        with pytest.raises(WechatLoginError, match="AUTH_SESSION_ISSUE_FAILED"):
            exchange_wechat_credential(
                db,
                credential="opaque-rollback-alias",
                request_id=uuid4(),
                device_id="device-a",
                client_platform=None,
                device_name=None,
                client_ip="127.0.0.1",
                provider=provider,
                settings=settings,
            )
        identities = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.user_id == user.id,
                    AuthIdentity.provider == AuthProvider.WECHAT,
                )
            )
        )
        assert [identity.subject for identity in identities] == [
            "unionid:wx-test-group:unionid-rollback-alias"
        ]


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
    monkeypatch.setattr(auth_api.settings, "auth_wechat_app_id", settings.auth_wechat_app_id)
    monkeypatch.setattr(
        auth_api.settings, "auth_wechat_subject_scope", settings.auth_wechat_subject_scope
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
