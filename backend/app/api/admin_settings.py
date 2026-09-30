from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.admin_deps import AdminPrincipal, require_admin_mutation, require_admin_roles
from app.admin_models import AdminRole, EntitlementQuotaPolicy
from app.admin_schemas import (
    AdminEntitlementAdjustmentRequest,
    AdminMessage,
    AdminQuotaCatalogRead,
    AdminQuotaCatalogWrite,
    AdminQuotaPlanRead,
)
from app.core.db import get_db
from app.services.admin_operations import (
    adjust_user_entitlement,
    read_quota_catalog,
    write_quota_catalog,
)
from app.services.admin_security import AdminOperationError

router = APIRouter(tags=["admin-settings"])
DbSession = Annotated[Session, Depends(get_db)]
AnyAdminRead = Annotated[
    AdminPrincipal,
    Depends(
        require_admin_roles(
            AdminRole.SUPER_ADMIN,
            AdminRole.OPERATOR,
            AdminRole.SUPPORT_READONLY,
        )
    ),
]
SuperAdminMutation = Annotated[
    AdminPrincipal,
    Depends(require_admin_mutation(AdminRole.SUPER_ADMIN)),
]


def _raise(exc: AdminOperationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _quota_read(row: EntitlementQuotaPolicy) -> AdminQuotaPlanRead:
    return AdminQuotaPlanRead(
        plan_code=row.plan_code,
        revision=row.revision,
        storage_bytes=row.storage_bytes,
        ai_provider_requests=row.ai_provider_requests,
        ai_input_tokens=row.ai_input_tokens,
        ai_output_tokens=row.ai_output_tokens,
        updated_at=row.updated_at,
    )


@router.get("/settings/quota-catalog", response_model=AdminQuotaCatalogRead)
def quota_catalog(
    db: DbSession,
    _: AnyAdminRead,
) -> AdminQuotaCatalogRead:
    try:
        initialized, rows = read_quota_catalog(db)
    except AdminOperationError as exc:
        _raise(exc)
    return AdminQuotaCatalogRead(
        initialized=initialized,
        plans=[_quota_read(row) for row in rows],
    )


@router.put("/settings/quota-catalog", response_model=AdminQuotaCatalogRead)
def update_quota_catalog(
    payload: AdminQuotaCatalogWrite,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminQuotaCatalogRead:
    try:
        rows = write_quota_catalog(
            db,
            actor=principal.account,
            payload=payload,
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
    return AdminQuotaCatalogRead(
        initialized=True,
        plans=[_quota_read(row) for row in rows],
    )


@router.put("/users/{user_id}/entitlement", response_model=AdminMessage)
def update_user_entitlement(
    user_id: UUID,
    payload: AdminEntitlementAdjustmentRequest,
    db: DbSession,
    principal: SuperAdminMutation,
) -> AdminMessage:
    try:
        entitlement = adjust_user_entitlement(
            db,
            actor=principal.account,
            user_id=user_id,
            payload=payload,
        )
    except AdminOperationError as exc:
        db.rollback()
        _raise(exc)
    return AdminMessage(
        message=f"会员方案已更新，当前版本 {entitlement.revision}"
    )
