import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

TEST_DB = Path(__file__).parent / "test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef-0123456789abcdef"
os.environ["ENABLE_DEV_AUTH"] = "true"
os.environ["AUTO_CREATE_SCHEMA"] = "true"

from app.auth_models import AuthRateLimitBucket  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402




@pytest.fixture(autouse=True)
def isolate_admin_login_rate_limit_buckets():
    """Keep privileged login abuse state isolated between test cases.

    Production buckets remain durable. Tests share one ASGI peer address, so without
    scoped cleanup unrelated Admin tests can consume each other's IP spray budget.
    """

    def clear() -> None:
        with SessionLocal() as db:
            db.execute(
                delete(AuthRateLimitBucket).where(
                    AuthRateLimitBucket.scope.in_(
                        ("admin_login_ip", "admin_login_account_ip")
                    )
                )
            )
            db.commit()

    clear()
    yield
    clear()


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
