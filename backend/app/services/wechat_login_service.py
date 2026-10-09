from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_models import (
    AuthIdentity,
    AuthProvider,
    AuthSession,
    WechatExchangeRecoveryState,
    WechatExchangeState,
    WechatLoginExchange,
)
from app.core.config import Settings, get_settings
from app.core.observability import emit_operational_event
from app.models import User
from app.services.auth_identity_service import (
    AuthIdentityError,
    create_user_for_verified_identity,
    issue_authenticated_session_in_transaction,
)
from app.services.auth_rate_limit import consume_wechat_attempt
from app.services.auth_session_service import (
    PublicAuthError,
    PublicSessionTokens,
    lock_installation_authority_in_transaction,
    revoke_session_in_transaction,
)
from app.services.concurrency_guard import (
    ConcurrencyRejected,
    claim_wechat_login_permit,
    release_permit,
)
from app.services.wechat_auth_provider import (
    VerifiedWechatResult,
    WechatAuthProvider,
    WechatProviderError,
    get_wechat_provider,
)


class WechatLoginError(RuntimeError):
    def __init__(self, code: str, status_code: int, *, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class WechatLoginResult:
    tokens: PublicSessionTokens
    account_deletion_in_progress: bool
    device_id: str


_PUBLIC_PROVIDER_CODES = {
    "INVALID": ("AUTH_WECHAT_CREDENTIAL_INVALID", 401),
    "EXPIRED": ("AUTH_WECHAT_CREDENTIAL_EXPIRED", 401),
    "TIMEOUT": ("AUTH_WECHAT_TIMEOUT", 504),
    "UNKNOWN": ("AUTH_WECHAT_TIMEOUT", 504),
    "PROVIDER_ERROR": ("AUTH_WECHAT_PROVIDER_ERROR", 502),
    "UNAVAILABLE": ("AUTH_WECHAT_UNAVAILABLE", 503),
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _fingerprint(credential: str, settings: Settings) -> str:
    secret = settings.auth_wechat_fingerprint_secret.strip()
    if not secret:
        raise WechatLoginError("AUTH_WECHAT_UNAVAILABLE", 503)
    message = (
        f"auth-wechat:{settings.auth_wechat_fingerprint_key_version}:{credential}"
    ).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _provider_error(error: str, *, ambiguous: bool = False) -> WechatLoginError:
    code, status = _PUBLIC_PROVIDER_CODES.get(
        error, ("AUTH_WECHAT_PROVIDER_ERROR", 502)
    )
    if ambiguous or status == 504:
        return WechatLoginError("AUTH_WECHAT_TIMEOUT", 504)
    return WechatLoginError(code, status)


def _stored_error(row: WechatLoginExchange) -> None:
    if row.error_code:
        status = {
            "AUTH_ACCOUNT_UNAVAILABLE": 401,
            "AUTH_WECHAT_CREDENTIAL_INVALID": 401,
            "AUTH_WECHAT_CREDENTIAL_EXPIRED": 401,
            "AUTH_WECHAT_PROVIDER_ERROR": 502,
            "AUTH_WECHAT_TIMEOUT": 504,
        }.get(row.error_code, 409)
        raise WechatLoginError(row.error_code, status)
    raise WechatLoginError("AUTH_WECHAT_TIMEOUT", 504)


def _lookup_existing(
    db: Session, *, request_id: UUID, credential_fingerprint: str
) -> WechatLoginExchange | None:
    by_request = db.scalar(
        select(WechatLoginExchange).where(WechatLoginExchange.request_id == request_id)
    )
    if by_request is not None:
        if by_request.credential_fingerprint != credential_fingerprint:
            raise WechatLoginError("AUTH_WECHAT_CONFLICT", 409)
        return by_request
    by_credential = db.scalar(
        select(WechatLoginExchange).where(
            WechatLoginExchange.credential_fingerprint == credential_fingerprint
        )
    )
    if by_credential is not None and by_credential.request_id != request_id:
        raise WechatLoginError("AUTH_WECHAT_CREDENTIAL_REPLAYED", 409)
    return by_credential


def _recover_completed(db: Session, *, row_id: UUID) -> WechatLoginResult:
    row = db.scalar(
        select(WechatLoginExchange)
        .where(WechatLoginExchange.id == row_id)
        .with_for_update()
    )
    if row is None or row.state != WechatExchangeState.COMPLETED:
        db.rollback()
        raise WechatLoginError("AUTH_WECHAT_TIMEOUT", 504)
    now = datetime.now(UTC)
    if (
        row.recovery_state != WechatExchangeRecoveryState.OPEN
        or row.recovery_count >= 1
        or row.recovery_deadline is None
        or _utc(row.recovery_deadline) <= now
        or row.session_id is None
        or row.resolved_user_id is None
    ):
        db.rollback()
        raise WechatLoginError("AUTH_WECHAT_CREDENTIAL_REPLAYED", 409)

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
        or original.revoked_at is not None
        or _utc(original.expires_at) <= now
        or original.rotation_revision != 0
    ):
        row.recovery_state = WechatExchangeRecoveryState.CLOSED
        row.recovery_deadline = now
        db.commit()
        raise WechatLoginError("AUTH_WECHAT_CREDENTIAL_REPLAYED", 409)

    revoked = revoke_session_in_transaction(
        db,
        user_id=row.resolved_user_id,
        session_id=original.id,
        reason="WECHAT_LOGIN_RECOVERY",
    )
    if not revoked[0]:
        db.rollback()
        raise WechatLoginError("AUTH_WECHAT_CREDENTIAL_REPLAYED", 409)
    try:
        issued = issue_authenticated_session_in_transaction(
            db,
            user_id=row.resolved_user_id,
            device_id=row.device_id,
            client_platform=original.client_platform,
            device_name=original.device_name,
        )
    except PublicAuthError as exc:
        row.recovery_state = WechatExchangeRecoveryState.CLOSED
        row.recovery_deadline = now
        row.error_code = exc.code
        db.commit()
        raise WechatLoginError(exc.code, exc.status_code) from exc

    row.replacement_session_id = issued.tokens.session_id
    row.recovery_count += 1
    row.recovery_state = WechatExchangeRecoveryState.CLOSED
    row.recovery_deadline = now
    row.updated_at = now
    db.commit()
    return WechatLoginResult(
        tokens=issued.tokens,
        account_deletion_in_progress=issued.account_deletion_in_progress,
        device_id=row.device_id,
    )


def _resolve_verified_identity(
    db: Session,
    *,
    result: VerifiedWechatResult,
) -> tuple[UUID, str]:
    subjects = result.canonical_subjects()
    identities = list(
        db.scalars(
            select(AuthIdentity)
            .where(
                AuthIdentity.provider == AuthProvider.WECHAT,
                AuthIdentity.subject.in_(subjects),
            )
            .with_for_update()
        )
    )
    user_ids = {identity.user_id for identity in identities}
    if len(user_ids) > 1:
        raise AuthIdentityError("AUTH_IDENTITY_CONFLICT", 409)

    now = result.verified_at
    if user_ids:
        user_id = next(iter(user_ids))
        user = db.get(User, user_id)
        if user is None or user.auth_disabled_at is not None:
            raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)
        by_subject = {identity.subject: identity for identity in identities}
        for subject in subjects:
            identity = by_subject.get(subject)
            if identity is None:
                db.add(
                    AuthIdentity(
                        user_id=user_id,
                        provider=AuthProvider.WECHAT,
                        subject=subject,
                        verified_at=now,
                    )
                )
            else:
                identity.last_login_at = datetime.now(UTC)
        return user_id, subjects[0]

    created = create_user_for_verified_identity(
        db,
        provider=AuthProvider.WECHAT,
        subject=subjects[0],
        verified_at=now,
    )
    user_id = created.user_id
    if created.created:
        for subject in subjects[1:]:
            db.add(
                AuthIdentity(
                    user_id=user_id,
                    provider=AuthProvider.WECHAT,
                    subject=subject,
                    verified_at=now,
                )
            )
    return user_id, subjects[0]


def _complete(
    db: Session,
    *,
    row_id: UUID,
    result: VerifiedWechatResult,
    settings: Settings,
) -> WechatLoginResult:
    row = db.scalar(
        select(WechatLoginExchange)
        .where(WechatLoginExchange.id == row_id)
        .with_for_update()
    )
    if row is None or row.state != WechatExchangeState.RESERVED:
        db.rollback()
        raise WechatLoginError("AUTH_WECHAT_TIMEOUT", 504)
    now = datetime.now(UTC)
    if _utc(row.lease_expires_at) <= now:
        row.state = WechatExchangeState.PROVIDER_UNKNOWN
        row.error_code = "AUTH_WECHAT_TIMEOUT"
        db.commit()
        raise WechatLoginError("AUTH_WECHAT_TIMEOUT", 504)
    try:
        user_id, primary_subject = _resolve_verified_identity(db, result=result)
        issued = issue_authenticated_session_in_transaction(
            db,
            user_id=user_id,
            device_id=row.device_id,
            client_platform=row.client_platform,
            device_name=row.device_name,
        )
    except (AuthIdentityError, PublicAuthError) as exc:
        row.state = WechatExchangeState.PROVIDER_REJECTED
        row.error_code = exc.code
        row.updated_at = now
        db.commit()
        raise WechatLoginError(exc.code, exc.status_code) from exc
    row.state = WechatExchangeState.COMPLETED
    row.recovery_state = WechatExchangeRecoveryState.OPEN
    row.resolved_user_id = user_id
    row.session_id = issued.tokens.session_id
    row.subject = primary_subject
    row.provider_request_id = (result.provider_request_id or "")[:255] or None
    row.verified_at = result.verified_at
    row.recovery_deadline = now + timedelta(
        seconds=settings.auth_wechat_recovery_deadline_seconds
    )
    row.completed_at = now
    row.lease_expires_at = now
    row.updated_at = now
    db.commit()
    emit_operational_event(
        event="auth.wechat_login.completed",
        correlation_id=str(row.id),
        operation="WECHAT_LOGIN_EXCHANGE",
        operation_status="COMPLETED",
    )
    return WechatLoginResult(
        tokens=issued.tokens,
        account_deletion_in_progress=issued.account_deletion_in_progress,
        device_id=row.device_id,
    )


def exchange_wechat_credential(
    db: Session,
    *,
    credential: str,
    request_id: UUID,
    device_id: str,
    client_platform: str | None,
    device_name: str | None,
    client_ip: str,
    provider: WechatAuthProvider | None = None,
    settings: Settings | None = None,
) -> WechatLoginResult:
    cfg = settings or get_settings()
    selected_provider = provider or get_wechat_provider(cfg)
    if not cfg.auth_wechat_fingerprint_secret.strip() or not getattr(
        selected_provider, "available", True
    ):
        consume_wechat_attempt(
            db,
            client_ip=client_ip,
            device_id=device_id,
            request_id=str(request_id),
        )
        raise WechatLoginError("AUTH_WECHAT_UNAVAILABLE", 503)
    credential_fingerprint = _fingerprint(credential, cfg)
    consume_wechat_attempt(
        db,
        client_ip=client_ip,
        device_id=device_id,
        request_id=str(request_id),
        credential_fingerprint=credential_fingerprint,
    )
    db.rollback()
    existing = _lookup_existing(
        db, request_id=request_id, credential_fingerprint=credential_fingerprint
    )
    if existing is not None:
        if existing.state == WechatExchangeState.COMPLETED:
            return _recover_completed(db, row_id=existing.id)
        if existing.state == WechatExchangeState.RESERVED:
            db.rollback()
            raise WechatLoginError("AUTH_WECHAT_TIMEOUT", 504)
        _stored_error(existing)

    try:
        now = datetime.now(UTC)
        row = WechatLoginExchange(
            request_id=request_id,
            credential_fingerprint=credential_fingerprint,
            fingerprint_key_version=cfg.auth_wechat_fingerprint_key_version,
            state=WechatExchangeState.RESERVED,
            recovery_state=WechatExchangeRecoveryState.CLOSED,
            device_id=device_id,
            client_platform=client_platform,
            device_name=device_name,
            lease_expires_at=now
            + timedelta(seconds=cfg.auth_wechat_exchange_reservation_seconds),
            expires_at=now
            + timedelta(seconds=cfg.auth_wechat_exchange_retention_seconds),
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            existing = _lookup_existing(
                db,
                request_id=request_id,
                credential_fingerprint=credential_fingerprint,
            )
            if existing is None:
                raise WechatLoginError("AUTH_WECHAT_CONFLICT", 409) from exc
            if existing.state == WechatExchangeState.COMPLETED:
                return _recover_completed(db, row_id=existing.id)
            _stored_error(existing)

        permit = claim_wechat_login_permit(db.get_bind(), settings=cfg)
        try:
            if db.in_transaction():
                db.rollback()
            try:
                provider_result = selected_provider.exchange_credential(
                    credential=credential, request_id=request_id
                )
            except WechatProviderError as exc:
                public_error = _provider_error(exc.code, ambiguous=exc.ambiguous)
                state = (
                    WechatExchangeState.PROVIDER_UNKNOWN
                    if exc.ambiguous or public_error.status_code in {502, 504}
                    else WechatExchangeState.PROVIDER_REJECTED
                )
                failed = db.scalar(
                    select(WechatLoginExchange)
                    .where(WechatLoginExchange.id == row.id)
                    .with_for_update()
                )
                if failed is not None:
                    failed.state = state
                    failed.error_code = public_error.code
                    failed.lease_expires_at = datetime.now(UTC)
                    failed.updated_at = datetime.now(UTC)
                    db.commit()
                raise public_error from exc
            except Exception:
                failed = db.scalar(
                    select(WechatLoginExchange)
                    .where(WechatLoginExchange.id == row.id)
                    .with_for_update()
                )
                if failed is not None:
                    failed.state = WechatExchangeState.PROVIDER_UNKNOWN
                    failed.error_code = "AUTH_WECHAT_PROVIDER_ERROR"
                    failed.lease_expires_at = datetime.now(UTC)
                    failed.updated_at = datetime.now(UTC)
                    db.commit()
                raise WechatLoginError("AUTH_WECHAT_PROVIDER_ERROR", 502) from None
            if not isinstance(provider_result, VerifiedWechatResult):
                failed = db.scalar(
                    select(WechatLoginExchange)
                    .where(WechatLoginExchange.id == row.id)
                    .with_for_update()
                )
                if failed is not None:
                    failed.state = WechatExchangeState.PROVIDER_UNKNOWN
                    failed.error_code = "AUTH_WECHAT_PROVIDER_ERROR"
                    failed.lease_expires_at = datetime.now(UTC)
                    failed.updated_at = datetime.now(UTC)
                    db.commit()
                raise WechatLoginError("AUTH_WECHAT_PROVIDER_ERROR", 502)
            return _complete(db, row_id=row.id, result=provider_result, settings=cfg)
        finally:
            if db.in_transaction():
                db.rollback()
            release_permit(db.get_bind(), permit=permit, settings=cfg)
    except ConcurrencyRejected as exc:
        raise WechatLoginError("AUTH_RATE_LIMITED", 429, retry_after=exc.retry_after) from exc
