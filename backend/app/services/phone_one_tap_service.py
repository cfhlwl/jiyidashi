from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import (
    AuthProvider,
    AuthSession,
    PhoneOneTapExchange,
    PhoneOneTapExchangeState,
    PhoneOneTapRecoveryState,
)
from app.core.config import Settings, get_settings
from app.core.observability import emit_operational_event
from app.models import User
from app.services.auth_identity_service import (
    AuthIdentityError,
    create_user_for_verified_identity,
    issue_authenticated_session_in_transaction,
    resolve_auth_identity,
)
from app.services.auth_rate_limit import consume_phone_one_tap_attempt
from app.services.auth_session_service import (
    PublicAuthError,
    PublicSessionTokens,
    lock_installation_authority_in_transaction,
    revoke_session_in_transaction,
)
from app.services.concurrency_guard import (
    ConcurrencyRejected,
    claim_phone_one_tap_permit,
    release_permit,
)
from app.services.phone_one_tap_provider import (
    PhoneOneTapProvider,
    PhoneOneTapProviderError,
    VerifiedPhoneResult,
    get_phone_one_tap_provider,
)


class PhoneOneTapError(RuntimeError):
    def __init__(
        self,
        code: str,
        status_code: int,
        *,
        retry_after: int | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class PhoneOneTapExchangeResult:
    tokens: PublicSessionTokens
    account_deletion_in_progress: bool


@dataclass(frozen=True)
class ReservationResult:
    row: PhoneOneTapExchange
    owns_provider_call: bool


_PUBLIC_PROVIDER_CODES = {
    "INVALID": ("AUTH_PHONE_ONE_TAP_TOKEN_INVALID", 401),
    "TOKEN_INVALID": ("AUTH_PHONE_ONE_TAP_TOKEN_INVALID", 401),
    "EXPIRED": ("AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED", 401),
    "TOKEN_EXPIRED": ("AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED", 401),
    "TIMEOUT": ("AUTH_PHONE_ONE_TAP_TIMEOUT", 504),
    "UNKNOWN": ("AUTH_PHONE_ONE_TAP_TIMEOUT", 504),
    "PROVIDER_ERROR": ("AUTH_PHONE_ONE_TAP_PROVIDER_ERROR", 502),
    "UNAVAILABLE": ("AUTH_PHONE_ONE_TAP_UNAVAILABLE", 503),
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _fingerprint(login_token: str, settings: Settings) -> str:
    secret = settings.auth_phone_one_tap_fingerprint_secret.strip()
    if not secret:
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_UNAVAILABLE", 503)
    message = (
        f"auth-phone-one-tap:{settings.auth_phone_one_tap_fingerprint_key_version}:"
        f"{login_token}"
    ).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _provider_error(error: str, *, ambiguous: bool = False) -> PhoneOneTapError:
    code, status = _PUBLIC_PROVIDER_CODES.get(
        error, ("AUTH_PHONE_ONE_TAP_PROVIDER_ERROR", 502)
    )
    if ambiguous and status == 502:
        code, status = "AUTH_PHONE_ONE_TAP_TIMEOUT", 504
    return PhoneOneTapError(code, status)


def _raise_stored_exchange_error(row: PhoneOneTapExchange) -> None:
    if row.error_code == "AUTH_ACCOUNT_UNAVAILABLE":
        raise PhoneOneTapError("AUTH_ACCOUNT_UNAVAILABLE", 401)
    if row.error_code:
        status = {
            "AUTH_PHONE_ONE_TAP_TOKEN_INVALID": 401,
            "AUTH_PHONE_ONE_TAP_TOKEN_EXPIRED": 401,
            "AUTH_PHONE_ONE_TAP_PROVIDER_ERROR": 502,
            "AUTH_PHONE_ONE_TAP_TIMEOUT": 504,
        }.get(row.error_code, 409)
        raise PhoneOneTapError(row.error_code, status)
    raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TIMEOUT", 504)


def _lookup_existing(
    db: Session,
    *,
    request_id: UUID,
    token_fingerprint: str,
) -> PhoneOneTapExchange | None:
    by_request = db.scalar(
        select(PhoneOneTapExchange).where(PhoneOneTapExchange.request_id == request_id)
    )
    if by_request is not None:
        if by_request.token_fingerprint != token_fingerprint:
            raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_CONFLICT", 409)
        return by_request
    by_token = db.scalar(
        select(PhoneOneTapExchange).where(
            PhoneOneTapExchange.token_fingerprint == token_fingerprint
        )
    )
    if by_token is not None and by_token.request_id != request_id:
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED", 409)
    return by_token


def _recover_completed(
    db: Session,
    *,
    row_id: UUID,
    settings: Settings,
) -> PhoneOneTapExchangeResult:
    row = db.scalar(
        select(PhoneOneTapExchange)
        .where(PhoneOneTapExchange.id == row_id)
        .with_for_update()
    )
    if row is None or row.state != PhoneOneTapExchangeState.COMPLETED:
        db.rollback()
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TIMEOUT", 504)
    now = datetime.now(UTC)
    if (
        row.recovery_state != PhoneOneTapRecoveryState.OPEN
        or row.recovery_count >= 1
        or row.recovery_deadline is None
        or _utc(row.recovery_deadline) <= now
        or row.session_id is None
        or row.resolved_user_id is None
    ):
        db.rollback()
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED", 409)

    # Recovery follows the ordinary session authority order: User -> installation
    # advisory lock -> AuthSession. The User lock is reacquired by the shared
    # session issuer in this transaction, which is safe and prevents a reverse
    # order cycle with a concurrent normal login on this installation.
    db.scalar(
        select(User.id)
        .where(User.id == row.resolved_user_id)
        .with_for_update(read=True, key_share=True)
    )
    lock_installation_authority_in_transaction(db, row.device_id)
    original = db.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == row.session_id,
            AuthSession.user_id == row.resolved_user_id,
            AuthSession.device_id == row.device_id,
        )
        .with_for_update()
    )
    if (
        original is None
        or original.id != row.session_id
        or original.user_id != row.resolved_user_id
        or original.device_id != row.device_id
        or original.revoked_at is not None
        or _utc(original.expires_at) <= now
        or original.rotation_revision != 0
    ):
        row.recovery_state = PhoneOneTapRecoveryState.CLOSED
        row.recovery_deadline = now
        db.commit()
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED", 409)

    revoked = revoke_session_in_transaction(
        db,
        user_id=row.resolved_user_id,
        session_id=original.id,
        reason="PHONE_ONE_TAP_RECOVERY",
    )
    if not revoked[0]:
        db.rollback()
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TOKEN_REPLAYED", 409)
    try:
        issued = issue_authenticated_session_in_transaction(
            db,
            user_id=row.resolved_user_id,
            device_id=original.device_id,
            client_platform=original.client_platform,
            device_name=original.device_name,
        )
    except PublicAuthError as exc:
        row.recovery_state = PhoneOneTapRecoveryState.CLOSED
        row.recovery_deadline = now
        row.error_code = exc.code
        db.commit()
        raise PhoneOneTapError(exc.code, exc.status_code) from exc

    row.replacement_session_id = issued.tokens.session_id
    row.recovery_count += 1
    row.recovery_state = PhoneOneTapRecoveryState.CLOSED
    row.recovery_deadline = now
    row.updated_at = now
    db.commit()
    emit_operational_event(
        event="auth.phone_one_tap.recovered",
        correlation_id=str(row.id),
        operation="PHONE_ONE_TAP_EXCHANGE",
        operation_status="COMPLETED",
    )
    return PhoneOneTapExchangeResult(
        tokens=issued.tokens,
        account_deletion_in_progress=issued.account_deletion_in_progress,
    )


def _resolve_existing_exchange(
    db: Session,
    row: PhoneOneTapExchange,
    *,
    settings: Settings,
) -> PhoneOneTapExchangeResult:
    if row.state == PhoneOneTapExchangeState.COMPLETED:
        return _recover_completed(db, row_id=row.id, settings=settings)
    if row.state == PhoneOneTapExchangeState.RESERVED:
        if _utc(row.lease_expires_at) <= datetime.now(UTC):
            row.state = PhoneOneTapExchangeState.PROVIDER_UNKNOWN
            row.error_code = "AUTH_PHONE_ONE_TAP_TIMEOUT"
            row.updated_at = datetime.now(UTC)
            db.commit()
        else:
            db.rollback()
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TIMEOUT", 504)
    _raise_stored_exchange_error(row)


def _reserve_exchange(
    db: Session,
    *,
    request_id: UUID,
    token_fingerprint: str,
    device_id: str,
    client_platform: str | None,
    device_name: str | None,
    settings: Settings,
) -> ReservationResult:
    now = datetime.now(UTC)
    row = PhoneOneTapExchange(
        request_id=request_id,
        token_fingerprint=token_fingerprint,
        fingerprint_key_version=settings.auth_phone_one_tap_fingerprint_key_version,
        state=PhoneOneTapExchangeState.RESERVED,
        recovery_state=PhoneOneTapRecoveryState.CLOSED,
        device_id=device_id,
        client_platform=client_platform,
        device_name=device_name,
        lease_expires_at=now
        + timedelta(seconds=settings.auth_phone_one_tap_exchange_reservation_seconds),
        expires_at=now
        + timedelta(seconds=settings.auth_phone_one_tap_exchange_retention_seconds),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = _lookup_existing(
            db, request_id=request_id, token_fingerprint=token_fingerprint
        )
        if existing is None:
            raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_CONFLICT", 409) from exc
        return ReservationResult(row=existing, owns_provider_call=False)
    return ReservationResult(row=row, owns_provider_call=True)


def _finalize_provider_failure(
    db: Session,
    *,
    row_id: UUID,
    state: PhoneOneTapExchangeState,
    error_code: str,
) -> None:
    row = db.scalar(
        select(PhoneOneTapExchange)
        .where(PhoneOneTapExchange.id == row_id)
        .with_for_update()
    )
    if row is not None and row.state == PhoneOneTapExchangeState.RESERVED:
        now = datetime.now(UTC)
        row.state = state
        row.error_code = error_code
        row.lease_expires_at = now
        row.updated_at = now
        db.commit()
    else:
        db.rollback()


def _complete_exchange(
    db: Session,
    *,
    row_id: UUID,
    result: VerifiedPhoneResult,
    settings: Settings,
) -> PhoneOneTapExchangeResult:
    row = db.scalar(
        select(PhoneOneTapExchange)
        .where(PhoneOneTapExchange.id == row_id)
        .with_for_update()
    )
    if row is None or row.state != PhoneOneTapExchangeState.RESERVED:
        db.rollback()
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TIMEOUT", 504)
    now = datetime.now(UTC)
    if _utc(row.lease_expires_at) <= now:
        row.state = PhoneOneTapExchangeState.PROVIDER_UNKNOWN
        row.error_code = "AUTH_PHONE_ONE_TAP_TIMEOUT"
        db.commit()
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_TIMEOUT", 504)

    try:
        resolution = resolve_auth_identity(
            db,
            provider=AuthProvider.PHONE,
            subject=result.canonical_phone_subject,
        )
        if resolution is None:
            created = create_user_for_verified_identity(
                db,
                provider=AuthProvider.PHONE,
                subject=result.canonical_phone_subject,
                verified_at=result.verified_at,
            )
            user_id = created.user_id
            identity = created.identity
        else:
            user_id = resolution.user_id
            identity = resolution.identity
        identity.last_login_at = now
        issued = issue_authenticated_session_in_transaction(
            db,
            user_id=user_id,
            device_id=row.device_id,
            client_platform=row.client_platform,
            device_name=row.device_name,
        )
    except (AuthIdentityError, PublicAuthError) as exc:
        row.state = PhoneOneTapExchangeState.PROVIDER_REJECTED
        row.error_code = exc.code
        row.updated_at = now
        db.commit()
        status = exc.status_code
        raise PhoneOneTapError(exc.code, status) from exc

    row.state = PhoneOneTapExchangeState.COMPLETED
    row.recovery_state = PhoneOneTapRecoveryState.OPEN
    row.resolved_user_id = user_id
    row.session_id = issued.tokens.session_id
    row.provider_request_id = (result.provider_request_id or "")[:255] or None
    row.verified_at = result.verified_at
    row.recovery_deadline = now + timedelta(
        seconds=settings.auth_phone_one_tap_recovery_deadline_seconds
    )
    row.completed_at = now
    row.lease_expires_at = now
    row.updated_at = now
    db.commit()
    emit_operational_event(
        event="auth.phone_one_tap.completed",
        correlation_id=str(row.id),
        operation="PHONE_ONE_TAP_EXCHANGE",
        operation_status="COMPLETED",
    )
    return PhoneOneTapExchangeResult(
        tokens=issued.tokens,
        account_deletion_in_progress=issued.account_deletion_in_progress,
    )


def exchange_phone_one_tap(
    db: Session,
    *,
    login_token: str,
    request_id: UUID,
    device_id: str,
    client_platform: str | None,
    device_name: str | None,
    client_ip: str,
    provider: PhoneOneTapProvider | None = None,
    settings: Settings | None = None,
) -> PhoneOneTapExchangeResult:
    cfg = settings or get_settings()
    selected_provider = provider or get_phone_one_tap_provider()

    if not cfg.auth_phone_one_tap_fingerprint_secret.strip() or not getattr(
        selected_provider, "available", True
    ):
        consume_phone_one_tap_attempt(
            db,
            client_ip=client_ip,
            device_id=device_id,
            request_id=str(request_id),
        )
        raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_UNAVAILABLE", 503)
    token_fingerprint = _fingerprint(login_token, cfg)
    # The anonymous gate is intentionally before provider I/O. No raw token is
    # passed to rate-limit persistence; the token bucket uses the dedicated
    # server-keyed fingerprint only.
    consume_phone_one_tap_attempt(
        db,
        client_ip=client_ip,
        device_id=device_id,
        request_id=str(request_id),
        token_fingerprint=token_fingerprint,
    )

    db.rollback()
    existing = _lookup_existing(
        db, request_id=request_id, token_fingerprint=token_fingerprint
    )
    if existing is not None:
        return _resolve_existing_exchange(db, existing, settings=cfg)

    try:
        permit = claim_phone_one_tap_permit(db.get_bind(), settings=cfg)
    except ConcurrencyRejected as exc:
        raise PhoneOneTapError(
            "AUTH_RATE_LIMITED", 429, retry_after=exc.retry_after
        ) from exc

    try:
        reservation = _reserve_exchange(
            db,
            request_id=request_id,
            token_fingerprint=token_fingerprint,
            device_id=device_id,
            client_platform=client_platform,
            device_name=device_name,
            settings=cfg,
        )
        row = reservation.row
        if not reservation.owns_provider_call:
            return _resolve_existing_exchange(db, row, settings=cfg)

        if db.in_transaction():
            db.rollback()
            raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_PROVIDER_ERROR", 502)

        try:
            provider_result = selected_provider.exchange_login_token(
                login_token=login_token,
                request_id=request_id,
            )
        except PhoneOneTapProviderError as exc:
            public_error = _provider_error(exc.code, ambiguous=exc.ambiguous)
            terminal_state = (
                PhoneOneTapExchangeState.PROVIDER_UNKNOWN
                if exc.ambiguous or public_error.status_code in {502, 504}
                else PhoneOneTapExchangeState.PROVIDER_REJECTED
            )
            _finalize_provider_failure(
                db,
                row_id=row.id,
                state=terminal_state,
                error_code=public_error.code,
            )
            raise public_error from exc
        except Exception:
            _finalize_provider_failure(
                db,
                row_id=row.id,
                state=PhoneOneTapExchangeState.PROVIDER_UNKNOWN,
                error_code="AUTH_PHONE_ONE_TAP_PROVIDER_ERROR",
            )
            raise PhoneOneTapError(
                "AUTH_PHONE_ONE_TAP_PROVIDER_ERROR", 502
            ) from None

        if not isinstance(provider_result, VerifiedPhoneResult):
            _finalize_provider_failure(
                db,
                row_id=row.id,
                state=PhoneOneTapExchangeState.PROVIDER_UNKNOWN,
                error_code="AUTH_PHONE_ONE_TAP_PROVIDER_ERROR",
            )
            raise PhoneOneTapError("AUTH_PHONE_ONE_TAP_PROVIDER_ERROR", 502)

        return _complete_exchange(
            db,
            row_id=row.id,
            result=provider_result,
            settings=cfg,
        )
    finally:
        # A finalization exception can leave the request transaction failed or
        # holding provisional identity/session rows. Roll it back before the
        # independent permit-release transaction touches the same database.
        if db.in_transaction():
            db.rollback()
        release_permit(db.get_bind(), permit=permit, settings=cfg)


def purge_expired_phone_one_tap_exchanges(
    db: Session,
    *,
    batch_size: int = 100,
    now: datetime | None = None,
) -> int:
    """Delete only bounded, expired exchange receipts.

    This is a maintenance seam, not a scheduler. It deliberately targets only
    ledger rows and cannot delete users, identities, or sessions.
    """

    bounded_batch = max(1, min(int(batch_size), 1000))
    cutoff = now or datetime.now(UTC)
    ids = list(
        db.scalars(
            select(PhoneOneTapExchange.id)
            .where(PhoneOneTapExchange.expires_at <= cutoff)
            .order_by(PhoneOneTapExchange.expires_at, PhoneOneTapExchange.id)
            .limit(bounded_batch)
        )
    )
    if not ids:
        db.rollback()
        return 0
    result = db.execute(
        delete(PhoneOneTapExchange).where(PhoneOneTapExchange.id.in_(ids))
    )
    db.commit()
    return int(result.rowcount or 0)
