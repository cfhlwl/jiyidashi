from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.family_models import (
    FamilyAccessAuditEvent,
    FamilyMembership,
    FamilyRole,
)

FAMILY_AUDIT_RETENTION_DAYS = 90
FAMILY_AUDIT_DEFAULT_WINDOW_DAYS = 30
FAMILY_AUDIT_MAX_LIMIT = 50


class FamilyAuditError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class FamilyAuditView:
    event_id: UUID
    actor_user_id: UUID
    resource_owner_user_id: UUID
    authority_type: str
    permission_code: str | None
    resource_type: str
    action: str
    result: str
    created_at: datetime


def list_family_access_audit(
    db: Session,
    *,
    actor_user_id: UUID,
    limit: int = FAMILY_AUDIT_MAX_LIMIT,
    now: datetime | None = None,
) -> list[FamilyAuditView]:
    if limit < 1 or limit > FAMILY_AUDIT_MAX_LIMIT:
        raise ValueError("family audit limit must be between 1 and 50")

    membership = db.execute(
        select(
            FamilyMembership.family_id,
            FamilyMembership.role,
        ).where(FamilyMembership.user_id == actor_user_id)
    ).one_or_none()
    if membership is None:
        raise FamilyAuditError("FAMILY_NOT_FOUND", 404)
    if membership.role != FamilyRole.OWNER.value:
        raise FamilyAuditError("OWNER_REQUIRED", 403)

    reference = now or datetime.now(UTC)
    lower_bound = reference - timedelta(days=FAMILY_AUDIT_DEFAULT_WINDOW_DAYS)
    rows = db.execute(
        select(
            FamilyAccessAuditEvent.id,
            FamilyAccessAuditEvent.actor_user_id,
            FamilyAccessAuditEvent.resource_owner_user_id,
            FamilyAccessAuditEvent.authority_type,
            FamilyAccessAuditEvent.permission_code,
            FamilyAccessAuditEvent.resource_type,
            FamilyAccessAuditEvent.action,
            FamilyAccessAuditEvent.result,
            FamilyAccessAuditEvent.created_at,
        )
        .where(
            FamilyAccessAuditEvent.family_id == membership.family_id,
            FamilyAccessAuditEvent.created_at >= lower_bound,
        )
        .order_by(
            FamilyAccessAuditEvent.created_at.desc(),
            FamilyAccessAuditEvent.id.desc(),
        )
        .limit(limit)
    ).all()
    return [
        FamilyAuditView(
            event_id=row.id,
            actor_user_id=row.actor_user_id,
            resource_owner_user_id=row.resource_owner_user_id,
            authority_type=row.authority_type,
            permission_code=row.permission_code,
            resource_type=row.resource_type,
            action=row.action,
            result=row.result,
            created_at=row.created_at,
        )
        for row in rows
    ]
