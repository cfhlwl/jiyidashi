from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import (
    AuthIdentity,
    AuthIdentityOperation,
    AuthIdentityOperationState,
    AuthIdentityOperationType,
    AuthProvider,
    AuthSession,
)
from app.core.config import Settings, get_settings
from app.models import User
from app.services.auth_identity_link_provider import (
    AuthIdentityLinkProvider,
    AuthIdentityLinkProviderError,
    ensure_recent_reauthentication,
)
from app.services.auth_identity_service import (
    AuthIdentityError,
    _link_verified_identities_without_commit,
    _unlink_identity_without_commit,
    canonicalize_subject,
)
from app.services.auth_session_service import revoke_all_sessions_in_transaction


@dataclass(frozen=True)
class IdentityMutationResult:
    request_id: UUID
    operation: AuthIdentityOperationType
    identity: AuthIdentity | None


def _settings(settings: Settings | None) -> Settings:
    return settings or get_settings()


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _digest(value: str, *, purpose: str, settings: Settings) -> str:
    key = settings.auth_identity_operation_fingerprint_secret.encode()
    if not key:
        raise AuthIdentityError("AUTH_IDENTITY_OPERATION_UNAVAILABLE", 503)
    return hmac.new(
        key,
        f"auth-005:{purpose}:v1:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _subject_hint(identity: AuthIdentity) -> str:
    subject = identity.subject
    if identity.provider is AuthProvider.EMAIL_PASSWORD and "@" in subject:
        local, domain = subject.split("@", 1)
        return f"{(local[:1] if local else '*')}***@{domain}"
    if identity.provider is AuthProvider.PHONE:
        return f"{subject[:3]}******{subject[-4:]}"
    # WeChat subjects can contain provider scope and openid/unionid. Never echo
    # a deterministic hash to the client either: low-entropy provider subjects
    # must not be brute-forceable from a UI response.
    return "linked"


def list_identities(db: Session, *, user_id: UUID) -> list[AuthIdentity]:
    return list(
        db.scalars(
            select(AuthIdentity)
            .where(AuthIdentity.user_id == user_id)
            .order_by(AuthIdentity.created_at, AuthIdentity.id)
        )
    )


def _load_operation_or_raise(
    db: Session,
    *,
    request_id: UUID,
    operation: AuthIdentityOperationType,
    user_id: UUID,
    session_id: UUID,
    request_fingerprint: str,
    fingerprint_key_version: str,
    reservation_timeout_seconds: int,
) -> tuple[AuthIdentityOperation, bool]:
    row = db.scalar(
        select(AuthIdentityOperation)
        .where(AuthIdentityOperation.request_id == request_id)
        .with_for_update()
    )
    if row is not None:
        if (
            row.operation_type != operation
            or row.user_id != user_id
            or row.session_id != session_id
            or not hmac.compare_digest(row.request_fingerprint, request_fingerprint)
        ):
            raise AuthIdentityError("AUTH_IDENTITY_OPERATION_CONFLICT", 409)
        if row.state == AuthIdentityOperationState.COMPLETED:
            return row, False
        if row.state == AuthIdentityOperationState.REJECTED:
            raise AuthIdentityError(row.error_code or "AUTH_IDENTITY_REJECTED", 409)
        age_seconds = (
            datetime.now(UTC) - _as_utc(row.created_at)
        ).total_seconds()
        if age_seconds >= reservation_timeout_seconds:
            row.state = AuthIdentityOperationState.REJECTED
            row.error_code = "AUTH_IDENTITY_OPERATION_UNKNOWN"
            row.completed_at = datetime.now(UTC)
            db.commit()
            raise AuthIdentityError("AUTH_IDENTITY_OPERATION_UNKNOWN", 503)
        raise AuthIdentityError("AUTH_IDENTITY_OPERATION_IN_PROGRESS", 409)

    row = AuthIdentityOperation(
        request_id=request_id,
        request_fingerprint=request_fingerprint,
        fingerprint_key_version=fingerprint_key_version,
        operation_type=operation,
        state=AuthIdentityOperationState.RESERVED,
        user_id=user_id,
        session_id=session_id,
    )
    db.add(row)
    try:
        db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        return _load_operation_or_raise(
            db,
            request_id=request_id,
            operation=operation,
            user_id=user_id,
            session_id=session_id,
            request_fingerprint=request_fingerprint,
            fingerprint_key_version=fingerprint_key_version,
            reservation_timeout_seconds=reservation_timeout_seconds,
        )
    return row, True


def _reserve(
    db: Session,
    *,
    request_id: UUID,
    operation: AuthIdentityOperationType,
    user_id: UUID,
    session_id: UUID,
    request_fingerprint: str,
    settings: Settings,
) -> tuple[AuthIdentityOperation, bool]:
    # The reservation is the only DB transaction before provider verification.
    # This prevents duplicate provider calls while keeping external I/O outside
    # the User/AuthIdentity critical section.
    row, reserved = _load_operation_or_raise(
        db,
        request_id=request_id,
        operation=operation,
        user_id=user_id,
        session_id=session_id,
        request_fingerprint=request_fingerprint,
        fingerprint_key_version=settings.auth_identity_operation_fingerprint_key_version,
        reservation_timeout_seconds=(
            settings.auth_identity_operation_reservation_timeout_seconds
        ),
    )
    return row, reserved


def _reject(db: Session, *, operation_id: UUID, code: str) -> None:
    db.rollback()
    row = db.scalar(
        select(AuthIdentityOperation)
        .where(AuthIdentityOperation.id == operation_id)
        .with_for_update()
    )
    if row is None:
        raise AuthIdentityError("AUTH_IDENTITY_OPERATION_NOT_FOUND", 409)
    if row.state == AuthIdentityOperationState.RESERVED:
        row.state = AuthIdentityOperationState.REJECTED
        row.error_code = code[:64]
        row.completed_at = datetime.now(UTC)
        db.commit()
    else:
        db.rollback()
    raise AuthIdentityError(code, _status_for_code(code))


def _status_for_code(code: str) -> int:
    if code in {"AUTH_ACCOUNT_UNAVAILABLE", "AUTH_SESSION_INVALID"}:
        return 401
    if code in {"AUTH_REAUTH_REQUIRED", "AUTH_PROVIDER_SCOPE_MISMATCH"}:
        return 403
    if code in {
        "AUTH_PROVIDER_UNAVAILABLE",
        "AUTH_PROVIDER_ERROR",
        "AUTH_IDENTITY_OPERATION_UNAVAILABLE",
        "AUTH_IDENTITY_OPERATION_UNKNOWN",
    }:
        return 503
    if code in {"AUTH_PROVIDER_TOKEN_INVALID", "AUTH_PROVIDER_TOKEN_REPLAYED"}:
        return 401
    if code == "ACCOUNT_DELETION_IN_PROGRESS":
        return 423
    if code in {
        "AUTH_IDENTITY_CONFLICT",
        "AUTH_IDENTITY_ALREADY_LINKED",
        "AUTH_LAST_IDENTITY_REQUIRED",
    }:
        return 409
    return 409


def _ensure_current_session(
    db: Session,
    *,
    user_id: UUID,
    session_id: UUID,
) -> None:
    row = db.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id, AuthSession.user_id == user_id)
        .with_for_update()
    )
    if row is None or row.revoked_at is not None:
        raise AuthIdentityError("AUTH_SESSION_INVALID", 401)
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.auth_disabled_at is not None:
        raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)


def _completed_result(
    db: Session,
    *,
    row: AuthIdentityOperation,
) -> IdentityMutationResult:
    identity = db.get(AuthIdentity, row.identity_id) if row.identity_id else None
    return IdentityMutationResult(
        request_id=row.request_id,
        operation=AuthIdentityOperationType(row.operation_type),
        identity=identity,
    )


def link_identity(
    db: Session,
    *,
    user_id: UUID,
    session_id: UUID,
    request_id: UUID,
    credential: str,
    reauth_credential: str,
    provider: AuthIdentityLinkProvider,
    settings: Settings | None = None,
) -> IdentityMutationResult:
    current_settings = _settings(settings)
    request_fingerprint = _digest(
        f"LINK:{credential}:{reauth_credential}",
        purpose="request",
        settings=current_settings,
    )
    operation, reserved = _reserve(
        db,
        request_id=request_id,
        operation=AuthIdentityOperationType.LINK,
        user_id=user_id,
        session_id=session_id,
        request_fingerprint=request_fingerprint,
        settings=current_settings,
    )
    if not reserved:
        return _completed_result(db, row=operation)
    operation_id = operation.id

    try:
        proof = provider.verify_link_credentials(
            credential=credential,
            reauth_credential=reauth_credential,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
        )
        if proof.user_id != user_id or proof.session_id != session_id:
            raise AuthIdentityLinkProviderError("AUTH_PROVIDER_SCOPE_MISMATCH", 403)
        ensure_recent_reauthentication(
            proof.reauthenticated_at,
            max_age_seconds=current_settings.auth_identity_link_recent_reauth_seconds,
        )
        canonical_subject = canonicalize_subject(proof.provider, proof.subject)
        operation.provider = proof.provider
        operation.subject_fingerprint = _digest(
            f"{proof.provider}:{canonical_subject}",
            purpose="subject",
            settings=current_settings,
        )
        operation.provider_request_id = proof.provider_request_id
        # Persist only redacted provider metadata before entering the identity
        # transaction. A later unique-key conflict must retain its audit proof;
        # no credential or raw subject is included in this commit.
        db.commit()
    except AuthIdentityLinkProviderError as exc:
        _reject(db, operation_id=operation_id, code=exc.code)
    except AuthIdentityError as exc:
        _reject(db, operation_id=operation_id, code=exc.code)
    except Exception:
        # Provider completion is unknown. Make the receipt terminal so a
        # retry cannot consume a one-time credential a second time.
        _reject(
            db,
            operation_id=operation_id,
            code="AUTH_IDENTITY_OPERATION_UNKNOWN",
        )

    try:
        _ensure_current_session(db, user_id=user_id, session_id=session_id)
        identity = _link_verified_identities_without_commit(
            db,
            user_id=user_id,
            provider=proof.provider,
            canonical_subjects=[canonical_subject],
            verified_at=proof.verified_at,
            secret_hash=proof.secret_hash,
            require_verified=True,
        )[0]
        db.flush()
        revoke_all_sessions_in_transaction(
            db,
            user_id=user_id,
            except_session_id=session_id,
            reason="IDENTITY_CHANGED",
        )
        operation.identity_id = identity.id
        operation.state = AuthIdentityOperationState.COMPLETED
        operation.completed_at = datetime.now(UTC)
        db.commit()
        return IdentityMutationResult(
            request_id=request_id,
            operation=AuthIdentityOperationType.LINK,
            identity=identity,
        )
    except IntegrityError:
        _reject(db, operation_id=operation_id, code="AUTH_IDENTITY_CONFLICT")
    except AuthIdentityError as exc:
        _reject(db, operation_id=operation_id, code=exc.code)
    except Exception:
        _reject(
            db,
            operation_id=operation_id,
            code="AUTH_IDENTITY_OPERATION_UNKNOWN",
        )
    raise AssertionError("unreachable")


def unlink_identity(
    db: Session,
    *,
    user_id: UUID,
    session_id: UUID,
    request_id: UUID,
    identity_id: UUID,
    reauth_credential: str,
    provider: AuthIdentityLinkProvider,
    settings: Settings | None = None,
) -> IdentityMutationResult:
    current_settings = _settings(settings)
    request_fingerprint = _digest(
        f"UNLINK:{identity_id}:{reauth_credential}",
        purpose="request",
        settings=current_settings,
    )
    operation, reserved = _reserve(
        db,
        request_id=request_id,
        operation=AuthIdentityOperationType.UNLINK,
        user_id=user_id,
        session_id=session_id,
        request_fingerprint=request_fingerprint,
        settings=current_settings,
    )
    if not reserved:
        return _completed_result(db, row=operation)
    operation_id = operation.id

    try:
        verified_at = provider.verify_reauthentication(
            reauth_credential=reauth_credential,
            user_id=user_id,
            session_id=session_id,
            request_id=request_id,
        )
        ensure_recent_reauthentication(
            verified_at,
            max_age_seconds=current_settings.auth_identity_link_recent_reauth_seconds,
        )
        operation.subject_fingerprint = _digest(
            str(identity_id),
            purpose="identity",
            settings=current_settings,
        )
        db.commit()
    except AuthIdentityLinkProviderError as exc:
        _reject(db, operation_id=operation_id, code=exc.code)
    except Exception:
        _reject(
            db,
            operation_id=operation_id,
            code="AUTH_IDENTITY_OPERATION_UNKNOWN",
        )

    try:
        _ensure_current_session(db, user_id=user_id, session_id=session_id)
        identity = _unlink_identity_without_commit(
            db,
            user_id=user_id,
            identity_id=identity_id,
            settings=current_settings,
        )
        revoke_all_sessions_in_transaction(
            db,
            user_id=user_id,
            except_session_id=session_id,
            reason="IDENTITY_CHANGED",
        )
        operation.identity_id = identity_id
        operation.state = AuthIdentityOperationState.COMPLETED
        operation.completed_at = datetime.now(UTC)
        db.commit()
        return IdentityMutationResult(
            request_id=request_id,
            operation=AuthIdentityOperationType.UNLINK,
            identity=identity,
        )
    except AuthIdentityError as exc:
        _reject(db, operation_id=operation_id, code=exc.code)
    raise AssertionError("unreachable")


def subject_hint(identity: AuthIdentity) -> str:
    return _subject_hint(identity)
