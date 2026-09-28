"""Real PostgreSQL SEC-015 durability/concurrency gate."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import engine
from app.security_models import SecurityAlert, SecuritySignalCode, SecuritySignalWindow
from app.services import auth_rate_limit
from app.services.auth_rate_limit import consume_registration_attempt
from app.services.security_alerting import (
    SecurityScope,
    record_security_signal,
    security_correlation_digest,
)


def _clean(correlation_digest: str) -> None:
    with Session(engine) as db:
        db.execute(
            delete(SecurityAlert).where(
                SecurityAlert.correlation_digest == correlation_digest
            )
        )
        db.execute(
            delete(SecuritySignalWindow).where(
                SecuritySignalWindow.correlation_digest == correlation_digest
            )
        )
        db.commit()


def main() -> None:
    base = datetime.now(UTC).replace(microsecond=0)
    raw = f"concurrent-sec015-{uuid4()}"
    digest = security_correlation_digest("register_ip", raw)
    _clean(digest)

    def trigger(_: int) -> None:
        record_security_signal(
            engine,
            signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
            correlation_kind="register_ip",
            correlation_value=raw,
            scope=SecurityScope.AUTH_REGISTER_IP,
            now=base,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(trigger, range(8)))

    # A brand-new Session observes the durable cross-worker window and one logical alert.
    with Session(engine) as db:
        windows = list(
            db.scalars(
                select(SecuritySignalWindow).where(
                    SecuritySignalWindow.correlation_digest == digest,
                    SecuritySignalWindow.rule_code
                    == SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED.value,
                )
            )
        )
        alerts = list(
            db.scalars(
                select(SecurityAlert).where(
                    SecurityAlert.correlation_digest == digest,
                    SecurityAlert.rule_code
                    == SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED.value,
                )
            )
        )
    assert len(windows) == 1, windows
    assert windows[0].signal_count == 8, windows[0].signal_count
    assert len(alerts) == 1, alerts
    assert alerts[0].signal_count == 8, alerts[0].signal_count

    # Cooldown/window rollover is intentionally eligible for a new logical alert.
    record_security_signal(
        engine,
        signal_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED,
        correlation_kind="register_ip",
        correlation_value=raw,
        scope=SecurityScope.AUTH_REGISTER_IP,
        now=base + timedelta(seconds=601),
    )
    with Session(engine) as db:
        alerts = list(
            db.scalars(
                select(SecurityAlert).where(
                    SecurityAlert.correlation_digest == digest,
                    SecurityAlert.rule_code
                    == SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED.value,
                )
            )
        )
    assert len(alerts) == 2, alerts

    # Canonical auth behavior remains authoritative: alerting is side-band only.
    old_limit = auth_rate_limit.settings.auth_register_ip_limit
    old_window = auth_rate_limit.settings.auth_register_window_seconds
    auth_rate_limit.settings.auth_register_ip_limit = 1
    auth_rate_limit.settings.auth_register_window_seconds = 600
    client_ip = f"198.51.100.{int(uuid4().int % 200) + 1}"
    try:
        with Session(engine) as db:
            consume_registration_attempt(db, client_ip)
        try:
            with Session(engine) as db:
                consume_registration_attempt(db, client_ip)
        except HTTPException as exc:
            assert exc.status_code == 429
            assert exc.detail == "AUTH_RATE_LIMITED"
            assert int(exc.headers["Retry-After"]) >= 1
        else:
            raise AssertionError("canonical registration limiter did not return 429")
    finally:
        auth_rate_limit.settings.auth_register_ip_limit = old_limit
        auth_rate_limit.settings.auth_register_window_seconds = old_window

    _clean(digest)


if __name__ == "__main__":
    main()
