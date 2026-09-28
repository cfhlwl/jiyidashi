"""Real PostgreSQL readiness/correlation gate for Production Observability V1."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import app


class _BrokenEngine:
    def connect(self):
        raise RuntimeError("postgresql://secret-user:secret-pass@private-db/internal")


async def main() -> None:
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://observability.test") as client:
            ready = await client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json() == {"status": "ready", "database": "ready"}
            assert UUID(ready.headers["X-Request-ID"])

            request_id = uuid4()
            email = f"observability-{uuid4()}@example.test"
            registered = await client.post(
                "/v1/auth/register",
                headers={"X-Request-ID": str(request_id)},
                json={
                    "email": email,
                    "password": "Observability-Test-123!",
                    "nickname": "Observability PG",
                    "timezone": "UTC",
                    "locale": "en-US",
                },
            )
            assert registered.status_code == 201, registered.text
            assert registered.headers["X-Request-ID"] == str(request_id)
            token = registered.json()["access_token"]

            user = await client.get(
                "/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": str(request_id),
                },
            )
            assert user.status_code == 200
            assert user.headers["X-Request-ID"] == str(request_id)

            original_engine = main_module.engine
            main_module.engine = _BrokenEngine()
            try:
                unavailable = await client.get("/health/ready")
            finally:
                main_module.engine = original_engine

            assert unavailable.status_code == 503
            assert unavailable.json() == {
                "status": "not_ready",
                "database": "unavailable",
            }
            assert "secret-user" not in unavailable.text
            assert "secret-pass" not in unavailable.text
            assert "private-db" not in unavailable.text


if __name__ == "__main__":
    asyncio.run(main())
