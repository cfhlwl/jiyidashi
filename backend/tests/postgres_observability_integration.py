"""Real PostgreSQL readiness/correlation gate for Production Observability V1."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url

import app.main as main_module
from app.core.config import get_settings
from app.core.db import create_readiness_engine
from app.main import app
from app.services.auth_delivery import (
    MemoryAuthEmailDelivery,
    set_auth_email_delivery_for_testing,
)


def _blackhole_listener() -> tuple[socket.socket, int, threading.Thread]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            time.sleep(3)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return listener, port, thread


async def main() -> None:
    delivery = MemoryAuthEmailDelivery()
    set_auth_email_delivery_for_testing(delivery)
    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://observability.test",
            ) as client:
                ready = await client.get("/health/ready")
                assert ready.status_code == 200
                assert ready.json() == {"status": "ready", "database": "ready"}
                assert UUID(ready.headers["X-Request-ID"])

                request_id = uuid4()
                email = f"observability-{uuid4()}@example.com"
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
                assert registered.json()["verification_required"] is True
                delivered_email, verification_token = delivery.verification_tokens[-1]
                assert delivered_email == email.casefold()

                verified = await client.post(
                    "/v1/auth/verify-email",
                    headers={"X-Request-ID": str(request_id)},
                    json={
                        "token": verification_token,
                        "device_id": "observability-integration",
                        "client_platform": "integration",
                    },
                )
                assert verified.status_code == 200, verified.text
                assert verified.headers["X-Request-ID"] == str(request_id)
                token = verified.json()["session"]["access_token"]

                user = await client.get(
                    "/v1/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Request-ID": str(request_id),
                    },
                )
                assert user.status_code == 200
                assert user.headers["X-Request-ID"] == str(request_id)

                settings = get_settings()
                original_engine = main_module.readiness_engine
                original_text = main_module.text

                listener, blackhole_port, blackhole_thread = _blackhole_listener()
                blackhole_url = make_url(settings.database_url).set(
                    host="127.0.0.1",
                    port=blackhole_port,
                )
                blackhole_engine = create_readiness_engine(
                    blackhole_url.render_as_string(hide_password=False),
                    connect_timeout_seconds=1,
                    statement_timeout_ms=250,
                )
                main_module.readiness_engine = blackhole_engine
                started = time.monotonic()
                try:
                    unavailable = await client.get("/health/ready")
                finally:
                    elapsed = time.monotonic() - started
                    main_module.readiness_engine = original_engine
                    blackhole_engine.dispose()
                    listener.close()
                    blackhole_thread.join(timeout=4)

                assert unavailable.status_code == 503
                assert unavailable.json() == {
                    "status": "not_ready",
                    "database": "unavailable",
                }
                assert elapsed < 2.5, elapsed

                statement_engine = create_readiness_engine(
                    settings.database_url,
                    connect_timeout_seconds=1,
                    statement_timeout_ms=250,
                )
                main_module.readiness_engine = statement_engine
                main_module.text = lambda _: text("SELECT pg_sleep(5)")
                started = time.monotonic()
                try:
                    statement_timeout = await client.get("/health/ready")
                finally:
                    elapsed = time.monotonic() - started
                    main_module.readiness_engine = original_engine
                    main_module.text = original_text
                    statement_engine.dispose()

                assert statement_timeout.status_code == 503
                assert statement_timeout.json() == {
                    "status": "not_ready",
                    "database": "unavailable",
                }
                assert elapsed < 2.0, elapsed
    finally:
        set_auth_email_delivery_for_testing(None)


if __name__ == "__main__":
    asyncio.run(main())
