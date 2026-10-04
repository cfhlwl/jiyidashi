from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_models import AdminAccount, AdminAuditEvent, AdminRole, AdminSession
from app.core.config import Settings, get_settings
from app.core.observability import current_request_id
from app.services.concurrency_guard import (
    ConcurrencyRejected,
    claim_argon2_permit,
    release_permit,
)

_password_hasher = PasswordHasher()
_DUMMY_ARGON2_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$CEhs1030PAoj5q0ODmRs5w$"
    "7hkHfPhql7bS5jt+yw3cdNJOFvIab4cwY1pem1n9hmw"
)


class AdminOperationError(RuntimeError):
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


def normalize_admin_email(value: str) -> str:
    return value.strip().casefold()


def hash_admin_password(password: str) -> str:
    return _password_hasher.hash(password)


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verify_password(db: Session, stored_hash: str | None, password: str) -> bool:
    candidate = stored_hash or _DUMMY_ARGON2_HASH
    try:
        permit = claim_argon2_permit(db.get_bind())
    except ConcurrencyRejected as exc:
        raise AdminOperationError(
            exc.code,
            429,
            retry_after=exc.retry_after,
        ) from exc
    try:
        try:
            return bool(_password_hasher.verify(candidate, password))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    finally:
        release_permit(db.get_bind(), permit=permit)


def _safe_audit_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, str):
        return value[:200]
    if isinstance(value, (list, tuple)) and depth < 2:
        return [
            _safe_audit_value(item, depth=depth + 1)
            for item in list(value)[:20]
            if isinstance(item, (str, int, bool, dict, list, tuple)) or item is None
        ]
    if isinstance(value, dict) and depth < 2:
        return {
            str(key)[:64]: _safe_audit_value(item, depth=depth + 1)
            for key, item in list(value.items())[:24]
            if isinstance(item, (str, int, bool, dict, list, tuple)) or item is None
        }
    return None


def _safe_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}

    allowed: dict[str, Any] = {}
    for key, value in list(metadata.items())[:12]:
        safe = _safe_audit_value(value)
        if safe is not None:
            allowed[str(key)[:64]] = safe
    return allowed


def append_admin_audit(
    db: Session,
    *,
    actor: AdminAccount,
    action: str,
    target_type: str,
    target_id: str | UUID | None,
    result: str,
    metadata: dict[str, Any] | None = None,
) -> AdminAuditEvent:
    event = AdminAuditEvent(
        admin_actor_id=actor.id,
        admin_role_snapshot=actor.role,
        action=action[:96],
        target_type=target_type[:64],
        target_id=None if target_id is None else str(target_id)[:255],
        result=result[:32],
        request_ref=current_request_id(),
        metadata_json=_safe_audit_metadata(metadata),
    )
    db.add(event)
    return event


def authenticate_admin(
    db: Session,
    *,
    email: str,
    password: str,
) -> AdminAccount:
    normalized = normalize_admin_email(email)
    account = db.scalar(
        select(AdminAccount).where(AdminAccount.email == normalized)
    )
    stored_hash = account.password_hash if account is not None else None
    verified = _verify_password(db, stored_hash, password)

    # Keep account existence, disabled state and password failure in one public response.
    if account is None or not verified or account.disabled:
        raise AdminOperationError("ADMIN_INVALID_CREDENTIALS", 401)

    if _password_hasher.check_needs_rehash(account.password_hash):
        try:
            permit = claim_argon2_permit(db.get_bind())
        except ConcurrencyRejected as exc:
            raise AdminOperationError(
                exc.code,
                429,
                retry_after=exc.retry_after,
            ) from exc
        try:
            account.password_hash = _password_hasher.hash(password)
        finally:
            release_permit(db.get_bind(), permit=permit)
        account.revision += 1

    return account


def rotate_presented_admin_session(
    db: Session,
    *,
    raw_session_token: str | None,
) -> None:
    if not raw_session_token:
        return
    digest = _token_digest(raw_session_token)
    session = db.scalar(
        select(AdminSession)
        .where(AdminSession.token_digest == digest)
        .with_for_update()
    )
    if session is None or session.revoked_at is not None:
        return
    account = db.get(AdminAccount, session.admin_id)
    session.revoked_at = datetime.now(UTC)
    if account is not None:
        append_admin_audit(
            db,
            actor=account,
            action="ADMIN_SESSION_ROTATE",
            target_type="ADMIN_SESSION",
            target_id=session.id,
            result="SUCCESS",
        )


def open_admin_session(
    db: Session,
    *,
    account: AdminAccount,
    settings: Settings | None = None,
) -> tuple[str, str, AdminSession]:
    cfg = settings or get_settings()
    now = datetime.now(UTC)
    raw_session = secrets.token_urlsafe(48)
    raw_csrf = secrets.token_urlsafe(32)
    row = AdminSession(
        admin_id=account.id,
        token_digest=_token_digest(raw_session),
        csrf_digest=_token_digest(raw_csrf),
        admin_revision_snapshot=account.revision,
        created_at=now,
        expires_at=now + timedelta(minutes=cfg.admin_session_minutes),
        last_seen_at=now,
    )
    account.last_login_at = now
    db.add(row)
    append_admin_audit(
        db,
        actor=account,
        action="ADMIN_LOGIN",
        target_type="ADMIN_SESSION",
        target_id=row.id,
        result="SUCCESS",
    )
    db.commit()
    db.refresh(row)
    return raw_session, raw_csrf, row


def revoke_admin_session(
    db: Session,
    *,
    actor: AdminAccount,
    session: AdminSession,
) -> None:
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
    append_admin_audit(
        db,
        actor=actor,
        action="ADMIN_LOGOUT",
        target_type="ADMIN_SESSION",
        target_id=session.id,
        result="SUCCESS",
    )
    db.commit()


def revoke_all_admin_sessions(
    db: Session,
    *,
    actor: AdminAccount,
    target_admin_id: UUID,
    action: str = "ADMIN_SESSIONS_REVOKE",
) -> int:
    now = datetime.now(UTC)
    rows = list(
        db.scalars(
            select(AdminSession)
            .where(
                AdminSession.admin_id == target_admin_id,
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > now,
            )
            .with_for_update()
        )
    )
    for row in rows:
        row.revoked_at = now
    append_admin_audit(
        db,
        actor=actor,
        action=action,
        target_type="ADMIN_ACCOUNT",
        target_id=target_admin_id,
        result="SUCCESS",
        metadata={"revoked_sessions": len(rows)},
    )
    db.commit()
    return len(rows)


def token_digest(value: str) -> str:
    return _token_digest(value)


def csrf_digest(value: str) -> str:
    return _token_digest(value)


def require_confirmation(actual: str, expected: str) -> None:
    actual_bytes = actual.strip().encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if not secrets.compare_digest(actual_bytes, expected_bytes):
        raise AdminOperationError("ADMIN_CONFIRMATION_REQUIRED", 400)


def ensure_role(value: str) -> AdminRole:
    try:
        return AdminRole(value)
    except ValueError as exc:
        raise AdminOperationError("ADMIN_SESSION_INVALID", 401) from exc
