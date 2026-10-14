"""PostgreSQL proof for AUTH-003 SMS OTP consumption and send races.

This module is intentionally named outside the default ``test_*.py`` pattern.
The PostgreSQL gate invokes it explicitly with a real DATABASE_URL; the normal
SQLite unit suite must not silently substitute for these transaction proofs.
"""

from __future__ import annotations

import os
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.auth_models import AuthIdentity, AuthProvider, AuthSession, AuthSmsOtpChallenge
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.entitlement_models import UserEntitlement
from app.models import User
from app.services.auth_rate_limit import settings as rate_limit_settings
from app.services.sms_otp_provider import SmsOtpDelivery
from app.services.sms_otp_service import SmsOtpError, request_sms_otp, verify_sms_otp

DATABASE_URL = os.environ["DATABASE_URL"]
_THREAD_TIMEOUT = 30


def _require_real_postgresql() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("AUTH-003 gate requires PostgreSQL DATABASE_URL")


class _RecordingProvider:
    available = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, str]] = []

    def deliver_code(self, *, phone_subject: str, code: str, request_id: UUID) -> SmsOtpDelivery:
        self.calls.append((phone_subject, request_id, code))
        return SmsOtpDelivery(provider_request_id=f"pg-fake-{request_id}")


def _settings():
    settings = get_settings()
    settings.auth_sms_otp_code_secret = "auth-003-postgres-only-secret"
    # These tests prove database authority, not the separate rate-policy gate.
    rate_limit_settings.auth_rate_limit_enabled = False
    return settings


def _cleanup(phone: str, request_ids: set[UUID]) -> None:
    with SessionLocal() as db:
        user_ids = set(
            db.scalars(
                select(AuthSmsOtpChallenge.resolved_user_id).where(
                    AuthSmsOtpChallenge.request_id.in_(request_ids),
                    AuthSmsOtpChallenge.resolved_user_id.is_not(None),
                )
            )
        )
        db.execute(
            delete(AuthSmsOtpChallenge).where(AuthSmsOtpChallenge.request_id.in_(request_ids))
        )
        if user_ids:
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
            db.execute(delete(AuthIdentity).where(AuthIdentity.user_id.in_(user_ids)))
            db.execute(delete(UserEntitlement).where(UserEntitlement.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
        db.commit()


def _join(*threads: Thread) -> None:
    for thread in threads:
        thread.join(timeout=_THREAD_TIMEOUT)
        assert not thread.is_alive(), f"thread did not finish: {thread.name}"


def test_postgres_sms_otp_same_code_has_one_winner_and_one_session() -> None:
    settings = _settings()
    provider = _RecordingProvider()
    phone = f"+861{uuid4().int % 10_000_000_000:010d}"
    with SessionLocal() as db:
        requested = request_sms_otp(
            db,
            phone=phone,
            device_id="auth-003-pg-device",
            client_platform="postgres-test",
            device_name=None,
            client_ip="auth-003-pg-ip",
            provider=provider,
            settings=settings,
            code_factory=lambda: "123456",
        )
    request_id = requested.request_id
    barrier = Barrier(2)
    successes = []
    failures: list[str] = []

    def verify() -> None:
        with SessionLocal() as db:
            try:
                barrier.wait(timeout=_THREAD_TIMEOUT)
                successes.append(
                    verify_sms_otp(
                        db,
                        request_id=request_id,
                        code="123456",
                        device_id="auth-003-pg-device",
                        client_platform="postgres-test",
                        device_name=None,
                        client_ip="auth-003-pg-verify-ip",
                        settings=settings,
                    )
                )
            except SmsOtpError as exc:
                failures.append(exc.code)

    threads = [
        Thread(target=verify, name="auth-003-sms-verify-a"),
        Thread(target=verify, name="auth-003-sms-verify-b"),
    ]
    for thread in threads:
        thread.start()
    _join(*threads)
    assert len(successes) == 1
    assert failures == ["AUTH_SMS_OTP_ALREADY_USED"]
    assert len(provider.calls) == 1

    with SessionLocal() as db:
        row = db.scalar(
            select(AuthSmsOtpChallenge).where(
                AuthSmsOtpChallenge.request_id == request_id
            )
        )
        assert row is not None
        assert getattr(row.state, "value", row.state) == "VERIFIED"
        assert row.resolved_user_id is not None and row.session_id is not None
        assert (
            db.scalar(
                select(func.count(AuthIdentity.id)).where(
                    AuthIdentity.provider == AuthProvider.PHONE,
                    AuthIdentity.subject == phone,
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.id == row.session_id,
                )
            )
            == 1
        )
    _cleanup(phone, {request_id})


def test_postgres_sms_otp_same_phone_device_send_has_one_provider_call() -> None:
    settings = _settings()
    provider = _RecordingProvider()
    phone = f"+861{uuid4().int % 10_000_000_000:010d}"
    barrier = Barrier(2)
    successes = []
    failures: list[str] = []

    def request_code() -> None:
        with SessionLocal() as db:
            try:
                barrier.wait(timeout=_THREAD_TIMEOUT)
                successes.append(
                    request_sms_otp(
                        db,
                        phone=phone,
                        device_id="auth-003-pg-device",
                        client_platform="postgres-test",
                        device_name=None,
                        client_ip="auth-003-pg-ip",
                        provider=provider,
                        settings=settings,
                        code_factory=lambda: "654321",
                    )
                )
            except SmsOtpError as exc:
                failures.append(exc.code)

    threads = [
        Thread(target=request_code, name="auth-003-sms-request-a"),
        Thread(target=request_code, name="auth-003-sms-request-b"),
    ]
    for thread in threads:
        thread.start()
    _join(*threads)
    assert len(successes) == 1
    assert failures == ["AUTH_SMS_OTP_COOLDOWN"]
    assert len(provider.calls) == 1
    _cleanup(phone, {successes[0].request_id})


def main() -> None:
    _require_real_postgresql()
    test_postgres_sms_otp_same_code_has_one_winner_and_one_session()
    test_postgres_sms_otp_same_phone_device_send_has_one_provider_call()
    print("PostgreSQL AUTH-003 phone SMS OTP authority PASS")


if __name__ == "__main__":
    main()
