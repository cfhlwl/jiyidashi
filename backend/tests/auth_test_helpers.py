from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.auth_models import AuthIdentity, AuthProvider
from app.core.db import SessionLocal


async def register_verified_session(
    client,
    *,
    email: str,
    password: str = "correct-horse-battery-staple",
    nickname: str = "Verified Test User",
    timezone: str = "Asia/Shanghai",
    locale: str = "zh-CN",
    device_id: str | None = None,
) -> tuple[dict[str, str], UUID, dict]:
    registered = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "nickname": nickname,
            "timezone": timezone,
            "locale": locale,
        },
    )
    assert registered.status_code == 201
    user_id = UUID(registered.json()["user_id"])

    with SessionLocal() as db:
        identity = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == user_id,
                AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
            )
        )
        assert identity is not None
        identity.verified_at = datetime.now(UTC)
        db.commit()

    logged_in = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": password,
            "device_id": device_id or f"test-{uuid4()}",
            "client_platform": "test",
        },
    )
    assert logged_in.status_code == 200
    payload = logged_in.json()
    return (
        {"Authorization": f"Bearer {payload['access_token']}"},
        user_id,
        payload,
    )
