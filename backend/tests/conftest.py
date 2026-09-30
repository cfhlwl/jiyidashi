import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, inspect

TEST_DB = Path(__file__).parent / "test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef-0123456789abcdef"
os.environ["ENABLE_DEV_AUTH"] = "true"
os.environ["AUTO_CREATE_SCHEMA"] = "true"

from app.auth_models import AuthRateLimitBucket  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.auth_delivery import (  # noqa: E402
    MemoryAuthEmailDelivery,
    set_auth_email_delivery_for_testing,
)


_PUBLIC_AUTH_RATE_SCOPES = (
    "register_ip",
    "login_ip",
    "login_account_ip",
    "refresh_session",
    "verify_ip",
    "verify_account",
    "password_reset_ip",
    "password_reset_account",
    "password_reset_confirm",
)


def _clear_public_auth_rate_buckets() -> None:
    if not inspect(engine).has_table("auth_rate_limit_buckets"):
        return
    with SessionLocal() as db:
        db.execute(
            delete(AuthRateLimitBucket).where(
                AuthRateLimitBucket.scope.in_(_PUBLIC_AUTH_RATE_SCOPES)
            )
        )
        db.commit()


@pytest.fixture(autouse=True)
def isolate_public_auth_rate_limits():
    _clear_public_auth_rate_buckets()
    try:
        yield
    finally:
        _clear_public_auth_rate_buckets()


@pytest.fixture(autouse=True)
def auth_email_delivery():
    provider = MemoryAuthEmailDelivery()
    set_auth_email_delivery_for_testing(provider)
    try:
        yield provider
    finally:
        set_auth_email_delivery_for_testing(None)


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
async def auth_headers(client: AsyncClient):
    response = await client.post("/v1/auth/dev-token", json={"nickname": "Test User"})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
