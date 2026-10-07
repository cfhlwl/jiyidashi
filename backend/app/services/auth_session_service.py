from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.auth_models import AuthRefreshTokenReceipt, AuthSession
from app.core.config import get_settings
from app.core.observability import emit_operational_event
from app.core.security import AccessTokenClaims, create_access_token
from app.models import User
from app.security_models import SecuritySignalCode
from app.services.auth_rate_limit import consume_refresh_attempt
from app.services.security_alerting import SecurityScope, record_security_signal

settings = get_settings()


class PublicAuthError(RuntimeError):
    def __init__(self, code: str, status_code: int = 401):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class PublicSessionTokens:
    access_token: str
    refresh_token: str
    session_id: UUID
    user_id: UUID
    expires_at: datetime
    refresh_expires_at: datetime


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def refresh_token_digest(raw_token: str) -> str:
    normalized = raw_token.strip()
    if not normalized:
        return ""
    message = f"public-refresh-v1:{normalized}".encode()
    return hmac.new(settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()


def _new_refresh_token() -> str:
    # 384 bits of entropy before URL-safe encoding.
    return secrets.token_urlsafe(48)


def _session_tokens(session: AuthSession, refresh_token: str) -> PublicSessionTokens:
    now = datetime.now(UTC)
    return PublicSessionTokens(
        access_token=create_access_token(session.user_id, session.id),
        refresh_token=refresh_token,
        session_id=session.id,
        user_id=session.user_id,
        expires_at=now + timedelta(minutes=settings.access_token_minutes),
        refresh_expires_at=_as_utc(session.expires_at),
    )


def _load_active_user_for_update(db: Session, user_id: UUID) -> User:
    user = db.scalar(
        select(User).where(User.id == user_id).with_for_update(read=True, key_share=True)
    )
    if user is None or user.auth_disabled_at is not None:
        raise PublicAuthError("AUTH_ACCOUNT_UNAVAILABLE")
    return user


AUTH_INSTALLATION_LOCK_SEED = 214006


def lock_installation_authority_in_transaction(
    db: Session,
    client_uuid: str,
) -> None:
    """Serialize the current AuthSession generation for one app installation."""

    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "hashtextextended(:client_uuid, :seed)"
            ")"
        ),
        {"client_uuid": client_uuid, "seed": AUTH_INSTALLATION_LOCK_SEED},
    )


def create_public_session_in_transaction(
    db: Session,
    *,
    user_id: UUID,
    device_id: str,
    client_platform: str | None = None,
    device_name: str | None = None,
) -> PublicSessionTokens:
    _load_active_user_for_update(db, user_id)
    lock_installation_authority_in_transaction(db, device_id)
    now = datetime.now(UTC)
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.device_id == device_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(
            revoked_at=now,
            revoke_reason="INSTALLATION_SUPERSEDED",
        )
    )
    refresh_token = _new_refresh_token()
    row = AuthSession(
        user_id=user_id,
        device_id=device_id,
        refresh_digest=refresh_token_digest(refresh_token),
        rotation_revision=0,
        client_platform=client_platform,
        device_name=device_name,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=settings.refresh_token_days),
    )
    db.add(row)
    db.flush()
    return _session_tokens(row, refresh_token)


def create_public_session(
    db: Session,
    *,
    user_id: UUID,
    device_id: str,
    client_platform: str | None = None,
    device_name: str | None = None,
) -> PublicSessionTokens:
    pair = create_public_session_in_transaction(
        db,
        user_id=user_id,
        device_id=device_id,
        client_platform=client_platform,
        device_name=device_name,
    )
    db.commit()
    emit_operational_event(
        event="auth.session.created",
        correlation_id=str(pair.session_id),
        operation="PUBLIC_AUTH_SESSION",
        operation_status="CREATED",
    )
    return pair


def authenticate_access_session(
    db: Session,
    claims: AccessTokenClaims,
) -> UUID:
    now = datetime.now(UTC)
    row = db.scalar(
        select(AuthSession).where(
            AuthSession.id == claims.session_id,
            AuthSession.user_id == claims.user_id,
        )
    )
    if (
        row is None
        or row.revoked_at is not None
        or _as_utc(row.expires_at) <= now
    ):
        raise PublicAuthError("AUTH_SESSION_INVALID")

    user = db.get(User, claims.user_id)
    if user is None:
        # Keep deleted-account behavior deterministic across SQLite tests and
        # PostgreSQL FK-cascade timing: a token whose owner no longer exists is
        # simply no longer backed by a valid durable session.
        raise PublicAuthError("AUTH_SESSION_INVALID")
    if user.auth_disabled_at is not None:
        raise PublicAuthError("AUTH_ACCOUNT_UNAVAILABLE")
    return claims.user_id


def _record_refresh_replay(db: Session, session: AuthSession) -> None:
    record_security_signal(
        db.get_bind(),
        signal_code=SecuritySignalCode.AUTH_REFRESH_REPLAY,
        correlation_kind="auth-session",
        correlation_value=str(session.id),
        scope=SecurityScope.AUTH_REFRESH_SESSION,
    )
    emit_operational_event(
        event="auth.refresh.replay_detected",
        level="WARNING",
        correlation_id=str(session.id),
        operation="PUBLIC_AUTH_REFRESH",
        operation_status="REPLAY_DETECTED",
    )


def _record_refresh_terminal(code: str, session_id: UUID | None = None) -> None:
    emit_operational_event(
        event="auth.refresh.terminal",
        level="WARNING",
        correlation_id=str(session_id) if session_id is not None else None,
        operation="PUBLIC_AUTH_REFRESH",
        operation_status=code,
        error_code=code,
    )


def refresh_public_session(
    db: Session,
    *,
    refresh_token: str,
) -> PublicSessionTokens:
    digest = refresh_token_digest(refresh_token)
    if not digest:
        _record_refresh_terminal("INVALID_REFRESH_TOKEN")
        raise PublicAuthError("INVALID_REFRESH_TOKEN")

    # Resolve a stable abuse-protection scope *before* the rotation transaction.
    # auth_rate_limit owns its own commit, so it must never run while holding the
    # AuthSession row lock used for exactly-one-success refresh rotation.
    scope_row = db.execute(
        select(AuthSession.user_id, AuthSession.id).where(
            AuthSession.refresh_digest == digest
        )
    ).first()
    if scope_row is not None:
        session_scope = f"{scope_row.user_id}:{scope_row.id}"
    else:
        receipt_scope = db.get(AuthRefreshTokenReceipt, digest)
        if receipt_scope is None:
            consume_refresh_attempt(db, f"unknown:{digest}")
            _record_refresh_terminal("INVALID_REFRESH_TOKEN")
            raise PublicAuthError("INVALID_REFRESH_TOKEN")
        replay_scope = db.execute(
            select(AuthSession.user_id, AuthSession.id).where(
                AuthSession.id == receipt_scope.session_id
            )
        ).first()
        session_scope = (
            f"{replay_scope.user_id}:{replay_scope.id}"
            if replay_scope is not None
            else f"deleted-session:{receipt_scope.session_id}"
        )

    consume_refresh_attempt(db, session_scope)
    now = datetime.now(UTC)

    # From here through commit, rotation state is serialized by the session row.
    row = db.scalar(
        select(AuthSession)
        .where(AuthSession.refresh_digest == digest)
        .with_for_update()
    )
    if row is None:
        receipt = db.get(AuthRefreshTokenReceipt, digest)
        if receipt is None:
            # The credential ceased to be current after the preflight lookup but no
            # consumed receipt exists. Fail closed without minting a successor.
            _record_refresh_terminal("INVALID_REFRESH_TOKEN")
            raise PublicAuthError("INVALID_REFRESH_TOKEN")

        replay_session = db.scalar(
            select(AuthSession)
            .where(AuthSession.id == receipt.session_id)
            .with_for_update()
        )
        if replay_session is not None:
            if replay_session.revoked_at is None:
                replay_session.revoked_at = now
                replay_session.revoke_reason = "REFRESH_REPLAY"
                db.commit()
            else:
                db.rollback()
            _record_refresh_replay(db, replay_session)
        raise PublicAuthError("REFRESH_TOKEN_REUSED")

    if row.revoked_at is not None:
        db.rollback()
        _record_refresh_terminal("AUTH_SESSION_REVOKED", row.id)
        raise PublicAuthError("AUTH_SESSION_REVOKED")
    if _as_utc(row.expires_at) <= now:
        row.revoked_at = now
        row.revoke_reason = "EXPIRED"
        db.commit()
        _record_refresh_terminal("REFRESH_TOKEN_EXPIRED", row.id)
        raise PublicAuthError("REFRESH_TOKEN_EXPIRED")

    try:
        _load_active_user_for_update(db, row.user_id)
    except PublicAuthError:
        row.revoked_at = now
        row.revoke_reason = "ACCOUNT_UNAVAILABLE"
        db.commit()
        _record_refresh_terminal("AUTH_ACCOUNT_UNAVAILABLE", row.id)
        raise

    old_revision = row.rotation_revision
    db.add(
        AuthRefreshTokenReceipt(
            digest=digest,
            session_id=row.id,
            rotation_revision=old_revision,
            consumed_at=now,
            expires_at=row.expires_at,
        )
    )
    successor = _new_refresh_token()
    row.refresh_digest = refresh_token_digest(successor)
    row.rotation_revision = old_revision + 1
    row.last_used_at = now
    db.commit()
    db.refresh(row)
    emit_operational_event(
        event="auth.refresh.success",
        correlation_id=str(row.id),
        operation="PUBLIC_AUTH_REFRESH",
        operation_status="ROTATED",
    )
    return _session_tokens(row, successor)

def revoke_session_in_transaction(
    db: Session,
    *,
    user_id: UUID,
    session_id: UUID,
    reason: str,
) -> tuple[bool, bool]:
    row = db.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
        )
        .with_for_update()
    )
    if row is None:
        return False, False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        row.revoke_reason = reason[:64]
        return True, True
    return True, False


def revoke_session(
    db: Session,
    *,
    user_id: UUID,
    session_id: UUID,
    reason: str,
) -> bool:
    found, changed = revoke_session_in_transaction(
        db,
        user_id=user_id,
        session_id=session_id,
        reason=reason,
    )
    if not found:
        return False
    if changed:
        db.commit()
        emit_operational_event(
            event="auth.session.revoked",
            correlation_id=str(session_id),
            operation="PUBLIC_AUTH_SESSION",
            operation_status=reason[:64],
        )
    else:
        db.rollback()
    return True


def revoke_all_sessions_in_transaction(
    db: Session,
    *,
    user_id: UUID,
    reason: str,
    except_session_id: UUID | None = None,
) -> int:
    now = datetime.now(UTC)
    predicates = [
        AuthSession.user_id == user_id,
        AuthSession.revoked_at.is_(None),
    ]
    if except_session_id is not None:
        predicates.append(AuthSession.id != except_session_id)
    result = db.execute(
        update(AuthSession)
        .where(*predicates)
        .values(revoked_at=now, revoke_reason=reason[:64])
    )
    return int(result.rowcount or 0)


def revoke_all_sessions(
    db: Session,
    *,
    user_id: UUID,
    reason: str,
) -> int:
    count = revoke_all_sessions_in_transaction(
        db,
        user_id=user_id,
        reason=reason,
    )
    db.commit()
    emit_operational_event(
        event="auth.session.logout_all",
        correlation_id=str(user_id),
        operation="PUBLIC_AUTH_SESSION",
        operation_status=reason[:64],
        completed=True,
    )
    return count


def list_active_sessions(db: Session, *, user_id: UUID) -> list[AuthSession]:
    now = datetime.now(UTC)
    return list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .order_by(AuthSession.last_used_at.desc(), AuthSession.id.desc())
            .limit(100)
        )
    )
