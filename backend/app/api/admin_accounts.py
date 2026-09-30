from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin_deps import AdminPrincipal, require_admin_mutation, require_admin_roles
from app.admin_models import AdminAccount, AdminRole
from app.admin_schemas import (
    AdminAccountCreate,
    AdminAccountRead,
    AdminAccountUpdate,
    AdminMessage,
    AdminPasswordResetRequest,
)
from app.core.db import get_db
from app.services.admin_operations import (
    create_admin_account,
    list_admin_accounts,
    reset_admin_password,
    revoke_admin_sessions,
    update_admin_account,
)
from app.services.admin_security import AdminOperationError

router = APIRouter(prefix="/admins", tags=["admin-accounts"])
DbSession = Annotated[Session, Depends(get_db)]
SuperAdminRead = Annotated[
    AdminPrincipal,
    Depends(require_admin_roles(AdminRole.SUPER_ADMIN)),
]
SuperAdminMutation = Annotated[
    AdminPrincipal,
    Depends(require_admin_mutation(AdminRole.SUPER_ADMIN)),
]


def _raise(exc: AdminOperationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _read(row: AdminAccount) -> AdminAccountRead:
    return AdminAccountRead(
        id=row.id,
        email=row.email,
        display_name=row.display_name,
        role=AdminRole(row.role),
        disabled=row.disabled,
        revision=row.revision,
        last_login_at=row.last_login_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[AdminAccountRead])
def list_accounts(
    db: DbSession,
    _: SuperAdminRead,
) -> list[AdminAccountRead]:
    return [_read(row) for row in list_admin_accounts(db)]


@router.post("", response_model=AdminAccountRead, status_code=201)
def create_account(
    payload: AdminAccountCreate,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminAccountRead:
    try:
        row = create_admin_account(
            db,
            actor=principal.account,
            payload=payload,
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
    return _read(row)


@router.patch("/{admin_id}", response_model=AdminAccountRead)
def update_account(
    admin_id: UUID,
    payload: AdminAccountUpdate,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminAccountRead:
    try:
        row = update_admin_account(
            db,
            actor=principal.account,
            target_id=admin_id,
            payload=payload,
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
    return _read(row)


@router.post("/{admin_id}/password-reset", response_model=AdminAccountRead)
def password_reset(
    admin_id: UUID,
    payload: AdminPasswordResetRequest,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminAccountRead:
    try:
        row = reset_admin_password(
            db,
            actor=principal.account,
            target_id=admin_id,
            payload=payload,
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
    return _read(row)


@router.post("/{admin_id}/revoke-sessions", response_model=AdminMessage)
def revoke_sessions(
    admin_id: UUID,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminMessage:
    try:
        count = revoke_admin_sessions(
            db,
            actor=principal.account,
            target_id=admin_id,
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
    return AdminMessage(message=f"已撤销 {count} 个有效会话")
