from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.admin_deps import (
    AdminPrincipal,
    AdminPrincipalDep,
    require_admin_mutation,
)
from app.admin_models import AdminRole
from app.admin_schemas import AdminLoginRequest, AdminMessage, AdminSessionRead
from app.core.config import get_settings
from app.core.db import get_db
from app.services.admin_security import (
    AdminOperationError,
    authenticate_admin,
    normalize_admin_email,
    open_admin_session,
    revoke_admin_session,
    rotate_presented_admin_session,
)
from app.services.auth_rate_limit import (
    clear_admin_login_account_penalty,
    consume_admin_login_account_attempt,
    consume_admin_login_ip_attempt,
    record_admin_login_failure,
)

router = APIRouter(prefix="/auth", tags=["admin-auth"])
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db)]
AnyAdminMutation = Annotated[
    AdminPrincipal,
    Depends(
        require_admin_mutation(
            AdminRole.SUPER_ADMIN,
            AdminRole.OPERATOR,
            AdminRole.SUPPORT_READONLY,
        )
    ),
]




def _client_ip(request: Request) -> str:
    # Use only ASGI's parsed peer address. Do not trust client-supplied forwarding
    # headers at this privileged boundary.
    return request.client.host if request.client is not None else "unknown"

def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _set_session_cookies(
    response: Response,
    *,
    session_token: str,
    csrf_token: str,
) -> None:
    max_age = settings.admin_session_minutes * 60
    response.set_cookie(
        key=settings.admin_session_cookie_name,
        value=session_token,
        max_age=max_age,
        secure=settings.is_production,
        httponly=True,
        samesite="strict",
        path="/admin",
    )
    # Double-submit value is intentionally readable by same-origin Admin JS;
    # the server stores only its digest and requires the matching header.
    response.set_cookie(
        key=settings.admin_csrf_cookie_name,
        value=csrf_token,
        max_age=max_age,
        secure=settings.is_production,
        httponly=False,
        samesite="strict",
        path="/admin",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        settings.admin_session_cookie_name,
        path="/admin",
        secure=settings.is_production,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        settings.admin_csrf_cookie_name,
        path="/admin",
        secure=settings.is_production,
        httponly=False,
        samesite="strict",
    )


@router.post("/login", response_model=AdminSessionRead)
def login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> AdminSessionRead:
    client_ip = _client_ip(request)
    subject = normalize_admin_email(str(payload.email))

    # Privileged abuse gates run before Argon2 so an attacker cannot turn the
    # management login endpoint into an unbounded password-hashing oracle.
    consume_admin_login_ip_attempt(db, client_ip)
    consume_admin_login_account_attempt(db, client_ip, subject)

    try:
        account = authenticate_admin(
            db,
            email=subject,
            password=payload.password,
        )
    except AdminOperationError as exc:
        if exc.code == "ADMIN_INVALID_CREDENTIALS":
            record_admin_login_failure(db, client_ip, subject)
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    clear_admin_login_account_penalty(db, client_ip, subject)

    try:
        rotate_presented_admin_session(
            db,
            raw_session_token=request.cookies.get(settings.admin_session_cookie_name),
        )
        session_token, csrf_token, session = open_admin_session(
            db,
            account=account,
        )
    except AdminOperationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    _set_session_cookies(
        response,
        session_token=session_token,
        csrf_token=csrf_token,
    )
    _set_no_store(response)
    return AdminSessionRead(
        admin_id=account.id,
        email=account.email,
        display_name=account.display_name,
        role=AdminRole(account.role),
        expires_at=session.expires_at,
    )


@router.get("/session", response_model=AdminSessionRead)
def session(
    response: Response,
    principal: AdminPrincipalDep,
) -> AdminSessionRead:
    _set_no_store(response)
    return AdminSessionRead(
        admin_id=principal.account.id,
        email=principal.account.email,
        display_name=principal.account.display_name,
        role=AdminRole(principal.account.role),
        expires_at=principal.session.expires_at,
    )


@router.post("/logout", response_model=AdminMessage)
def logout(
    response: Response,
    db: DbSession,
    principal: AnyAdminMutation,
) -> AdminMessage:
    revoke_admin_session(
        db,
        actor=principal.account,
        session=principal.session,
    )
    _clear_session_cookies(response)
    _set_no_store(response)
    return AdminMessage(message="已安全退出")
