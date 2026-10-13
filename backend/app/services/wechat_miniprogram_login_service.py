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
    WechatMiniProgramExchange,
    WechatMiniProgramExchangeState,
)
from app.core.config import Settings, get_settings
from app.core.observability import emit_operational_event
from app.models import User
from app.services.auth_identity_service import (
    AuthIdentityError,
    create_user_for_verified_identity,
    issue_authenticated_session_in_transaction,
)
from app.services.auth_rate_limit import consume_wechat_miniprogram_attempt
from app.services.auth_session_service import PublicAuthError, PublicSessionTokens
from app.services.concurrency_guard import (
    ConcurrencyRejected,
    claim_wechat_miniprogram_permit,
    release_permit,
)
from app.services.wechat_miniprogram_provider import (
    VerifiedWechatMiniProgramResult,
    WechatMiniProgramProvider,
    WechatMiniProgramProviderError,
    get_wechat_miniprogram_provider,
)


class WechatMiniProgramLoginError(RuntimeError):
    def __init__(self, code: str, status_code: int, *, retry_after: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class WechatMiniProgramLoginResult:
    tokens: PublicSessionTokens
    account_deletion_in_progress: bool
    device_id: str


_PUBLIC_CODES = {
    "INVALID": ("AUTH_WECHAT_MINIPROGRAM_CODE_INVALID", 401),
    "REPLAYED": ("AUTH_WECHAT_MINIPROGRAM_CODE_REPLAYED", 409),
    "RATE_LIMITED": ("AUTH_RATE_LIMITED", 429),
    "PROVIDER_REJECTED": ("AUTH_WECHAT_MINIPROGRAM_PROVIDER_REJECTED", 401),
    "TIMEOUT": ("AUTH_WECHAT_MINIPROGRAM_TIMEOUT", 504),
    "PROVIDER_ERROR": ("AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR", 502),
    "UNAVAILABLE": ("AUTH_WECHAT_MINIPROGRAM_UNAVAILABLE", 503),
}


def _fingerprint(code: str, settings: Settings) -> str:
    secret = settings.auth_wechat_miniprogram_fingerprint_secret.strip()
    if not secret:
        raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_UNAVAILABLE", 503)
    message = (
        f"auth-wechat-miniprogram:{settings.auth_wechat_miniprogram_fingerprint_key_version}:{code}"
    ).encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _provider_error(error: str, *, ambiguous: bool = False) -> WechatMiniProgramLoginError:
    code, status = _PUBLIC_CODES.get(error, _PUBLIC_CODES["PROVIDER_ERROR"])
    if ambiguous:
        return WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_TIMEOUT", 504)
    return WechatMiniProgramLoginError(code, status)


def _stored_error(row: WechatMiniProgramExchange) -> None:
    if row.error_code:
        status = {
            "AUTH_WECHAT_MINIPROGRAM_CODE_INVALID": 401,
            "AUTH_WECHAT_MINIPROGRAM_CODE_REPLAYED": 409,
            "AUTH_RATE_LIMITED": 429,
            "AUTH_WECHAT_MINIPROGRAM_PROVIDER_REJECTED": 401,
            "AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR": 502,
            "AUTH_WECHAT_MINIPROGRAM_TIMEOUT": 504,
        }.get(row.error_code, 409)
        raise WechatMiniProgramLoginError(row.error_code, status)
    raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_TIMEOUT", 504)


def _utc(value: datetime) -> datetime:
    """Normalize SQLite-naive and PostgreSQL-aware timestamps at the boundary."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _finalize_failure(
    db: Session,
    *,
    row_id: UUID,
    state: WechatMiniProgramExchangeState,
    error_code: str,
) -> None:
    row = db.scalar(
        select(WechatMiniProgramExchange)
        .where(WechatMiniProgramExchange.id == row_id)
        .with_for_update()
    )
    if row is not None and row.state == WechatMiniProgramExchangeState.RESERVED:
        now = datetime.now(UTC)
        row.state = state
        row.error_code = error_code
        row.lease_expires_at = now
        row.updated_at = now
        db.commit()
    else:
        db.rollback()


def _lookup_existing(
    db: Session, *, request_id: UUID, credential_fingerprint: str
) -> WechatMiniProgramExchange | None:
    by_request = db.scalar(
        select(WechatMiniProgramExchange).where(
            WechatMiniProgramExchange.request_id == request_id
        )
    )
    if by_request is not None:
        if by_request.credential_fingerprint != credential_fingerprint:
            raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_CONFLICT", 409)
        if by_request.state == WechatMiniProgramExchangeState.COMPLETED:
            raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_CODE_REPLAYED", 409)
        if by_request.state == WechatMiniProgramExchangeState.PROVIDER_REJECTED:
            _stored_error(by_request)
        raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_TIMEOUT", 504)
    by_credential = db.scalar(
        select(WechatMiniProgramExchange).where(
            WechatMiniProgramExchange.credential_fingerprint == credential_fingerprint
        )
    )
    if by_credential is not None:
        raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_CODE_REPLAYED", 409)
    return None


def _subject(result: VerifiedWechatMiniProgramResult) -> str:
    if not result.app_id.strip() or not result.openid.strip():
        raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR", 502)
    return f"openid:{result.app_id.strip()}:{result.openid.strip()}"


def _resolve_identity(
    db: Session, *, result: VerifiedWechatMiniProgramResult
) -> tuple[UUID, str]:
    subject = _subject(result)
    identity = db.scalar(
        select(AuthIdentity)
        .where(
            AuthIdentity.provider == AuthProvider.WECHAT_MINIPROGRAM,
            AuthIdentity.subject == subject,
        )
        .with_for_update()
    )
    if identity is not None:
        user = db.get(User, identity.user_id)
        if user is None or user.auth_disabled_at is not None:
            raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)
        identity.last_login_at = datetime.now(UTC)
        return user.id, subject
    created = create_user_for_verified_identity(
        db,
        provider=AuthProvider.WECHAT_MINIPROGRAM,
        subject=subject,
        verified_at=result.verified_at,
    )
    user = db.get(User, created.user_id)
    if user is None or user.auth_disabled_at is not None:
        raise AuthIdentityError("AUTH_ACCOUNT_UNAVAILABLE", 401)
    return user.id, subject


def _complete(
    db: Session,
    *,
    row_id: UUID,
    result: VerifiedWechatMiniProgramResult,
    settings: Settings,
) -> WechatMiniProgramLoginResult:
    row = db.scalar(
        select(WechatMiniProgramExchange)
        .where(WechatMiniProgramExchange.id == row_id)
        .with_for_update()
    )
    if row is None or row.state != WechatMiniProgramExchangeState.RESERVED:
        db.rollback()
        raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_TIMEOUT", 504)
    now = datetime.now(UTC)
    if _utc(row.lease_expires_at) <= now:
        row.state = WechatMiniProgramExchangeState.PROVIDER_UNKNOWN
        row.error_code = "AUTH_WECHAT_MINIPROGRAM_TIMEOUT"
        db.commit()
        raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_TIMEOUT", 504)
    business = db.begin_nested()
    try:
        user_id, subject = _resolve_identity(db, result=result)
        issued = issue_authenticated_session_in_transaction(
            db,
            user_id=user_id,
            device_id=row.device_id,
            client_platform=row.client_platform,
            device_name=row.device_name,
        )
    except (AuthIdentityError, PublicAuthError, WechatMiniProgramLoginError) as exc:
        business.rollback()
        failed = db.scalar(
            select(WechatMiniProgramExchange)
            .where(WechatMiniProgramExchange.id == row_id)
            .with_for_update()
        )
        if failed is not None:
            failed.state = WechatMiniProgramExchangeState.PROVIDER_REJECTED
            failed.error_code = exc.code
            failed.lease_expires_at = now
            failed.updated_at = now
            db.commit()
        raise WechatMiniProgramLoginError(exc.code, exc.status_code) from exc
    except IntegrityError as exc:
        business.rollback()
        failed = db.scalar(
            select(WechatMiniProgramExchange)
            .where(WechatMiniProgramExchange.id == row_id)
            .with_for_update()
        )
        if failed is not None:
            failed.state = WechatMiniProgramExchangeState.PROVIDER_REJECTED
            failed.error_code = "AUTH_IDENTITY_CONFLICT"
            failed.lease_expires_at = now
            failed.updated_at = now
            db.commit()
        raise WechatMiniProgramLoginError("AUTH_IDENTITY_CONFLICT", 409) from exc
    else:
        business.commit()
    row.state = WechatMiniProgramExchangeState.COMPLETED
    row.resolved_user_id = user_id
    row.session_id = issued.tokens.session_id
    row.subject = subject
    row.provider_request_id = (result.provider_request_id or "")[:255] or None
    row.verified_at = result.verified_at
    row.completed_at = now
    row.lease_expires_at = now
    db.commit()
    emit_operational_event(
        event="auth.wechat_miniprogram_login.completed",
        correlation_id=str(row.id),
        operation="WECHAT_MINIPROGRAM_EXCHANGE",
        operation_status="COMPLETED",
    )
    return WechatMiniProgramLoginResult(
        tokens=issued.tokens,
        account_deletion_in_progress=issued.account_deletion_in_progress,
        device_id=row.device_id,
    )


def exchange_wechat_miniprogram_code(
    db: Session,
    *,
    code: str,
    request_id: UUID,
    device_id: str,
    client_platform: str | None,
    device_name: str | None,
    client_ip: str,
    provider: WechatMiniProgramProvider | None = None,
    settings: Settings | None = None,
) -> WechatMiniProgramLoginResult:
    cfg = settings or get_settings()
    selected = provider or get_wechat_miniprogram_provider(cfg)
    if (
        not cfg.auth_wechat_miniprogram_fingerprint_secret.strip()
        or not cfg.auth_wechat_miniprogram_app_id.strip()
        or not getattr(selected, "available", True)
    ):
        consume_wechat_miniprogram_attempt(
            db, client_ip=client_ip, device_id=device_id, request_id=str(request_id)
        )
        raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_UNAVAILABLE", 503)
    fingerprint = _fingerprint(code, cfg)
    consume_wechat_miniprogram_attempt(
        db,
        client_ip=client_ip,
        device_id=device_id,
        request_id=str(request_id),
        credential_fingerprint=fingerprint,
    )
    db.rollback()
    existing = _lookup_existing(db, request_id=request_id, credential_fingerprint=fingerprint)
    if existing is not None:
        _stored_error(existing)
    now = datetime.now(UTC)
    row = WechatMiniProgramExchange(
        request_id=request_id,
        credential_fingerprint=fingerprint,
        fingerprint_key_version=cfg.auth_wechat_miniprogram_fingerprint_key_version,
        state=WechatMiniProgramExchangeState.RESERVED,
        device_id=device_id,
        client_platform=client_platform,
        device_name=device_name,
        lease_expires_at=now
        + timedelta(seconds=cfg.auth_wechat_miniprogram_exchange_reservation_seconds),
        expires_at=now
        + timedelta(seconds=cfg.auth_wechat_miniprogram_exchange_retention_seconds),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = _lookup_existing(db, request_id=request_id, credential_fingerprint=fingerprint)
        if existing is None:
            raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_CONFLICT", 409) from exc
        _stored_error(existing)

    try:
        permit = claim_wechat_miniprogram_permit(db.get_bind(), settings=cfg)
    except ConcurrencyRejected as exc:
        _finalize_failure(
            db,
            row_id=row.id,
            state=WechatMiniProgramExchangeState.PROVIDER_REJECTED,
            error_code="AUTH_RATE_LIMITED",
        )
        raise WechatMiniProgramLoginError(
            "AUTH_RATE_LIMITED", 429, retry_after=exc.retry_after
        ) from exc
    try:
        db.rollback()
        try:
            provider_result = selected.exchange_code(code=code, request_id=request_id)
        except WechatMiniProgramProviderError as exc:
            public_error = _provider_error(exc.code, ambiguous=exc.ambiguous)
            state = (
                WechatMiniProgramExchangeState.PROVIDER_UNKNOWN
                if exc.ambiguous or public_error.status_code in {502, 504}
                else WechatMiniProgramExchangeState.PROVIDER_REJECTED
            )
            _finalize_failure(
                db,
                row_id=row.id,
                state=state,
                error_code=public_error.code,
            )
            raise public_error from exc
        except Exception:
            _finalize_failure(
                db,
                row_id=row.id,
                state=WechatMiniProgramExchangeState.PROVIDER_UNKNOWN,
                error_code="AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR",
            )
            raise WechatMiniProgramLoginError(
                "AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR", 502
            ) from None
        if not isinstance(provider_result, VerifiedWechatMiniProgramResult):
            _finalize_failure(
                db,
                row_id=row.id,
                state=WechatMiniProgramExchangeState.PROVIDER_UNKNOWN,
                error_code="AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR",
            )
            raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR", 502)
        if provider_result.app_id != cfg.auth_wechat_miniprogram_app_id.strip():
            _finalize_failure(
                db,
                row_id=row.id,
                state=WechatMiniProgramExchangeState.PROVIDER_REJECTED,
                error_code="AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR",
            )
            raise WechatMiniProgramLoginError("AUTH_WECHAT_MINIPROGRAM_PROVIDER_ERROR", 502)
        return _complete(db, row_id=row.id, result=provider_result, settings=cfg)
    finally:
        if db.in_transaction():
            db.rollback()
        release_permit(db.get_bind(), permit=permit, settings=cfg)
