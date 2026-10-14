from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api import auth as auth_api
from app.auth_models import (
    AuthIdentity,
    AuthIdentityOperation,
    AuthIdentityOperationState,
    AuthProvider,
    AuthSession,
)
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, create_schema
from app.core.security import decode_access_token_claims
from app.models import User
from app.services.auth_identity_link_provider import (
    DisabledAuthIdentityLinkProvider,
    FakeAuthIdentityLinkProvider,
    VerifiedIdentityProof,
    get_auth_identity_link_provider,
)
from app.services.auth_identity_operation_service import (
    link_identity,
    list_identities,
    unlink_identity,
)
from app.services.auth_identity_service import (
    AuthIdentityError,
    create_user_for_verified_identity,
    issue_authenticated_session,
)

create_schema()


def _settings(monkeypatch) -> Settings:
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "auth_identity_operation_fingerprint_secret",
        "auth-005-test-only-server-key",
    )
    monkeypatch.setattr(settings, "auth_identity_link_recent_reauth_seconds", 300)
    return settings


def _phone_user(db, suffix: str):
    return create_user_for_verified_identity(
        db,
        provider=AuthProvider.PHONE,
        subject=f"+86138123{suffix:0>5}",
        verified_at=datetime.now(UTC),
    )


def _provider(*, user_id, session_id, subject: str, credential: str = "credential-a"):
    now = datetime.now(UTC)
    proof = VerifiedIdentityProof(
        provider=AuthProvider.WECHAT,
        subject=subject,
        verified_at=now,
        reauthenticated_at=now,
        user_id=user_id,
        session_id=session_id,
        provider_request_id="mock-request",
    )
    return FakeAuthIdentityLinkProvider(
        link_results={credential: proof},
        reauth_results={"reauth": now},
    )


def test_production_fake_identity_provider_is_fail_closed():
    provider = get_auth_identity_link_provider(
        Settings.model_construct(
            app_env="production",
            auth_identity_link_provider="fake",
        )
    )
    assert isinstance(provider, DisabledAuthIdentityLinkProvider)
    assert provider.available is False


def test_link_is_idempotent_and_fences_other_sessions(monkeypatch):
    settings = _settings(monkeypatch)
    with SessionLocal() as db:
        created = _phone_user(db, "10001")
        db.commit()
        first = issue_authenticated_session(
            db, user_id=created.user_id, device_id=f"auth-005-a-{uuid4()}"
        )
        second = issue_authenticated_session(
            db, user_id=created.user_id, device_id=f"auth-005-b-{uuid4()}"
        )
        provider = _provider(
            user_id=created.user_id,
            session_id=first.tokens.session_id,
            subject="unionid:test-scope:auth005-idempotent",
        )
        request_id = uuid4()

        result = link_identity(
            db,
            user_id=created.user_id,
            session_id=first.tokens.session_id,
            request_id=request_id,
            credential="credential-a",
            reauth_credential="reauth",
            provider=provider,
            settings=settings,
        )
        retry = link_identity(
            db,
            user_id=created.user_id,
            session_id=first.tokens.session_id,
            request_id=request_id,
            credential="credential-a",
            reauth_credential="reauth",
            provider=provider,
            settings=settings,
        )
        assert result.identity is not None
        assert retry.identity is not None
        assert retry.identity.id == result.identity.id
        assert provider.link_calls == 1
        assert db.get(AuthSession, second.tokens.session_id).revoked_at is not None
        operation = db.scalar(
            select(AuthIdentityOperation).where(
                AuthIdentityOperation.request_id == request_id
            )
        )
        assert operation is not None
        assert operation.state == AuthIdentityOperationState.COMPLETED
        assert "credential-a" not in repr(operation)


def test_conflicting_owner_is_rejected_without_transfer_or_merge(monkeypatch):
    settings = _settings(monkeypatch)
    with SessionLocal() as db:
        owner_a = _phone_user(db, "10002")
        owner_b = _phone_user(db, "10003")
        db.commit()
        session_a = issue_authenticated_session(
            db, user_id=owner_a.user_id, device_id=f"auth-005-a-{uuid4()}"
        )
        # Use the actual canonical identity owned by B, not a client assertion.
        b_identity = db.scalar(
            select(AuthIdentity).where(AuthIdentity.user_id == owner_b.user_id)
        )
        now = datetime.now(UTC)
        provider = FakeAuthIdentityLinkProvider(
            link_results={
                "credential-a": VerifiedIdentityProof(
            provider=AuthProvider.PHONE,
            subject=b_identity.subject,
            verified_at=now,
            reauthenticated_at=now,
            user_id=owner_a.user_id,
            session_id=session_a.tokens.session_id,
                )
            },
            reauth_results={"reauth": now},
        )
        request_id = uuid4()
        with pytest.raises(AuthIdentityError, match="AUTH_IDENTITY_CONFLICT"):
            link_identity(
                db,
                user_id=owner_a.user_id,
                session_id=session_a.tokens.session_id,
                request_id=request_id,
                credential="credential-a",
                reauth_credential="reauth",
                provider=provider,
                settings=settings,
            )
        db.expire_all()
        assert db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == owner_a.user_id,
                AuthIdentity.subject == b_identity.subject,
            )
        ) is None
        assert db.scalar(
            select(AuthIdentity).where(AuthIdentity.id == b_identity.id)
        ).user_id == owner_b.user_id
        operation = db.scalar(
            select(AuthIdentityOperation).where(
                AuthIdentityOperation.request_id == request_id
            )
        )
        assert operation.state == AuthIdentityOperationState.REJECTED


def test_unlink_requires_step_up_and_never_removes_last_identity(monkeypatch):
    settings = _settings(monkeypatch)
    with SessionLocal() as db:
        created = _phone_user(db, "10004")
        db.commit()
        session = issue_authenticated_session(
            db, user_id=created.user_id, device_id=f"auth-005-a-{uuid4()}"
        )
        phone = db.scalar(select(AuthIdentity).where(AuthIdentity.user_id == created.user_id))
        provider = _provider(
            user_id=created.user_id,
            session_id=session.tokens.session_id,
            subject="unionid:test-scope:auth005-unlink",
        )
        with pytest.raises(AuthIdentityError, match="AUTH_LAST_IDENTITY_REQUIRED"):
            unlink_identity(
                db,
                user_id=created.user_id,
                session_id=session.tokens.session_id,
                request_id=uuid4(),
                identity_id=phone.id,
                reauth_credential="reauth",
                provider=provider,
                settings=settings,
            )
        assert len(list_identities(db, user_id=created.user_id)) == 1

        linked = link_identity(
            db,
            user_id=created.user_id,
            session_id=session.tokens.session_id,
            request_id=uuid4(),
            credential="credential-a",
            reauth_credential="reauth",
            provider=provider,
            settings=settings,
        )
        assert linked.identity is not None
        wechat = linked.identity
        assert len(list_identities(db, user_id=created.user_id)) == 2
        removed = unlink_identity(
            db,
            user_id=created.user_id,
            session_id=session.tokens.session_id,
            request_id=uuid4(),
            identity_id=wechat.id,
            reauth_credential="reauth",
            provider=provider,
            settings=settings,
        )
        assert removed.identity is not None
        assert len(list_identities(db, user_id=created.user_id)) == 1
        assert db.get(User, created.user_id).phone is not None


@pytest.mark.asyncio
async def test_api_rejects_client_identity_claims(client, auth_headers):
    response = await client.post(
        "/v1/auth/identities/link",
        headers=auth_headers,
        json={
            "request_id": str(uuid4()),
            "credential": "opaque-provider-credential",
            "reauth_credential": "opaque-step-up",
            "provider": "PHONE",
            "subject": "+8613812345678",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_api_uses_provider_proof_and_returns_masked_identity(
    client, monkeypatch
):
    settings = _settings(monkeypatch)
    token_response = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "AUTH-005 API mock"},
    )
    assert token_response.status_code == 200
    token = token_response.json()
    claims = decode_access_token_claims(token["access_token"])
    now = datetime.now(UTC)
    provider = FakeAuthIdentityLinkProvider(
        link_results={
            "opaque-provider-credential": VerifiedIdentityProof(
                provider=AuthProvider.WECHAT,
                subject="unionid:auth005:api-mock",
                verified_at=now,
                reauthenticated_at=now,
                user_id=claims.user_id,
                session_id=claims.session_id,
            )
        },
        reauth_results={"opaque-step-up": now},
    )
    monkeypatch.setattr(auth_api, "get_auth_identity_link_provider", lambda: provider)
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    response = await client.post(
        "/v1/auth/identities/link",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "credential": "opaque-provider-credential",
            "reauth_credential": "opaque-step-up",
        },
    )
    assert response.status_code == 200
    assert response.json()["identity"]["provider"] == "WECHAT"
    assert "api-mock" not in response.json()["identity"]["subject_hint"]
    assert provider.link_calls == 1
    assert settings.auth_identity_operation_fingerprint_secret
