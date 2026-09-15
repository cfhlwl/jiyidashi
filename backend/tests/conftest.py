import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

TEST_DB = Path(__file__).parent / "test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["APP_ENV"] = "development"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-secret-0123456789abcdef-0123456789abcdef"
os.environ["AUTO_CREATE_SCHEMA"] = "true"

from app.main import app  # noqa: E402


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
