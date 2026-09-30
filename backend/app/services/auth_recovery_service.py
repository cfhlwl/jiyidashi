from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth_models import (
    AuthIdentity,
    AuthOneTimePurpose,
    AuthOneTimeToken,
    AuthProvider,
)
from app.core.config import get_settings
from app.core.observability import emit_operational_event
from app.models import User
from app.services.auth_delivery import get_auth_email_delivery
from app.services.auth_rate_limit import (
    consume_password_reset_confirmation,
    consume_password_reset_request,
    consume_verification_resend,
)
from app.services.auth_service import hash_password, normalize_email, verify_password
from app.services.auth_session_service import revoke_all_sessions_in_transaction

settings = get_settings()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AuthRecoveryError(RuntimeError):
    def __init__(self, code: str, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class VerificationResult:
    user_id: UUID
    already_verified: bool


def one_time_token_digest(purpose: AuthOneTimePurpose, raw_token: str) -> str:
    normalized = raw_token.strip()
    if not normalized:
        return ""
    message = f"auth-one-time-v1:{purpose.value}:{normalized}".encode()
    return hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def _new_one_time_token() -> str:
    return secrets.token_urlsafe(32)


def _issue_one_time_token(
    db: Session,
    *,
    user_id: UUID,
    purpose: AuthOneTimePurpose,
    lifetime_minutes: int,
) -> str:
    now = datetime.now(UTC)
    db.execute(
        delete(AuthOneTimeToken).where(
            AuthOneTimeToken.user_id == user_id,
            AuthOneTimeToken.purpose == purpose,
            AuthOneTimeToken.consumed_at.is_(None),
        )
    )
    raw = _new_one_time_token()
    db.add(
        AuthOneTimeToken(
            user_id=user_id,
            purpose=purpose,
            digest=one_time_token_digest(purpose, raw),
            created_at=now,
            expires_at=now + timedelta(minutes=lifetime_minutes),
        )
    )
    db.commit()
    return raw


def issue_email_verification(
    db: Session,
    *,
    user_id: UUID,
) -> tuple[str, str]:
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == user_id,
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
        )
    )
    if identity is None:
        raise AuthRecoveryError("AUTH_IDENTITY_NOT_FOUND", 404)
    if identity.verified_at is not None:
        raise AuthRecoveryError("EMAIL_ALREADY_VERIFIED", 409)
    token = _issue_one_time_token(
        db,
        user_id=user_id,
        purpose=AuthOneTimePurpose.EMAIL_VERIFY,
        lifetime_minutes=settings.email_verification_minutes,
    )
    return identity.subject, token


def deliver_registration_verification(
    db: Session,
    *,
    user_id: UUID,
) -> bool:
    email, token = issue_email_verification(db, user_id=user_id)
    try:
        get_auth_email_delivery().send_verification(email=email, token=token)
        return True
    except Exception:
        # Registration is already durable at this point. Do not turn a transient SMTP
        # outage into a misleading "registration failed" response that traps the user
        # behind duplicate-registration on retry; the explicit resend path can recover.
        emit_operational_event(
            event="auth.email_verification.delivery_failed",
            level="ERROR",
            user_id=str(user_id),
            error_code="AUTH_EMAIL_DELIVERY_UNAVAILABLE",
        )
        return False


def resend_email_verification(
    db: Session,
    *,
    email: str,
    client_ip: str,
) -> None:
    subject = normalize_email(email)
    consume_verification_resend(db, client_ip, subject)
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
            AuthIdentity.subject == subject,
        )
    )
    if identity is None or identity.verified_at is not None:
        return

    token = _issue_one_time_token(
        db,
        user_id=identity.user_id,
        purpose=AuthOneTimePurpose.EMAIL_VERIFY,
        lifetime_minutes=settings.email_verification_minutes,
    )
    try:
        get_auth_email_delivery().send_verification(email=subject, token=token)
    except Exception:
        emit_operational_event(
            event="auth.email_verification.delivery_failed",
            level="ERROR",
            user_id=str(identity.user_id),
            error_code="AUTH_EMAIL_DELIVERY_UNAVAILABLE",
        )


def verify_email_token(db: Session, *, token: str) -> VerificationResult:
    digest = one_time_token_digest(AuthOneTimePurpose.EMAIL_VERIFY, token)
    if not digest:
        raise AuthRecoveryError("INVALID_VERIFICATION_TOKEN")

    row = db.scalar(
        select(AuthOneTimeToken)
        .where(
            AuthOneTimeToken.digest == digest,
            AuthOneTimeToken.purpose == AuthOneTimePurpose.EMAIL_VERIFY,
        )
        .with_for_update()
    )
    if row is None:
        raise AuthRecoveryError("INVALID_VERIFICATION_TOKEN")

    identity = db.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.user_id == row.user_id,
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
        )
        .with_for_update()
    )
    user = db.scalar(
        select(User).where(User.id == row.user_id).with_for_update(read=True, key_share=True)
    )
    if identity is None or user is None or user.auth_disabled_at is not None:
        raise AuthRecoveryError("AUTH_ACCOUNT_UNAVAILABLE", 401)

    if row.consumed_at is not None:
        if identity.verified_at is not None:
            db.rollback()
            return VerificationResult(user_id=row.user_id, already_verified=True)
        raise AuthRecoveryError("INVALID_VERIFICATION_TOKEN")

    now = datetime.now(UTC)
    if _as_utc(row.expires_at) <= now:
        raise AuthRecoveryError("VERIFICATION_TOKEN_EXPIRED")

    identity.verified_at = now
    row.consumed_at = now
    db.commit()
    emit_operational_event(
        event="auth.email_verified",
        user_id=str(row.user_id),
    )
    return VerificationResult(user_id=row.user_id, already_verified=False)


def request_password_reset(
    db: Session,
    *,
    email: str,
    client_ip: str,
) -> None:
    subject = normalize_email(email)
    consume_password_reset_request(db, client_ip, subject)
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
            AuthIdentity.subject == subject,
        )
    )
    if identity is None or identity.verified_at is None:
        return

    token = _issue_one_time_token(
        db,
        user_id=identity.user_id,
        purpose=AuthOneTimePurpose.PASSWORD_RESET,
        lifetime_minutes=settings.password_reset_minutes,
    )
    emit_operational_event(
        event="auth.password_reset.requested",
        user_id=str(identity.user_id),
    )
    try:
        get_auth_email_delivery().send_password_reset(email=subject, token=token)
    except Exception:
        emit_operational_event(
            event="auth.password_reset.delivery_failed",
            level="ERROR",
            user_id=str(identity.user_id),
            error_code="AUTH_EMAIL_DELIVERY_UNAVAILABLE",
        )


def reset_password(
    db: Session,
    *,
    token: str,
    new_password: str,
    client_ip: str,
) -> UUID:
    digest = one_time_token_digest(AuthOneTimePurpose.PASSWORD_RESET, token)
    if not digest:
        raise AuthRecoveryError("INVALID_PASSWORD_RESET_TOKEN")
    consume_password_reset_confirmation(db, client_ip, digest)

    row = db.scalar(
        select(AuthOneTimeToken)
        .where(
            AuthOneTimeToken.digest == digest,
            AuthOneTimeToken.purpose == AuthOneTimePurpose.PASSWORD_RESET,
        )
        .with_for_update()
    )
    if row is None:
        raise AuthRecoveryError("INVALID_PASSWORD_RESET_TOKEN")
    if row.consumed_at is not None:
        raise AuthRecoveryError("INVALID_PASSWORD_RESET_TOKEN")

    now = datetime.now(UTC)
    if row.expires_at <= now:
        raise AuthRecoveryError("PASSWORD_RESET_TOKEN_EXPIRED")

    identity = db.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.user_id == row.user_id,
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
        )
        .with_for_update()
    )
    user = db.scalar(select(User).where(User.id == row.user_id).with_for_update())
    if identity is None or user is None or user.auth_disabled_at is not None:
        raise AuthRecoveryError("AUTH_ACCOUNT_UNAVAILABLE", 401)

    identity.secret_hash = hash_password(new_password)
    row.consumed_at = now
    revoke_all_sessions_in_transaction(
        db,
        user_id=row.user_id,
        reason="PASSWORD_RESET",
    )
    db.commit()
    emit_operational_event(
        event="auth.password_reset.completed",
        user_id=str(row.user_id),
    )
    return row.user_id


def change_password(
    db: Session,
    *,
    user_id: UUID,
    current_password: str,
    new_password: str,
) -> None:
    identity = db.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.user_id == user_id,
            AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
        )
        .with_for_update()
    )
    if identity is None or not verify_password(identity.secret_hash, current_password):
        raise AuthRecoveryError("INVALID_CREDENTIALS", 401)

    identity.secret_hash = hash_password(new_password)
    revoke_all_sessions_in_transaction(
        db,
        user_id=user_id,
        reason="PASSWORD_CHANGED",
    )
    db.commit()
    emit_operational_event(
        event="auth.password.changed",
        user_id=str(user_id),
    )
