from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import (
    AuthProvider,
    AuthSmsOtpChallenge,
    AuthSmsOtpChallengeState,
)
from app.core.config import Settings, get_settings
from app.services.auth_identity_service import (
    AuthIdentityError,
    create_user_for_verified_identity,
    issue_authenticated_session_in_transaction,
    resolve_auth_identity,
)
from app.services.auth_rate_limit import (
    consume_sms_otp_request_attempt,
    consume_sms_otp_verify_attempt,
)
from app.services.auth_session_service import PublicAuthError
from app.services.sms_otp_provider import SmsOtpProvider, SmsOtpProviderError, get_sms_otp_provider


class SmsOtpError(RuntimeError):
    def __init__(self, code: str, status_code: int = 400, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class SmsOtpRequestResult:
    request_id: UUID
    expires_at: datetime
    cooldown_until: datetime


@dataclass(frozen=True)
class SmsOtpVerifyResult:
    tokens: object
    account_deletion_in_progress: bool
    device_id: str


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _require_secret(settings: Settings) -> bytes:
    secret = settings.auth_sms_otp_code_secret.strip()
    if not secret:
        raise SmsOtpError("AUTH_SMS_OTP_UNAVAILABLE", 503)
    return secret.encode()


def _digest(settings: Settings, *, phone: str, request_id: UUID, code: str) -> str:
    message = f"sms-otp:v1:{phone}:{request_id}:{code}".encode()
    return hmac.new(_require_secret(settings), message, hashlib.sha256).hexdigest()


def _active_key(settings: Settings, *, phone: str, device_id: str) -> str:
    message = f"sms-otp-active:v1:{phone}:{device_id}".encode()
    return hmac.new(_require_secret(settings), message, hashlib.sha256).hexdigest()


def _map_identity_error(exc: AuthIdentityError) -> SmsOtpError:
    return SmsOtpError(exc.code, exc.status_code)


def request_sms_otp(
    db: Session,
    *,
    phone: str,
    device_id: str,
    client_platform: str | None,
    device_name: str | None,
    client_ip: str,
    provider: SmsOtpProvider | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
    code_factory=None,
) -> SmsOtpRequestResult:
    current = settings or get_settings()
    provider = provider or get_sms_otp_provider(current)
    if not provider.available:
        raise SmsOtpError("AUTH_SMS_OTP_UNAVAILABLE", 503)

    from app.services.auth_identity_service import canonicalize_phone_subject

    try:
        phone_subject = canonicalize_phone_subject(phone)
    except AuthIdentityError as exc:
        raise _map_identity_error(exc) from exc
    _require_secret(current)
    consume_sms_otp_request_attempt(
        db,
        client_ip=client_ip,
        device_id=device_id,
        phone_subject=phone_subject,
    )
    now = _utc(now or datetime.now(UTC))
    active = _active_key(current, phone=phone_subject, device_id=device_id)
    existing = db.scalar(
        select(AuthSmsOtpChallenge)
        .where(AuthSmsOtpChallenge.active_key == active)
        .with_for_update()
    )
    if existing is not None:
        cooldown_until = _utc(existing.cooldown_until)
        if existing.state == AuthSmsOtpChallengeState.PENDING and cooldown_until > now:
            db.rollback()
            retry = max(1, int((cooldown_until - now).total_seconds()))
            raise SmsOtpError("AUTH_SMS_OTP_COOLDOWN", 429, retry)
        existing.state = AuthSmsOtpChallengeState.EXPIRED
        existing.active_key = None
        db.flush()

    request_id = uuid4()
    expires_at = now + timedelta(seconds=current.auth_sms_otp_code_ttl_seconds)
    cooldown_until = now + timedelta(seconds=current.auth_sms_otp_cooldown_seconds)
    code = code_factory() if code_factory is not None else f"{secrets.randbelow(1_000_000):06d}"
    row = AuthSmsOtpChallenge(
        request_id=request_id,
        active_key=active,
        phone_subject=phone_subject,
        code_digest=_digest(current, phone=phone_subject, request_id=request_id, code=code),
        code_key_version=current.auth_sms_otp_code_key_version,
        device_id=device_id,
        client_platform=client_platform,
        device_name=device_name,
        state=AuthSmsOtpChallengeState.PENDING,
        expires_at=expires_at,
        cooldown_until=cooldown_until,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SmsOtpError(
            "AUTH_SMS_OTP_COOLDOWN", 429, current.auth_sms_otp_cooldown_seconds
        ) from exc

    try:
        delivery = provider.deliver_code(
            phone_subject=phone_subject,
            code=code,
            request_id=request_id,
        )
    except SmsOtpProviderError as exc:
        failed = db.scalar(
            select(AuthSmsOtpChallenge).where(AuthSmsOtpChallenge.request_id == request_id)
        )
        if failed is not None:
            failed.state = AuthSmsOtpChallengeState.PROVIDER_ERROR
            failed.active_key = None
            failed.error_code = exc.code
            db.commit()
        code = ""
        mapped = (
            "AUTH_SMS_OTP_UNAVAILABLE"
            if exc.code == "UNAVAILABLE"
            else "AUTH_SMS_OTP_PROVIDER_ERROR"
        )
        raise SmsOtpError(mapped, 503 if exc.code == "UNAVAILABLE" else 502) from exc
    finally:
        code = ""

    delivered = db.scalar(
        select(AuthSmsOtpChallenge).where(AuthSmsOtpChallenge.request_id == request_id)
    )
    if delivered is not None:
        delivered.provider_request_id = delivery.provider_request_id
        db.commit()
    return SmsOtpRequestResult(request_id, expires_at, cooldown_until)


def verify_sms_otp(
    db: Session,
    *,
    request_id: UUID,
    code: str,
    device_id: str,
    client_platform: str | None,
    device_name: str | None,
    client_ip: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> SmsOtpVerifyResult:
    current = settings or get_settings()
    consume_sms_otp_verify_attempt(db, client_ip=client_ip, request_id=str(request_id))
    now = _utc(now or datetime.now(UTC))
    row = db.scalar(
        select(AuthSmsOtpChallenge)
        .where(AuthSmsOtpChallenge.request_id == request_id)
        .with_for_update()
    )
    if row is None or row.state != AuthSmsOtpChallengeState.PENDING:
        raise SmsOtpError(
            "AUTH_SMS_OTP_EXPIRED"
            if row is None or row.state == AuthSmsOtpChallengeState.EXPIRED
            else "AUTH_SMS_OTP_ALREADY_USED",
            410 if row is None or row.state == AuthSmsOtpChallengeState.EXPIRED else 409,
        )
    if device_id != row.device_id:
        # The installation captured at request time is the challenge authority.
        # Keep the challenge pending so the original installation can retry.
        raise SmsOtpError("AUTH_SMS_OTP_CHALLENGE_MISMATCH", 409)
    if _utc(row.expires_at) <= now:
        row.state = AuthSmsOtpChallengeState.EXPIRED
        row.active_key = None
        db.commit()
        raise SmsOtpError("AUTH_SMS_OTP_EXPIRED", 410)
    if row.attempt_count >= current.auth_sms_otp_max_attempts:
        row.state = AuthSmsOtpChallengeState.LOCKED
        row.active_key = None
        db.commit()
        raise SmsOtpError("AUTH_SMS_OTP_TOO_MANY_ATTEMPTS", 429)

    expected = _digest(current, phone=row.phone_subject, request_id=request_id, code=code)
    if not hmac.compare_digest(expected, row.code_digest):
        row.attempt_count += 1
        if row.attempt_count >= current.auth_sms_otp_max_attempts:
            row.state = AuthSmsOtpChallengeState.LOCKED
            row.active_key = None
            db.commit()
            raise SmsOtpError("AUTH_SMS_OTP_TOO_MANY_ATTEMPTS", 429)
        db.commit()
        raise SmsOtpError("AUTH_SMS_OTP_INVALID", 401)

    try:
        resolution = resolve_auth_identity(
            db, provider=AuthProvider.PHONE, subject=row.phone_subject
        )
        if resolution is None:
            created = create_user_for_verified_identity(
                db,
                provider=AuthProvider.PHONE,
                subject=row.phone_subject,
                verified_at=now,
            )
            user_id = created.user_id
        else:
            user_id = resolution.user_id
        issued = issue_authenticated_session_in_transaction(
            db,
            user_id=user_id,
            device_id=row.device_id,
            client_platform=client_platform or row.client_platform,
            device_name=device_name or row.device_name,
        )
    except (AuthIdentityError, PublicAuthError) as exc:
        row.state = AuthSmsOtpChallengeState.LOCKED
        row.active_key = None
        row.error_code = getattr(exc, "code", "AUTH_ACCOUNT_UNAVAILABLE")
        db.commit()
        raise SmsOtpError(getattr(exc, "code", "AUTH_ACCOUNT_UNAVAILABLE"), 401) from exc
    row.state = AuthSmsOtpChallengeState.VERIFIED
    row.active_key = None
    row.verified_at = now
    row.resolved_user_id = issued.tokens.user_id
    row.session_id = issued.tokens.session_id
    db.commit()
    return SmsOtpVerifyResult(issued.tokens, issued.account_deletion_in_progress, row.device_id)
