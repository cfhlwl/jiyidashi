from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_models import AdminAccount, AdminRole, AdminSession
from app.core.config import get_settings
from app.core.db import get_db
from app.services.admin_security import csrf_digest, token_digest

settings = get_settings()
DbSession = Annotated[Session, Depends(get_db)]


@dataclass(frozen=True)
class AdminPrincipal:
    account: AdminAccount
    session: AdminSession


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _deny(code: str = "ADMIN_AUTH_REQUIRED", status_code: int = 401) -> None:
    raise HTTPException(status_code=status_code, detail=code)


def _validate_rows(
    account: AdminAccount | None,
    session: AdminSession | None,
) -> AdminPrincipal:
    now = datetime.now(UTC)
    if account is None or session is None:
        _deny()
    assert account is not None and session is not None

    if (
        account.disabled
        or session.revoked_at is not None
        or _as_utc(session.expires_at) <= now
        or session.admin_revision_snapshot != account.revision
    ):
        _deny("ADMIN_SESSION_STALE", 401)
    try:
        AdminRole(account.role)
    except ValueError:
        _deny("ADMIN_SESSION_STALE", 401)
    return AdminPrincipal(account=account, session=session)


def get_admin_principal(request: Request, db: DbSession) -> AdminPrincipal:
    raw = request.cookies.get(settings.admin_session_cookie_name)
    if not raw:
        _deny()

    digest = token_digest(raw)
    session = db.scalar(
        select(AdminSession).where(AdminSession.token_digest == digest)
    )
    if session is None:
        _deny()

    account = db.get(AdminAccount, session.admin_id)
    return _validate_rows(account, session)


AdminPrincipalDep = Annotated[AdminPrincipal, Depends(get_admin_principal)]


def require_admin_roles(
    *roles: AdminRole,
) -> Callable[[AdminPrincipalDep], AdminPrincipal]:
    allowed = frozenset(roles)

    def dependency(principal: AdminPrincipalDep) -> AdminPrincipal:
        if AdminRole(principal.account.role) not in allowed:
            _deny("ADMIN_PERMISSION_DENIED", 403)
        return principal

    return dependency


def require_admin_mutation(
    *roles: AdminRole,
) -> Callable[..., AdminPrincipal]:
    allowed = frozenset(roles)

    def dependency(
        request: Request,
        principal: AdminPrincipalDep,
        db: DbSession,
        x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> AdminPrincipal:
        cookie_csrf = request.cookies.get(settings.admin_csrf_cookie_name)
        if not x_csrf_token or not cookie_csrf:
            _deny("ADMIN_CSRF_REQUIRED", 403)
        if not secrets.compare_digest(x_csrf_token, cookie_csrf):
            _deny("ADMIN_CSRF_INVALID", 403)
        if not secrets.compare_digest(
            csrf_digest(x_csrf_token),
            principal.session.csrf_digest,
        ):
            _deny("ADMIN_CSRF_INVALID", 403)

        # SEC-014 semantics for Admin: fresh session/role authority at mutation time.
        locked_session = db.scalar(
            select(AdminSession)
            .where(AdminSession.id == principal.session.id)
            .with_for_update()
        )
        if locked_session is None:
            _deny("ADMIN_SESSION_STALE", 401)
        locked_account = db.scalar(
            select(AdminAccount)
            .where(AdminAccount.id == principal.account.id)
            .with_for_update()
        )
        current = _validate_rows(locked_account, locked_session)
        if AdminRole(current.account.role) not in allowed:
            _deny("ADMIN_PERMISSION_DENIED", 403)
        return current

    return dependency
