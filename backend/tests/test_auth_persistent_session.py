from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from sqlalchemy import select

from app.auth_models import AuthOneTimePurpose, AuthOneTimeToken, AuthSession
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import decode_access_token_claims, legacy_access_session_id
from app.models import User
from app.services import auth_rate_limit
from app.services.auth_delivery import (
    MemoryAuthEmailDelivery,
    set_auth_email_delivery_for_testing,
)

settings = get_settings()


@pytest.fixture(autouse=True)
def relaxed_public_auth_limits(monkeypatch):
    monkeypatch.setattr(auth_rate_limit.settings, "auth_register_ip_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_login_ip_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_login_account_ip_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_refresh_session_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_verify_resend_ip_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_verify_resend_account_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_password_reset_ip_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_password_reset_account_limit", 1000)
    monkeypatch.setattr(auth_rate_limit.settings, "auth_password_reset_confirm_limit", 1000)


async def _register(
    client,
    delivery: MemoryAuthEmailDelivery,
    *,
    email: str,
    password: str = "correct-horse-battery-staple",
):
    before = len(delivery.verification_tokens)
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "nickname": "Persistent Session User",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201
    assert response.json()["verification_required"] is True
    assert "access_token" not in response.json()
    assert len(delivery.verification_tokens) == before + 1
    delivered_email, token = delivery.verification_tokens[-1]
    assert delivered_email == email.casefold()
    return response.json()["user_id"], token


async def _verify(
    client,
    token: str,
    *,
    device_id: str = "auth-test-device",
):
    response = await client.post(
        "/v1/auth/verify-email",
        json={
            "token": token,
            "device_id": device_id,
            "client_platform": "test",
            "device_name": "AUTH-001 test",
        },
    )
    assert response.status_code == 200
    session = response.json()["session"]
    assert session is not None
    return session


def _headers(session: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}




class _FailingAuthEmailDelivery:
    def send_verification(self, *, email: str, token: str) -> None:
        raise RuntimeError("simulated delivery outage")

    def send_password_reset(self, *, email: str, token: str) -> None:
        raise RuntimeError("simulated delivery outage")


async def test_registration_survives_verification_delivery_outage(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    set_auth_email_delivery_for_testing(_FailingAuthEmailDelivery())
    try:
        response = await client.post(
            "/v1/auth/register",
            json={
                "email": "auth001-mail-outage@example.com",
                "password": "correct-horse-battery-staple",
                "nickname": "Mail Outage",
                "timezone": "Asia/Shanghai",
                "locale": "zh-CN",
            },
        )
    finally:
        set_auth_email_delivery_for_testing(auth_email_delivery)

    assert response.status_code == 201
    assert response.json()["verification_required"] is True
    assert response.json()["verification_delivery_pending"] is True
    assert "access_token" not in response.json()

    resent = await client.post(
        "/v1/auth/resend-verification",
        json={"email": "auth001-mail-outage@example.com"},
    )
    assert resent.status_code == 202
    assert auth_email_delivery.verification_tokens


async def test_registration_requires_email_verification_before_login(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    _, token = await _register(
        client,
        auth_email_delivery,
        email="auth001-unverified@example.com",
    )

    blocked = await client.post(
        "/v1/auth/login",
        json={
            "email": "auth001-unverified@example.com",
            "password": "correct-horse-battery-staple",
            "device_id": "unverified-device",
        },
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "EMAIL_VERIFICATION_REQUIRED"

    session = await _verify(client, token)
    me = await client.get("/v1/user", headers=_headers(session))
    assert me.status_code == 200


async def test_verification_is_single_use_and_repeat_is_idempotent(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    _, token = await _register(
        client,
        auth_email_delivery,
        email="auth001-verify-once@example.com",
    )
    first = await _verify(client, token, device_id="verify-once")

    repeated = await client.post(
        "/v1/auth/verify-email",
        json={"token": token, "device_id": "second-device"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["verified"] is True
    assert repeated.json()["already_verified"] is True
    assert repeated.json()["session"] is None

    with SessionLocal() as db:
        active = list(
            db.scalars(
                select(AuthSession).where(
                    AuthSession.user_id == UUID(first["user_id"]),
                    AuthSession.revoked_at.is_(None),
                )
            )
        )
        assert len(active) == 1


async def test_access_jwt_has_issuer_audience_jti_and_session_binding(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    _, token = await _register(
        client,
        auth_email_delivery,
        email="auth001-claims@example.com",
    )
    session = await _verify(client, token, device_id="claims-device")
    claims = decode_access_token_claims(session["access_token"])
    assert str(claims.user_id) == session["user_id"]
    assert str(claims.session_id) == session["session_id"]
    assert claims.jti

    now = datetime.now(UTC)
    bad = jwt.encode(
        {
            "iss": "wrong-issuer",
            "aud": settings.jwt_audience,
            "sub": session["user_id"],
            "jti": "00000000-0000-4000-8000-000000000001",
            "session_id": session["session_id"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    denied = await client.get(
        "/v1/user",
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"] == "INVALID_ACCESS_TOKEN"

    wrong_audience = jwt.encode(
        {
            "iss": settings.jwt_issuer,
            "aud": "wrong-audience",
            "sub": session["user_id"],
            "jti": "00000000-0000-4000-8000-000000000002",
            "session_id": session["session_id"],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    audience_denied = await client.get(
        "/v1/user",
        headers={"Authorization": f"Bearer {wrong_audience}"},
    )
    assert audience_denied.status_code == 401
    assert audience_denied.json()["detail"] == "INVALID_ACCESS_TOKEN"

    wrong_session = jwt.encode(
        {
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "sub": session["user_id"],
            "jti": "00000000-0000-4000-8000-000000000003",
            "session_id": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    session_denied = await client.get(
        "/v1/user",
        headers={"Authorization": f"Bearer {wrong_session}"},
    )
    assert session_denied.status_code == 401
    assert session_denied.json()["detail"] == "AUTH_SESSION_INVALID"


async def test_pre_session_access_jwt_uses_backfilled_compatibility_session(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        user = User(nickname="Pre-session JWT")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(
            AuthSession(
                id=legacy_access_session_id(user_id),
                user_id=user_id,
                device_id="legacy-access-token",
                refresh_digest=str(user_id).replace("-", "") * 2,
                rotation_revision=0,
                client_platform="legacy",
                device_name="Pre-session access token",
                created_at=now,
                last_used_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        db.commit()

    token = jwt.encode(
        {
            "sub": str(user_id),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    response = await client.get("/v1/user", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


async def test_refresh_rotates_and_old_token_replay_revokes_session(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    _, token = await _register(
        client,
        auth_email_delivery,
        email="auth001-refresh@example.com",
    )
    first = await _verify(client, token, device_id="refresh-device")

    rotated_response = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert rotated_response.status_code == 200
    rotated = rotated_response.json()
    assert rotated["session_id"] == first["session_id"]
    assert rotated["refresh_token"] != first["refresh_token"]
    assert rotated["access_token"] != first["access_token"]

    replay = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": first["refresh_token"]},
    )
    assert replay.status_code == 401
    assert replay.json()["detail"] == "REFRESH_TOKEN_REUSED"

    # Replay revokes the affected token family, including the valid successor JWT.
    denied = await client.get("/v1/user", headers=_headers(rotated))
    assert denied.status_code == 401
    assert denied.json()["detail"] == "AUTH_SESSION_INVALID"

    successor_refresh = await client.post(
        "/v1/auth/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert successor_refresh.status_code == 401


async def test_logout_current_rejects_still_unexpired_access_jwt(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    _, token = await _register(
        client,
        auth_email_delivery,
        email="auth001-logout@example.com",
    )
    session = await _verify(client, token, device_id="logout-device")
    headers = _headers(session)

    logout = await client.post("/v1/auth/logout", headers=headers)
    assert logout.status_code == 200

    denied = await client.get("/v1/user", headers=headers)
    assert denied.status_code == 401
    assert denied.json()["detail"] == "AUTH_SESSION_INVALID"


async def test_logout_all_revokes_every_device_session(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    email = "auth001-logout-all@example.com"
    password = "correct-horse-battery-staple"
    _, token = await _register(client, auth_email_delivery, email=email, password=password)
    first = await _verify(client, token, device_id="device-a")

    second_login = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": password,
            "device_id": "device-b",
            "client_platform": "test",
        },
    )
    assert second_login.status_code == 200
    second = second_login.json()

    listed = await client.get("/v1/auth/sessions", headers=_headers(first))
    assert listed.status_code == 200
    assert {row["device_id"] for row in listed.json()} == {"device-a", "device-b"}

    logout_all = await client.post("/v1/auth/logout-all", headers=_headers(first))
    assert logout_all.status_code == 200

    assert (await client.get("/v1/user", headers=_headers(first))).status_code == 401
    assert (await client.get("/v1/user", headers=_headers(second))).status_code == 401


async def test_forgot_password_is_enumeration_safe_and_reset_revokes_sessions(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    email = "auth001-reset@example.com"
    password = "correct-horse-battery-staple"
    _, token = await _register(client, auth_email_delivery, email=email, password=password)
    session = await _verify(client, token, device_id="reset-device")

    missing = await client.post(
        "/v1/auth/forgot-password",
        json={"email": "missing-auth001@example.com"},
    )
    existing = await client.post(
        "/v1/auth/forgot-password",
        json={"email": email},
    )
    assert missing.status_code == existing.status_code == 202
    assert missing.json() == existing.json() == {"accepted": True}
    assert auth_email_delivery.password_reset_tokens
    reset_email, reset_token = auth_email_delivery.password_reset_tokens[-1]
    assert reset_email == email

    reset = await client.post(
        "/v1/auth/reset-password",
        json={
            "token": reset_token,
            "new_password": "new-correct-horse-battery-staple",
        },
    )
    assert reset.status_code == 200

    # Password reset revokes previously valid durable sessions.
    denied = await client.get("/v1/user", headers=_headers(session))
    assert denied.status_code == 401

    reused = await client.post(
        "/v1/auth/reset-password",
        json={
            "token": reset_token,
            "new_password": "another-correct-horse-battery-staple",
        },
    )
    assert reused.status_code == 400
    assert reused.json()["detail"] == "INVALID_PASSWORD_RESET_TOKEN"

    old_login = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": password,
            "device_id": "old-password",
        },
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": "new-correct-horse-battery-staple",
            "device_id": "new-password",
        },
    )
    assert new_login.status_code == 200


async def test_session_listing_and_owner_scoped_revoke(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    email = "auth001-revoke@example.com"
    password = "correct-horse-battery-staple"
    _, token = await _register(client, auth_email_delivery, email=email, password=password)
    first = await _verify(client, token, device_id="revoke-a")
    other = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": password, "device_id": "revoke-b"},
    )
    assert other.status_code == 200
    second = other.json()

    revoked = await client.delete(
        f"/v1/auth/sessions/{second['session_id']}",
        headers=_headers(first),
    )
    assert revoked.status_code == 200
    assert (await client.get("/v1/user", headers=_headers(second))).status_code == 401
    assert (await client.get("/v1/user", headers=_headers(first))).status_code == 200

async def test_email_verification_token_expires(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    user_id, token = await _register(
        client,
        auth_email_delivery,
        email="auth001-verify-expired@example.com",
    )
    with SessionLocal() as db:
        row = db.scalar(
            select(AuthOneTimeToken).where(
                AuthOneTimeToken.user_id == UUID(user_id),
                AuthOneTimeToken.purpose == AuthOneTimePurpose.EMAIL_VERIFY,
            )
        )
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    response = await client.post(
        "/v1/auth/verify-email",
        json={"token": token, "device_id": "expired-verify"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "VERIFICATION_TOKEN_EXPIRED"


async def test_password_reset_token_expires(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    email = "auth001-reset-expired@example.com"
    user_id, token = await _register(client, auth_email_delivery, email=email)
    await _verify(client, token, device_id="reset-expired")

    requested = await client.post(
        "/v1/auth/forgot-password",
        json={"email": email},
    )
    assert requested.status_code == 202
    _, reset_token = auth_email_delivery.password_reset_tokens[-1]

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthOneTimeToken).where(
                AuthOneTimeToken.user_id == UUID(user_id),
                AuthOneTimeToken.purpose == AuthOneTimePurpose.PASSWORD_RESET,
            )
        )
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    response = await client.post(
        "/v1/auth/reset-password",
        json={
            "token": reset_token,
            "new_password": "expired-reset-new-password",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSWORD_RESET_TOKEN_EXPIRED"


async def test_password_change_revokes_all_existing_sessions(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    email = "auth001-change-password@example.com"
    old_password = "correct-horse-battery-staple"
    _, token = await _register(
        client,
        auth_email_delivery,
        email=email,
        password=old_password,
    )
    first = await _verify(client, token, device_id="password-change-a")
    second_response = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": old_password,
            "device_id": "password-change-b",
        },
    )
    assert second_response.status_code == 200
    second = second_response.json()

    changed = await client.post(
        "/v1/auth/change-password",
        headers=_headers(first),
        json={
            "current_password": old_password,
            "new_password": "new-correct-horse-battery-staple",
        },
    )
    assert changed.status_code == 200
    assert (await client.get("/v1/user", headers=_headers(first))).status_code == 401
    assert (await client.get("/v1/user", headers=_headers(second))).status_code == 401

    old_login = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": old_password,
            "device_id": "old-password-after-change",
        },
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": "new-correct-horse-battery-staple",
            "device_id": "new-password-after-change",
        },
    )
    assert new_login.status_code == 200


async def test_disabled_user_fails_closed_even_with_unexpired_access_jwt(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    user_id, token = await _register(
        client,
        auth_email_delivery,
        email="auth001-disabled@example.com",
    )
    session = await _verify(client, token, device_id="disabled-device")

    with SessionLocal() as db:
        user = db.get(User, UUID(user_id))
        assert user is not None
        user.auth_disabled_at = datetime.now(UTC)
        db.commit()

    denied = await client.get("/v1/user", headers=_headers(session))
    assert denied.status_code == 401
    assert denied.json()["detail"] == "AUTH_ACCOUNT_UNAVAILABLE"


async def test_account_delete_revokes_other_sessions_and_preserves_two_phase_continuation(
    client,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    email = "auth001-account-delete@example.com"
    password = "correct-horse-battery-staple"
    _, token = await _register(
        client,
        auth_email_delivery,
        email=email,
        password=password,
    )
    continuation = await _verify(client, token, device_id="delete-continuation")
    other_response = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": password,
            "device_id": "delete-other",
        },
    )
    assert other_response.status_code == 200
    other = other_response.json()

    request_id = str(uuid4())
    prepared = await client.post(
        "/v1/account/delete",
        headers=_headers(continuation),
        json={
            "request_id": request_id,
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": False,
        },
    )
    assert prepared.status_code == 202
    assert prepared.json()["completed"] is False

    # Other devices lose session authority immediately.
    other_denied = await client.get("/v1/user", headers=_headers(other))
    assert other_denied.status_code == 401
    assert other_denied.json()["detail"] == "AUTH_SESSION_INVALID"

    # The exact continuation session cannot re-enter ordinary owner data.
    ordinary_denied = await client.get("/v1/user", headers=_headers(continuation))
    assert ordinary_denied.status_code == 423
    assert ordinary_denied.json()["detail"] == "ACCOUNT_DELETION_IN_PROGRESS"

    # It can finish the reviewed PREPARE -> local purge -> COMMIT protocol.
    committed = await client.post(
        "/v1/account/delete",
        headers=_headers(continuation),
        json={
            "request_id": request_id,
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert committed.status_code == 200
    assert committed.json()["completed"] is True

    after_delete = await client.get("/v1/user", headers=_headers(continuation))
    assert after_delete.status_code == 401

