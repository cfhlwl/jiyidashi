from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.admin_models import AdminAccount, AdminRole, AdminSession
from app.security_models import SecurityAlert, SecuritySignalCode
from app.services import auth_rate_limit
from app.services.security_alerting import SecurityScope
from app.core.db import SessionLocal
from app.services.admin_security import hash_admin_password


def _create_admin(*, role: AdminRole = AdminRole.SUPER_ADMIN) -> tuple[str, str]:
    email = f"admin-{uuid4()}@example.com"
    password = "Admin-Test-Password-123!"
    with SessionLocal() as db:
        db.add(
            AdminAccount(
                email=email,
                display_name="测试管理员",
                password_hash=hash_admin_password(password),
                role=role.value,
                disabled=False,
                revision=0,
            )
        )
        db.commit()
    return email, password


async def _login(client, *, role: AdminRole = AdminRole.SUPER_ADMIN):
    email, password = _create_admin(role=role)
    response = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return email, response


async def test_product_user_token_is_never_admin_authority(client, auth_headers):
    response = await client.get(
        "/admin/api/v1/auth/session",
        headers=auth_headers,
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "ADMIN_AUTH_REQUIRED"


async def test_admin_login_uses_httponly_session_and_separate_csrf_cookie(client):
    _, response = await _login(client)
    set_cookie = response.headers.get_list("set-cookie")
    session_cookie = next(
        value for value in set_cookie if value.startswith("jiyi_admin_session=")
    )
    csrf_cookie = next(
        value for value in set_cookie if value.startswith("jiyi_admin_csrf=")
    )

    assert "HttpOnly" in session_cookie
    assert "SameSite=strict" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=strict" in csrf_cookie
    assert response.headers["cache-control"] == "no-store"

    current = await client.get("/admin/api/v1/auth/session")
    assert current.status_code == 200
    assert current.json()["role"] == "SUPER_ADMIN"


async def test_admin_mutation_requires_matching_csrf(client):
    await _login(client)

    missing = await client.post("/admin/api/v1/auth/logout")
    assert missing.status_code == 403
    assert missing.json()["detail"] == "ADMIN_CSRF_REQUIRED"

    invalid = await client.post(
        "/admin/api/v1/auth/logout",
        headers={"X-CSRF-Token": "wrong"},
    )
    assert invalid.status_code == 403
    assert invalid.json()["detail"] == "ADMIN_CSRF_INVALID"

    csrf = client.cookies.get("jiyi_admin_csrf")
    assert csrf
    ok = await client.post(
        "/admin/api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200

    stale = await client.get("/admin/api/v1/auth/session")
    assert stale.status_code == 401


async def test_admin_role_revision_change_invalidates_existing_session(client):
    email, _ = await _login(client, role=AdminRole.OPERATOR)

    with SessionLocal() as db:
        account = db.scalar(select(AdminAccount).where(AdminAccount.email == email))
        assert account is not None
        account.role = AdminRole.SUPPORT_READONLY.value
        account.revision += 1
        db.commit()

    response = await client.get("/admin/api/v1/auth/session")
    assert response.status_code == 401
    assert response.json()["detail"] == "ADMIN_SESSION_STALE"


async def test_revoked_admin_session_is_rejected(client):
    email, _ = await _login(client)

    with SessionLocal() as db:
        account = db.scalar(select(AdminAccount).where(AdminAccount.email == email))
        assert account is not None
        session = db.scalar(
            select(AdminSession)
            .where(AdminSession.admin_id == account.id)
            .order_by(AdminSession.created_at.desc())
            .limit(1)
        )
        assert session is not None
        from datetime import UTC, datetime

        session.revoked_at = datetime.now(UTC)
        db.commit()

    response = await client.get("/admin/api/v1/auth/session")
    assert response.status_code == 401
    assert response.json()["detail"] == "ADMIN_SESSION_STALE"

async def test_admin_login_is_rate_limited_before_repeated_argon2_and_emits_security_signal(
    client,
    monkeypatch,
):
    email, _ = _create_admin()
    monkeypatch.setattr(auth_rate_limit.settings, "admin_login_ip_limit", 50)
    monkeypatch.setattr(auth_rate_limit.settings, "admin_login_account_ip_limit", 10)
    monkeypatch.setattr(auth_rate_limit.settings, "admin_login_backoff_after_failures", 2)
    monkeypatch.setattr(auth_rate_limit.settings, "admin_login_backoff_max_seconds", 60)

    first = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-one"},
    )
    second = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-two"},
    )
    blocked = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-three"},
    )

    assert first.status_code == 401
    assert second.status_code == 401
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "AUTH_RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) >= 1

    with SessionLocal() as db:
        alert = db.scalar(
            select(SecurityAlert)
            .where(
                SecurityAlert.rule_code
                == SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED.value,
                SecurityAlert.scope == SecurityScope.ADMIN_LOGIN_ACCOUNT_IP.value,
            )
            .order_by(SecurityAlert.created_at.desc())
            .limit(1)
        )
        assert alert is not None


async def test_successful_admin_login_clears_only_account_ip_penalty(client, monkeypatch):
    email, password = _create_admin()
    monkeypatch.setattr(auth_rate_limit.settings, "admin_login_ip_limit", 50)
    monkeypatch.setattr(auth_rate_limit.settings, "admin_login_account_ip_limit", 10)
    monkeypatch.setattr(auth_rate_limit.settings, "admin_login_backoff_after_failures", 5)

    failed = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": "wrong-password"},
    )
    assert failed.status_code == 401

    ok = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert ok.status_code == 200

    # A successful login clears the account+IP failure penalty but the separate
    # IP spray bucket remains durable.
    with SessionLocal() as db:
        account_bucket = db.scalar(
            select(auth_rate_limit.AuthRateLimitBucket)
            .where(
                auth_rate_limit.AuthRateLimitBucket.scope
                == "admin_login_account_ip"
            )
            .order_by(auth_rate_limit.AuthRateLimitBucket.updated_at.desc())
            .limit(1)
        )
        assert account_bucket is not None
        assert account_bucket.failures == 0
        assert account_bucket.blocked_until is None

