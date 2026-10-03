from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.admin_deps import AdminPrincipal, require_admin_mutation, require_admin_roles
from app.admin_models import AdminRole
from app.admin_schemas import (
    AdminAccountDeletionPage,
    AdminAuditPage,
    AdminDashboardRead,
    AdminDataDeletionPage,
    AdminFamilyDetail,
    AdminFamilyPage,
    AdminMessage,
    AdminSecurityAlertPage,
    AdminSystemHealthRead,
    AdminSystemSettingsRead,
    AdminUserDetail,
    AdminUserPage,
)
from app.core.db import engine, get_db
from app.security_models import SecurityAlert, SecurityAlertDeliveryStatus
from app.services.admin_projection_service import (
    dashboard_projection,
    family_detail,
    list_account_deletions,
    list_admin_audit,
    list_data_deletions,
    list_families,
    list_security_alerts,
    list_users,
    system_health_projection,
    system_settings_projection,
    user_detail,
)
from app.services.admin_security import (
    AdminOperationError,
    append_admin_audit,
)
from app.services.security_alerting import deliver_security_alert

router = APIRouter(tags=["admin-operations"])
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
OperatorMutation = Annotated[
    AdminPrincipal,
    Depends(
        require_admin_mutation(
            AdminRole.SUPER_ADMIN,
            AdminRole.OPERATOR,
        )
    ),
]


def _raise(exc: AdminOperationError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("/dashboard", response_model=AdminDashboardRead)
def dashboard(
    db: DbSession,
    _: AnyAdminRead,
) -> AdminDashboardRead:
    return dashboard_projection(db)


@router.get("/users", response_model=AdminUserPage)
def users(
    db: DbSession,
    _: AnyAdminRead,
    search: str | None = Query(default=None, max_length=100),
    plan: str | None = Query(default=None, max_length=32),
    registered_from: date | None = Query(default=None),
    registered_to: date | None = Query(default=None),
    operational_state: str | None = Query(default=None, max_length=32),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
) -> AdminUserPage:
    try:
        return list_users(
            db,
            search=search,
            plan=plan,
            registered_from=registered_from,
            registered_to=registered_to,
            operational_state=operational_state,
            cursor=cursor,
            limit=limit,
        )
    except AdminOperationError as exc:
        _raise(exc)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def user(
    user_id: UUID,
    db: DbSession,
    _: AnyAdminRead,
) -> AdminUserDetail:
    try:
        return user_detail(db, user_id=user_id)
    except AdminOperationError as exc:
        _raise(exc)


@router.get("/families", response_model=AdminFamilyPage)
def families(
    db: DbSession,
    _: AnyAdminRead,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
) -> AdminFamilyPage:
    try:
        return list_families(db, cursor=cursor, limit=limit)
    except AdminOperationError as exc:
        _raise(exc)


@router.get("/families/{family_id}", response_model=AdminFamilyDetail)
def family(
    family_id: UUID,
    db: DbSession,
    _: AnyAdminRead,
) -> AdminFamilyDetail:
    try:
        return family_detail(db, family_id=family_id)
    except AdminOperationError as exc:
        _raise(exc)


@router.get("/data-tasks/deletions", response_model=AdminDataDeletionPage)
def data_deletions(
    db: DbSession,
    _: AnyAdminRead,
    search: str | None = Query(default=None, max_length=100),
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
) -> AdminDataDeletionPage:
    try:
        return list_data_deletions(
            db,
            search=search,
            status_filter=status_filter,
            cursor=cursor,
            limit=limit,
        )
    except AdminOperationError as exc:
        _raise(exc)


@router.get(
    "/data-tasks/account-deletions",
    response_model=AdminAccountDeletionPage,
)
def account_deletions(
    db: DbSession,
    _: AnyAdminRead,
    search: str | None = Query(default=None, max_length=100),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
) -> AdminAccountDeletionPage:
    try:
        return list_account_deletions(
            db,
            search=search,
            cursor=cursor,
            limit=limit,
        )
    except AdminOperationError as exc:
        _raise(exc)


@router.get("/security/alerts", response_model=AdminSecurityAlertPage)
def security_alerts(
    db: DbSession,
    _: AnyAdminRead,
    severity: str | None = Query(default=None, max_length=16),
    category: str | None = Query(default=None, max_length=32),
    delivery_status: str | None = Query(default=None, max_length=32),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
) -> AdminSecurityAlertPage:
    try:
        return list_security_alerts(
            db,
            severity=severity,
            category=category,
            delivery_status=delivery_status,
            cursor=cursor,
            limit=limit,
        )
    except AdminOperationError as exc:
        _raise(exc)


@router.post("/security/alerts/{alert_id}/retry", response_model=AdminMessage)
def retry_security_alert(
    alert_id: UUID,
    db: DbSession,
    principal: OperatorMutation,
) -> AdminMessage:
    alert = db.get(SecurityAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="ADMIN_SECURITY_ALERT_NOT_FOUND")
    if alert.delivery_status in {
        SecurityAlertDeliveryStatus.DELIVERED.value,
        SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value,
    }:
        raise HTTPException(status_code=409, detail="ADMIN_SECURITY_ALERT_NOT_RETRYABLE")

    # Use the existing canonical delivery function. Admin never edits delivery
    # counters/status directly.
    db.rollback()
    delivered = deliver_security_alert(engine, alert_id=str(alert_id))

    refreshed = db.get(SecurityAlert, alert_id)
    final_status = (
        "UNKNOWN" if refreshed is None else refreshed.delivery_status
    )
    append_admin_audit(
        db,
        actor=principal.account,
        action="SECURITY_ALERT_RETRY",
        target_type="SECURITY_ALERT",
        target_id=alert_id,
        result="SUCCESS" if delivered else "NOT_DELIVERED",
        metadata={"delivery_status": final_status},
    )
    db.commit()
    return AdminMessage(
        message="安全通知已重新发送"
        if delivered
        else "本次未完成发送，系统会按既有策略继续处理"
    )


@router.get("/audit", response_model=AdminAuditPage)
def audit(
    db: DbSession,
    _: AnyAdminRead,
    search: str | None = Query(default=None, max_length=100),
    action: str | None = Query(default=None, max_length=96),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
) -> AdminAuditPage:
    try:
        return list_admin_audit(
            db,
            search=search,
            action=action,
            cursor=cursor,
            limit=limit,
        )
    except AdminOperationError as exc:
        _raise(exc)


@router.get("/system/settings", response_model=AdminSystemSettingsRead)
def settings(
    db: DbSession,
    _: AnyAdminRead,
) -> AdminSystemSettingsRead:
    try:
        return system_settings_projection(db)
    except AdminOperationError as exc:
        _raise(exc)


@router.get("/system/health", response_model=AdminSystemHealthRead)
def system_health(
    db: DbSession,
    _: AnyAdminRead,
) -> AdminSystemHealthRead:
    return system_health_projection(db)
