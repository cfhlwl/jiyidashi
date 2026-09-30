from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_models import AdminAccount, AdminRole, AdminSession, EntitlementQuotaPolicy
from app.admin_schemas import (
    AdminAccountCreate,
    AdminAccountUpdate,
    AdminEntitlementAdjustmentRequest,
    AdminPasswordResetRequest,
    AdminQuotaCatalogWrite,
)
from app.entitlement_models import UserEntitlement
from app.models import User
from app.services.admin_security import (
    AdminOperationError,
    append_admin_audit,
    hash_admin_password,
    normalize_admin_email,
    require_confirmation,
)
from app.services.runtime_policy_service import (
    COMMERCIAL_PLAN_CODES,
    RuntimeQuotaPolicyUnavailable,
    commercial_quota_catalog_initialized,
    read_runtime_quota_rows,
)

_COMMERCIAL_PLAN_VALUES = {item.value for item in COMMERCIAL_PLAN_CODES}


def _require_super_admin(actor: AdminAccount) -> None:
    if actor.role != AdminRole.SUPER_ADMIN.value or actor.disabled:
        raise AdminOperationError("ADMIN_PERMISSION_DENIED", 403)


def _revoke_target_sessions_in_transaction(
    db: Session,
    *,
    target_admin_id: UUID,
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
    return len(rows)


def _lock_active_super_admins(db: Session) -> list[AdminAccount]:
    return list(
        db.scalars(
            select(AdminAccount)
            .where(
                AdminAccount.role == AdminRole.SUPER_ADMIN.value,
                AdminAccount.disabled.is_(False),
            )
            .order_by(AdminAccount.id.asc())
            .with_for_update()
        )
    )


def list_admin_accounts(db: Session) -> list[AdminAccount]:
    return list(
        db.scalars(
            select(AdminAccount).order_by(
                AdminAccount.created_at.asc(),
                AdminAccount.id.asc(),
            )
        )
    )


def create_admin_account(
    db: Session,
    *,
    actor: AdminAccount,
    payload: AdminAccountCreate,
) -> AdminAccount:
    _require_super_admin(actor)
    if payload.role == AdminRole.SUPER_ADMIN:
        require_confirmation(payload.confirmation, "创建超级管理员")
    else:
        require_confirmation(payload.confirmation, "创建管理员")

    email = normalize_admin_email(str(payload.email))
    if db.scalar(select(AdminAccount.id).where(AdminAccount.email == email)) is not None:
        raise AdminOperationError("ADMIN_ACCOUNT_EXISTS", 409)

    row = AdminAccount(
        email=email,
        display_name=payload.display_name.strip(),
        password_hash=hash_admin_password(payload.password),
        role=payload.role.value,
        disabled=False,
        revision=0,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AdminOperationError("ADMIN_ACCOUNT_EXISTS", 409) from exc

    append_admin_audit(
        db,
        actor=actor,
        action="ADMIN_ACCOUNT_CREATE",
        target_type="ADMIN_ACCOUNT",
        target_id=row.id,
        result="SUCCESS",
        metadata={"role": row.role},
    )
    db.commit()
    db.refresh(row)
    return row


def update_admin_account(
    db: Session,
    *,
    actor: AdminAccount,
    target_id: UUID,
    payload: AdminAccountUpdate,
) -> AdminAccount:
    _require_super_admin(actor)
    target = db.scalar(
        select(AdminAccount)
        .where(AdminAccount.id == target_id)
        .with_for_update()
    )
    if target is None:
        raise AdminOperationError("ADMIN_ACCOUNT_NOT_FOUND", 404)
    if target.revision != payload.expected_revision:
        raise AdminOperationError("ADMIN_STATE_STALE", 409)

    changing_role = "role" in payload.model_fields_set
    changing_disabled = "disabled" in payload.model_fields_set
    if actor.id == target.id and (changing_role or changing_disabled):
        raise AdminOperationError("ADMIN_SELF_ROLE_CHANGE_DENIED", 409)

    next_role = payload.role.value if payload.role is not None else target.role
    next_disabled = payload.disabled if payload.disabled is not None else target.disabled

    if (
        target.role == AdminRole.SUPER_ADMIN.value
        and not target.disabled
        and (next_role != AdminRole.SUPER_ADMIN.value or next_disabled)
    ):
        active_supers = _lock_active_super_admins(db)
        if len(active_supers) <= 1:
            raise AdminOperationError("ADMIN_LAST_SUPER_ADMIN_REQUIRED", 409)

    if next_role == AdminRole.SUPER_ADMIN.value and target.role != next_role:
        require_confirmation(payload.confirmation, "授予超级管理员")
    else:
        require_confirmation(payload.confirmation, "确认管理员变更")

    before = {
        "display_name": target.display_name,
        "role": target.role,
        "disabled": target.disabled,
        "revision": target.revision,
    }
    if payload.display_name is not None:
        target.display_name = payload.display_name.strip()
    if payload.role is not None:
        target.role = payload.role.value
    if payload.disabled is not None:
        target.disabled = payload.disabled

    target.revision += 1
    target.updated_at = datetime.now(UTC)
    revoked = _revoke_target_sessions_in_transaction(db, target_admin_id=target.id)
    append_admin_audit(
        db,
        actor=actor,
        action="ADMIN_ACCOUNT_UPDATE",
        target_type="ADMIN_ACCOUNT",
        target_id=target.id,
        result="SUCCESS",
        metadata={
            "before": before,
            "after": {
                "display_name": target.display_name,
                "role": target.role,
                "disabled": target.disabled,
                "revision": target.revision,
            },
            "revoked_sessions": revoked,
        },
    )
    db.commit()
    db.refresh(target)
    return target


def reset_admin_password(
    db: Session,
    *,
    actor: AdminAccount,
    target_id: UUID,
    payload: AdminPasswordResetRequest,
) -> AdminAccount:
    _require_super_admin(actor)
    require_confirmation(payload.confirmation, "重置管理员密码")
    target = db.scalar(
        select(AdminAccount)
        .where(AdminAccount.id == target_id)
        .with_for_update()
    )
    if target is None:
        raise AdminOperationError("ADMIN_ACCOUNT_NOT_FOUND", 404)
    if target.revision != payload.expected_revision:
        raise AdminOperationError("ADMIN_STATE_STALE", 409)

    target.password_hash = hash_admin_password(payload.new_password)
    target.revision += 1
    target.updated_at = datetime.now(UTC)
    revoked = _revoke_target_sessions_in_transaction(db, target_admin_id=target.id)
    append_admin_audit(
        db,
        actor=actor,
        action="ADMIN_PASSWORD_RESET",
        target_type="ADMIN_ACCOUNT",
        target_id=target.id,
        result="SUCCESS",
        metadata={"revision": target.revision, "revoked_sessions": revoked},
    )
    db.commit()
    db.refresh(target)
    return target


def revoke_admin_sessions(
    db: Session,
    *,
    actor: AdminAccount,
    target_id: UUID,
) -> int:
    _require_super_admin(actor)
    target = db.scalar(
        select(AdminAccount)
        .where(AdminAccount.id == target_id)
        .with_for_update()
    )
    if target is None:
        raise AdminOperationError("ADMIN_ACCOUNT_NOT_FOUND", 404)
    revoked = _revoke_target_sessions_in_transaction(db, target_admin_id=target.id)
    append_admin_audit(
        db,
        actor=actor,
        action="ADMIN_SESSIONS_REVOKE",
        target_type="ADMIN_ACCOUNT",
        target_id=target.id,
        result="SUCCESS",
        metadata={"revoked_sessions": revoked},
    )
    db.commit()
    return revoked


def _quota_row_snapshot(row: EntitlementQuotaPolicy) -> dict[str, int | str]:
    return {
        "plan": row.plan_code,
        "revision": row.revision,
        "storage_bytes": row.storage_bytes,
        "ai_provider_requests": row.ai_provider_requests,
        "ai_input_tokens": row.ai_input_tokens,
        "ai_output_tokens": row.ai_output_tokens,
    }


def read_quota_catalog(db: Session) -> tuple[bool, list[EntitlementQuotaPolicy]]:
    rows = read_runtime_quota_rows(db)
    if not rows:
        return False, []
    if len(rows) != len(COMMERCIAL_PLAN_CODES):
        raise AdminOperationError("ADMIN_QUOTA_POLICY_UNAVAILABLE", 503)
    if {row.plan_code for row in rows} != _COMMERCIAL_PLAN_VALUES:
        raise AdminOperationError("ADMIN_QUOTA_POLICY_UNAVAILABLE", 503)
    return True, rows


def write_quota_catalog(
    db: Session,
    *,
    actor: AdminAccount,
    payload: AdminQuotaCatalogWrite,
) -> list[EntitlementQuotaPolicy]:
    _require_super_admin(actor)
    require_confirmation(payload.confirmation, "保存额度配置")

    rows = read_runtime_quota_rows(db, for_update=True)
    if len(rows) not in {0, len(COMMERCIAL_PLAN_CODES)}:
        raise AdminOperationError("ADMIN_QUOTA_POLICY_UNAVAILABLE", 503)

    existing = {row.plan_code: row for row in rows}
    requested = {row.plan_code: row for row in payload.plans}
    if set(requested) != _COMMERCIAL_PLAN_VALUES:
        raise AdminOperationError("ADMIN_QUOTA_POLICY_INVALID", 400)

    before = [_quota_row_snapshot(row) for row in rows]
    now = datetime.now(UTC)
    result: list[EntitlementQuotaPolicy] = []

    if not rows:
        if any(item.expected_revision is not None for item in payload.plans):
            raise AdminOperationError("ADMIN_STATE_STALE", 409)
        for plan in sorted(_COMMERCIAL_PLAN_VALUES):
            item = requested[plan]
            row = EntitlementQuotaPolicy(
                plan_code=plan,
                revision=0,
                storage_bytes=item.storage_bytes,
                ai_provider_requests=item.ai_provider_requests,
                ai_input_tokens=item.ai_input_tokens,
                ai_output_tokens=item.ai_output_tokens,
                updated_by_admin_id=actor.id,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            result.append(row)
    else:
        for plan in sorted(_COMMERCIAL_PLAN_VALUES):
            row = existing[plan]
            item = requested[plan]
            if item.expected_revision is None or row.revision != item.expected_revision:
                raise AdminOperationError("ADMIN_STATE_STALE", 409)
            row.storage_bytes = item.storage_bytes
            row.ai_provider_requests = item.ai_provider_requests
            row.ai_input_tokens = item.ai_input_tokens
            row.ai_output_tokens = item.ai_output_tokens
            row.revision += 1
            row.updated_by_admin_id = actor.id
            row.updated_at = now
            result.append(row)

    db.flush()
    append_admin_audit(
        db,
        actor=actor,
        action="ENTITLEMENT_QUOTA_CATALOG_UPDATE",
        target_type="RUNTIME_POLICY",
        target_id="entitlement-quota",
        result="SUCCESS",
        metadata={
            "before": before,
            "after": [_quota_row_snapshot(row) for row in result],
        },
    )
    db.commit()
    return read_runtime_quota_rows(db)


def adjust_user_entitlement(
    db: Session,
    *,
    actor: AdminAccount,
    user_id: UUID,
    payload: AdminEntitlementAdjustmentRequest,
) -> UserEntitlement:
    _require_super_admin(actor)
    require_confirmation(payload.confirmation, "调整会员方案")
    if payload.plan_code not in _COMMERCIAL_PLAN_VALUES:
        raise AdminOperationError("ADMIN_PLAN_NOT_ASSIGNABLE", 400)

    try:
        if not commercial_quota_catalog_initialized(db):
            raise AdminOperationError("ADMIN_QUOTA_POLICY_NOT_INITIALIZED", 409)
    except RuntimeQuotaPolicyUnavailable as exc:
        raise AdminOperationError("ADMIN_QUOTA_POLICY_UNAVAILABLE", 503) from exc

    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise AdminOperationError("ADMIN_USER_NOT_FOUND", 404)

    entitlement = db.scalar(
        select(UserEntitlement)
        .where(UserEntitlement.user_id == user_id)
        .with_for_update()
    )
    if entitlement is None:
        raise AdminOperationError("ADMIN_ENTITLEMENT_UNAVAILABLE", 503)
    if entitlement.revision != payload.expected_revision:
        raise AdminOperationError("ADMIN_STATE_STALE", 409)

    now = datetime.now(UTC)
    expires_at = payload.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise AdminOperationError("ADMIN_EXPIRY_INVALID", 400)
        expires_at = expires_at.astimezone(UTC)
        if expires_at <= now:
            raise AdminOperationError("ADMIN_EXPIRY_INVALID", 400)

    before = {
        "plan": entitlement.plan_code,
        "revision": entitlement.revision,
        "expires_at": None
        if entitlement.expires_at is None
        else entitlement.expires_at.isoformat(),
    }
    entitlement.plan_code = payload.plan_code
    entitlement.revision += 1
    entitlement.effective_at = now
    entitlement.expires_at = expires_at
    entitlement.updated_at = now

    append_admin_audit(
        db,
        actor=actor,
        action="USER_ENTITLEMENT_ADJUST",
        target_type="USER",
        target_id=user_id,
        result="SUCCESS",
        metadata={
            "before": before,
            "after": {
                "plan": entitlement.plan_code,
                "revision": entitlement.revision,
                "expires_at": None
                if entitlement.expires_at is None
                else entitlement.expires_at.isoformat(),
            },
        },
    )
    db.commit()
    db.refresh(entitlement)
    return entitlement
