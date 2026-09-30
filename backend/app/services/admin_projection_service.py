from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.admin_models import AdminAccount, AdminAuditEvent
from app.admin_schemas import (
    AdminAccountDeletionItem,
    AdminAccountDeletionPage,
    AdminAuditPage,
    AdminAuditRead,
    AdminDashboardOverview,
    AdminDashboardRead,
    AdminDashboardTrendPoint,
    AdminDataDeletionItem,
    AdminDataDeletionPage,
    AdminFamilyDetail,
    AdminFamilyGrantSummary,
    AdminFamilyListItem,
    AdminFamilyMemberRead,
    AdminFamilyPage,
    AdminSecurityAlertItem,
    AdminSecurityAlertPage,
    AdminServiceStatus,
    AdminSettingRead,
    AdminSettingSectionRead,
    AdminSystemHealthRead,
    AdminSystemSettingsRead,
    AdminUserDetail,
    AdminUserEntitlementRead,
    AdminUserListItem,
    AdminUserPage,
)
from app.analytics_models import ProductActiveDay, RetrievalAnalyticsAttempt, RetrievalOutcome
from app.core.config import Settings, get_settings
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.entitlement_models import PlanCode, UserEntitlement
from app.family_models import Family, FamilyMembership, FamilyPermissionGrant
from app.media_models import MediaAsset, MediaStatus
from app.models import Device, Memory, User
from app.security_models import (
    SecurityAlert,
    SecurityAlertDeliveryStatus,
    SecuritySeverity,
)
from app.services.admin_security import AdminOperationError
from app.services.entitlement_service import EntitlementError, entitlement_snapshot

_MAX_PAGE_SIZE = 100


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = json.dumps(
        {"t": _as_utc(created_at).isoformat(), "id": str(row_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        observed = datetime.fromisoformat(str(payload["t"]))
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError
        return observed.astimezone(UTC), UUID(str(payload["id"]))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise AdminOperationError("ADMIN_CURSOR_INVALID", 400) from exc


def _bounded_page_size(value: int) -> int:
    return max(1, min(int(value), _MAX_PAGE_SIZE))


def _descending_cursor_filter(created_col, id_col, cursor: str | None):
    decoded = _decode_cursor(cursor)
    if decoded is None:
        return None
    created_at, row_id = decoded
    return or_(
        created_col < created_at,
        and_(created_col == created_at, id_col < row_id),
    )


def _safe_host(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    return parsed.hostname or ""


def _service_configured(provider: str, api_key: str, model: str) -> bool:
    if provider == "disabled":
        return False
    return bool(api_key.strip() and model.strip())


def dashboard_projection(
    db: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> AdminDashboardRead:
    cfg = settings or get_settings()
    observed = _as_utc(now or datetime.now(UTC))
    start = observed.replace(hour=0, minute=0, second=0, microsecond=0)
    today = observed.date()

    overview = AdminDashboardOverview(
        registered_users=int(db.scalar(select(func.count(User.id))) or 0),
        new_users_today=int(
            db.scalar(select(func.count(User.id)).where(User.created_at >= start)) or 0
        ),
        active_users_today=int(
            db.scalar(
                select(func.count(ProductActiveDay.id)).where(
                    ProductActiveDay.activity_date_utc == today
                )
            )
            or 0
        ),
        memories_created_today=int(
            db.scalar(
                select(func.count(Memory.id)).where(
                    Memory.created_at >= start,
                    Memory.is_deleted.is_(False),
                )
            )
            or 0
        ),
        successful_retrievals_today=int(
            db.scalar(
                select(func.count(RetrievalAnalyticsAttempt.id)).where(
                    RetrievalAnalyticsAttempt.occurred_at >= start,
                    RetrievalAnalyticsAttempt.outcome == RetrievalOutcome.SUCCESS,
                )
            )
            or 0
        ),
        active_account_deletions=int(
            db.scalar(select(func.count(AccountDeletionOperation.id))) or 0
        ),
        pending_data_deletions=int(
            db.scalar(
                select(func.count(DataDeletionOperation.id)).where(
                    DataDeletionOperation.status != DataDeletionStatus.COMPLETED
                )
            )
            or 0
        ),
        security_alerts_needing_attention=int(
            db.scalar(
                select(func.count(SecurityAlert.id)).where(
                    SecurityAlert.delivery_status
                    != SecurityAlertDeliveryStatus.DELIVERED.value
                )
            )
            or 0
        ),
    )

    trend_start = today - timedelta(days=6)
    active_rows = dict(
        db.execute(
            select(
                ProductActiveDay.activity_date_utc,
                func.count(ProductActiveDay.id),
            )
            .where(ProductActiveDay.activity_date_utc >= trend_start)
            .group_by(ProductActiveDay.activity_date_utc)
        )
    )
    retrieval_rows = dict(
        db.execute(
            select(
                func.date(RetrievalAnalyticsAttempt.occurred_at),
                func.count(RetrievalAnalyticsAttempt.id),
            )
            .where(
                RetrievalAnalyticsAttempt.occurred_at >= datetime.combine(
                    trend_start,
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
                RetrievalAnalyticsAttempt.outcome == RetrievalOutcome.SUCCESS,
            )
            .group_by(func.date(RetrievalAnalyticsAttempt.occurred_at))
        )
    )
    trend = [
        AdminDashboardTrendPoint(
            day=trend_start + timedelta(days=offset),
            active_users=int(active_rows.get(trend_start + timedelta(days=offset), 0)),
            successful_retrievals=int(
                retrieval_rows.get(
                    (trend_start + timedelta(days=offset)).isoformat(),
                    retrieval_rows.get(trend_start + timedelta(days=offset), 0),
                )
                or 0
            ),
        )
        for offset in range(7)
    ]

    storage_status = "正常" if cfg.storage_backend == "s3" else "未启用"
    ai_status = (
        "正常"
        if _service_configured(cfg.ai_provider, cfg.ai_api_key, cfg.ai_model)
        else "未启用"
    )
    asr_status = (
        "正常"
        if _service_configured(cfg.asr_provider, cfg.asr_api_key, cfg.asr_model)
        else "未启用"
    )
    embedding_status = (
        "正常"
        if _service_configured(
            cfg.embedding_provider,
            cfg.embedding_api_key,
            cfg.embedding_model,
        )
        else "未启用"
    )
    return AdminDashboardRead(
        overview=overview,
        services=[
            AdminServiceStatus(
                key="core",
                label="核心服务",
                status="NORMAL",
                detail="服务运行正常",
            ),
            AdminServiceStatus(
                key="database",
                label="数据库",
                status="NORMAL",
                detail="数据库连接正常",
            ),
            AdminServiceStatus(
                key="storage",
                label="文件存储",
                status="NORMAL" if storage_status == "正常" else "DISABLED",
                detail=storage_status,
            ),
            AdminServiceStatus(
                key="ai",
                label="AI 整理",
                status="NORMAL" if ai_status == "正常" else "DISABLED",
                detail=ai_status,
            ),
            AdminServiceStatus(
                key="asr",
                label="语音识别",
                status="NORMAL" if asr_status == "正常" else "DISABLED",
                detail=asr_status,
            ),
            AdminServiceStatus(
                key="embedding",
                label="记忆检索",
                status="NORMAL" if embedding_status == "正常" else "DISABLED",
                detail=embedding_status,
            ),
        ],
        trend=trend,
    )


def _user_projection_query():
    device_count = (
        select(func.count(Device.id))
        .where(Device.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    last_active = (
        select(func.max(Device.last_active_at))
        .where(Device.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    family_role = (
        select(FamilyMembership.role)
        .where(FamilyMembership.user_id == User.id)
        .correlate(User)
        .limit(1)
        .scalar_subquery()
    )
    storage_used = (
        select(func.coalesce(func.sum(MediaAsset.size_bytes), 0))
        .where(
            MediaAsset.user_id == User.id,
            MediaAsset.status.in_((MediaStatus.PENDING, MediaStatus.READY)),
        )
        .correlate(User)
        .scalar_subquery()
    )
    account_deleting = (
        select(func.count(AccountDeletionOperation.id))
        .where(AccountDeletionOperation.user_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )
    data_deleting = (
        select(func.count(DataDeletionOperation.id))
        .where(
            DataDeletionOperation.user_id == User.id,
            DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
        )
        .correlate(User)
        .scalar_subquery()
    )
    return (
        select(
            User,
            UserEntitlement.plan_code,
            device_count.label("device_count"),
            last_active.label("last_active_at"),
            family_role.label("family_role"),
            storage_used.label("storage_used_bytes"),
            account_deleting.label("account_deleting"),
            data_deleting.label("data_deleting"),
        )
        .join(UserEntitlement, UserEntitlement.user_id == User.id)
    )


def _user_item(row) -> AdminUserListItem:
    user = row[0]
    return AdminUserListItem(
        id=user.id,
        display_name=user.nickname,
        email=user.email,
        created_at=user.created_at,
        last_active_at=row.last_active_at,
        device_count=int(row.device_count or 0),
        plan_code=str(row.plan_code),
        family_role=row.family_role,
        storage_used_bytes=int(row.storage_used_bytes or 0),
        account_deletion_in_progress=bool(row.account_deleting),
        data_deletion_in_progress=bool(row.data_deleting),
    )


def list_users(
    db: Session,
    *,
    search: str | None = None,
    plan: str | None = None,
    registered_from: date | None = None,
    registered_to: date | None = None,
    operational_state: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AdminUserPage:
    query = _user_projection_query()
    normalized_search = (search or "").strip().casefold()
    if normalized_search:
        like = f"%{normalized_search}%"
        query = query.where(
            or_(
                func.lower(func.coalesce(User.email, "")).like(like),
                func.lower(User.nickname).like(like),
            )
        )

    if plan:
        if plan not in {item.value for item in PlanCode}:
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400)
        query = query.where(UserEntitlement.plan_code == plan)

    if registered_from is not None:
        query = query.where(
            User.created_at >= datetime.combine(
                registered_from,
                datetime.min.time(),
                tzinfo=UTC,
            )
        )
    if registered_to is not None:
        query = query.where(
            User.created_at < datetime.combine(
                registered_to + timedelta(days=1),
                datetime.min.time(),
                tzinfo=UTC,
            )
        )
    if registered_from is not None and registered_to is not None:
        if registered_from > registered_to:
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400)

    if operational_state:
        if operational_state == "ACCOUNT_DELETION":
            query = query.where(
                select(AccountDeletionOperation.id)
                .where(AccountDeletionOperation.user_id == User.id)
                .correlate(User)
                .exists()
            )
        elif operational_state == "DATA_DELETION":
            query = query.where(
                select(DataDeletionOperation.id)
                .where(
                    DataDeletionOperation.user_id == User.id,
                    DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
                )
                .correlate(User)
                .exists()
            )
        elif operational_state == "NORMAL":
            query = query.where(
                ~select(AccountDeletionOperation.id)
                .where(AccountDeletionOperation.user_id == User.id)
                .correlate(User)
                .exists(),
                ~select(DataDeletionOperation.id)
                .where(
                    DataDeletionOperation.user_id == User.id,
                    DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
                )
                .correlate(User)
                .exists(),
            )
        else:
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400)

    cursor_filter = _descending_cursor_filter(User.created_at, User.id, cursor)
    if cursor_filter is not None:
        query = query.where(cursor_filter)

    page_size = _bounded_page_size(limit)
    rows = list(
        db.execute(
            query.order_by(User.created_at.desc(), User.id.desc()).limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [_user_item(row) for row in rows]
    next_cursor = None
    if has_more and rows:
        user = rows[-1][0]
        next_cursor = _encode_cursor(user.created_at, user.id)
    return AdminUserPage(items=items, next_cursor=next_cursor)


def user_detail(db: Session, *, user_id: UUID) -> AdminUserDetail:
    row = db.execute(_user_projection_query().where(User.id == user_id)).first()
    if row is None:
        raise AdminOperationError("ADMIN_USER_NOT_FOUND", 404)
    item = _user_item(row)
    entitlement_row = db.get(UserEntitlement, user_id)
    if entitlement_row is None:
        raise AdminOperationError("ADMIN_ENTITLEMENT_UNAVAILABLE", 503)
    try:
        snapshot = entitlement_snapshot(db, user_id=user_id)
    except EntitlementError as exc:
        raise AdminOperationError("ADMIN_ENTITLEMENT_UNAVAILABLE", 503) from exc

    membership = db.scalar(
        select(FamilyMembership).where(FamilyMembership.user_id == user_id)
    )
    deletion = db.scalar(
        select(DataDeletionOperation)
        .where(DataDeletionOperation.user_id == user_id)
        .order_by(DataDeletionOperation.created_at.desc(), DataDeletionOperation.id.desc())
        .limit(1)
    )
    account_delete = db.scalar(
        select(AccountDeletionOperation).where(
            AccountDeletionOperation.user_id == user_id
        )
    )
    return AdminUserDetail(
        user=item,
        entitlement=AdminUserEntitlementRead(
            plan_code=entitlement_row.plan_code,
            revision=entitlement_row.revision,
            effective_at=entitlement_row.effective_at,
            expires_at=entitlement_row.expires_at,
            storage_used_bytes=snapshot.storage_used_bytes,
            storage_limit_bytes=snapshot.storage_limit_bytes,
            ai_requests_used=snapshot.ai_requests_used,
            ai_requests_limit=snapshot.ai_requests_limit,
        ),
        family_id=None if membership is None else membership.family_id,
        data_deletion_status=None if deletion is None else deletion.status.value,
        account_deletion_started_at=None
        if account_delete is None
        else account_delete.created_at,
    )


def list_families(
    db: Session,
    *,
    cursor: str | None = None,
    limit: int = 50,
) -> AdminFamilyPage:
    member_count = (
        select(func.count(FamilyMembership.id))
        .where(FamilyMembership.family_id == Family.id)
        .correlate(Family)
        .scalar_subquery()
    )
    grant_count = (
        select(func.count(FamilyPermissionGrant.id))
        .where(FamilyPermissionGrant.family_id == Family.id)
        .correlate(Family)
        .scalar_subquery()
    )
    query = (
        select(Family, User, member_count.label("member_count"), grant_count.label("grant_count"))
        .join(User, User.id == Family.created_by_user_id)
    )
    cursor_filter = _descending_cursor_filter(Family.created_at, Family.id, cursor)
    if cursor_filter is not None:
        query = query.where(cursor_filter)
    page_size = _bounded_page_size(limit)
    rows = list(
        db.execute(
            query.order_by(Family.created_at.desc(), Family.id.desc()).limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [
        AdminFamilyListItem(
            id=row[0].id,
            owner_user_id=row[1].id,
            owner_display_name=row[1].nickname,
            owner_email=row[1].email,
            member_count=int(row.member_count or 0),
            grant_count=int(row.grant_count or 0),
            created_at=row[0].created_at,
        )
        for row in rows
    ]
    next_cursor = (
        _encode_cursor(rows[-1][0].created_at, rows[-1][0].id)
        if has_more and rows
        else None
    )
    return AdminFamilyPage(items=items, next_cursor=next_cursor)


def family_detail(db: Session, *, family_id: UUID) -> AdminFamilyDetail:
    family = db.get(Family, family_id)
    if family is None:
        raise AdminOperationError("ADMIN_FAMILY_NOT_FOUND", 404)

    memberships = list(
        db.execute(
            select(FamilyMembership, User)
            .join(User, User.id == FamilyMembership.user_id)
            .where(FamilyMembership.family_id == family_id)
            .order_by(FamilyMembership.created_at.asc(), FamilyMembership.id.asc())
        )
    )
    owner_pair = next(
        (row for row in memberships if row[0].role == "OWNER"),
        None,
    )
    if owner_pair is None:
        raise AdminOperationError("ADMIN_FAMILY_STATE_UNAVAILABLE", 503)

    grant_rows = list(
        db.execute(
            select(
                FamilyPermissionGrant.permission_code,
                func.count(FamilyPermissionGrant.id),
            )
            .where(FamilyPermissionGrant.family_id == family_id)
            .group_by(FamilyPermissionGrant.permission_code)
            .order_by(FamilyPermissionGrant.permission_code.asc())
        )
    )
    owner_user = owner_pair[1]
    return AdminFamilyDetail(
        family=AdminFamilyListItem(
            id=family.id,
            owner_user_id=owner_user.id,
            owner_display_name=owner_user.nickname,
            owner_email=owner_user.email,
            member_count=len(memberships),
            grant_count=sum(int(row[1]) for row in grant_rows),
            created_at=family.created_at,
        ),
        members=[
            AdminFamilyMemberRead(
                user_id=user.id,
                display_name=user.nickname,
                email=user.email,
                role=membership.role,
                joined_at=membership.created_at,
            )
            for membership, user in memberships
        ],
        grants=[
            AdminFamilyGrantSummary(
                permission_code=str(code),
                grant_count=int(count),
            )
            for code, count in grant_rows
        ],
    )


_DATA_DELETE_MESSAGES = {
    DataDeletionStatus.STORAGE_PENDING: "正在清理文件数据",
    DataDeletionStatus.WAITING_STORAGE_EXPIRY: "正在等待旧文件访问能力失效",
    DataDeletionStatus.WAITING_STORAGE_QUIET: "正在确认文件清理完成",
    DataDeletionStatus.STORAGE_FAILED: "文件清理未完成，可以按既有流程重试",
    DataDeletionStatus.DB_PENDING: "正在清理账号内数据",
    DataDeletionStatus.DB_FAILED: "数据清理未完成，可以按既有流程重试",
    DataDeletionStatus.COMPLETED: "数据删除已完成",
}


def _apply_safe_user_search(query, search: str | None):
    normalized = (search or "").strip().casefold()
    if not normalized:
        return query
    like = f"%{normalized}%"
    return query.where(
        or_(
            func.lower(func.coalesce(User.email, "")).like(like),
            func.lower(User.nickname).like(like),
        )
    )


def list_data_deletions(
    db: Session,
    *,
    search: str | None = None,
    status_filter: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AdminDataDeletionPage:
    query = (
        select(DataDeletionOperation, User)
        .join(User, User.id == DataDeletionOperation.user_id)
    )
    query = _apply_safe_user_search(query, search)
    if status_filter:
        try:
            status_value = DataDeletionStatus(status_filter)
        except ValueError as exc:
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400) from exc
        query = query.where(DataDeletionOperation.status == status_value)
    cursor_filter = _descending_cursor_filter(
        DataDeletionOperation.created_at,
        DataDeletionOperation.id,
        cursor,
    )
    if cursor_filter is not None:
        query = query.where(cursor_filter)
    page_size = _bounded_page_size(limit)
    rows = list(
        db.execute(
            query.order_by(
                DataDeletionOperation.created_at.desc(),
                DataDeletionOperation.id.desc(),
            ).limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items: list[AdminDataDeletionItem] = []
    for operation, user in rows:
        status = DataDeletionStatus(operation.status)
        wait_until = operation.storage_quiet_until or operation.storage_capability_expires_at
        items.append(
            AdminDataDeletionItem(
                id=operation.id,
                user_id=user.id,
                user_display_name=user.nickname,
                user_email=user.email,
                status=status.value,
                created_at=operation.created_at,
                updated_at=operation.updated_at,
                completed_at=operation.completed_at,
                storage_wait_until=wait_until,
                retryable=status
                in {DataDeletionStatus.STORAGE_FAILED, DataDeletionStatus.DB_FAILED},
                safe_message=_DATA_DELETE_MESSAGES[status],
                deleted_counts={
                    str(key)[:64]: int(value)
                    for key, value in (operation.deleted_counts or {}).items()
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                },
            )
        )
    next_cursor = (
        _encode_cursor(rows[-1][0].created_at, rows[-1][0].id)
        if has_more and rows
        else None
    )
    return AdminDataDeletionPage(items=items, next_cursor=next_cursor)


def list_account_deletions(
    db: Session,
    *,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AdminAccountDeletionPage:
    query = (
        select(AccountDeletionOperation, User)
        .join(User, User.id == AccountDeletionOperation.user_id)
    )
    query = _apply_safe_user_search(query, search)
    cursor_filter = _descending_cursor_filter(
        AccountDeletionOperation.created_at,
        AccountDeletionOperation.id,
        cursor,
    )
    if cursor_filter is not None:
        query = query.where(cursor_filter)
    page_size = _bounded_page_size(limit)
    rows = list(
        db.execute(
            query.order_by(
                AccountDeletionOperation.created_at.desc(),
                AccountDeletionOperation.id.desc(),
            ).limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [
        AdminAccountDeletionItem(
            id=operation.id,
            user_id=user.id,
            user_display_name=user.nickname,
            user_email=user.email,
            created_at=operation.created_at,
            updated_at=operation.updated_at,
            safe_phase="IN_PROGRESS",
            safe_message="账号注销正在处理中；完成后不会保留可关联用户身份的永久注销记录",
        )
        for operation, user in rows
    ]
    next_cursor = (
        _encode_cursor(rows[-1][0].created_at, rows[-1][0].id)
        if has_more and rows
        else None
    )
    return AdminAccountDeletionPage(items=items, next_cursor=next_cursor)


def _security_category(rule_code: str) -> str:
    if rule_code.startswith("AUTH_"):
        return "LOGIN_PROTECTION"
    if rule_code.startswith("FAMILY_"):
        return "FAMILY_ACCESS"
    if rule_code.startswith("DESTRUCTIVE_"):
        return "DATA_SECURITY"
    if rule_code.startswith("STORAGE_"):
        return "STORAGE"
    return "SYSTEM_SECURITY"


def _security_message(rule_code: str) -> str:
    if rule_code.startswith("AUTH_"):
        return "登录保护检测到异常访问"
    if rule_code.startswith("FAMILY_"):
        return "家庭敏感访问出现异常"
    if rule_code.startswith("DESTRUCTIVE_"):
        return "数据删除相关操作出现异常"
    if rule_code.startswith("STORAGE_"):
        return "文件存储能力出现异常"
    return "系统检测到需要关注的安全事件"


def list_security_alerts(
    db: Session,
    *,
    severity: str | None = None,
    category: str | None = None,
    delivery_status: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AdminSecurityAlertPage:
    query = select(SecurityAlert)
    if severity:
        if severity not in {item.value for item in SecuritySeverity}:
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400)
        query = query.where(SecurityAlert.severity == severity)
    if delivery_status:
        if delivery_status not in {item.value for item in SecurityAlertDeliveryStatus}:
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400)
        query = query.where(SecurityAlert.delivery_status == delivery_status)
    if category:
        category_prefixes = {
            "LOGIN_PROTECTION": ("AUTH_",),
            "FAMILY_ACCESS": ("FAMILY_",),
            "DATA_SECURITY": ("DESTRUCTIVE_",),
            "STORAGE": ("STORAGE_",),
        }
        if category == "SYSTEM_SECURITY":
            query = query.where(
                ~SecurityAlert.rule_code.like("AUTH_%"),
                ~SecurityAlert.rule_code.like("FAMILY_%"),
                ~SecurityAlert.rule_code.like("DESTRUCTIVE_%"),
                ~SecurityAlert.rule_code.like("STORAGE_%"),
            )
        elif category in category_prefixes:
            query = query.where(
                or_(
                    *[
                        SecurityAlert.rule_code.like(f"{prefix}%")
                        for prefix in category_prefixes[category]
                    ]
                )
            )
        else:
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400)
    cursor_filter = _descending_cursor_filter(SecurityAlert.created_at, SecurityAlert.id, cursor)
    if cursor_filter is not None:
        query = query.where(cursor_filter)
    page_size = _bounded_page_size(limit)
    rows = list(
        db.scalars(
            query.order_by(SecurityAlert.created_at.desc(), SecurityAlert.id.desc())
            .limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items = [
        AdminSecurityAlertItem(
            id=row.id,
            severity=row.severity,
            category=_security_category(row.rule_code),
            delivery_status=row.delivery_status,
            signal_count=row.signal_count,
            first_seen_at=row.created_at,
            latest_seen_at=row.updated_at,
            next_retry_at=row.next_retry_at,
            safe_message=_security_message(row.rule_code),
        )
        for row in rows
    ]
    next_cursor = (
        _encode_cursor(rows[-1].created_at, rows[-1].id)
        if has_more and rows
        else None
    )
    return AdminSecurityAlertPage(items=items, next_cursor=next_cursor)


def list_admin_audit(
    db: Session,
    *,
    search: str | None = None,
    action: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> AdminAuditPage:
    query = select(AdminAuditEvent)
    normalized_search = (search or "").strip().casefold()
    if normalized_search:
        like = f"%{normalized_search}%"
        query = query.outerjoin(
            AdminAccount,
            AdminAccount.id == AdminAuditEvent.admin_actor_id,
        ).where(
            or_(
                func.lower(func.coalesce(AdminAccount.display_name, "")).like(like),
                func.lower(func.coalesce(AdminAccount.email, "")).like(like),
            )
        )
    if action:
        if len(action) > 96 or not action.replace("_", "").isalnum():
            raise AdminOperationError("ADMIN_FILTER_INVALID", 400)
        query = query.where(AdminAuditEvent.action == action)
    cursor_filter = _descending_cursor_filter(
        AdminAuditEvent.created_at,
        AdminAuditEvent.id,
        cursor,
    )
    if cursor_filter is not None:
        query = query.where(cursor_filter)
    page_size = _bounded_page_size(limit)
    rows = list(
        db.scalars(
            query.order_by(AdminAuditEvent.created_at.desc(), AdminAuditEvent.id.desc())
            .limit(page_size + 1)
        )
    )
    has_more = len(rows) > page_size
    rows = rows[:page_size]
    items: list[AdminAuditRead] = []
    for row in rows:
        actor = db.get(AdminAccount, row.admin_actor_id) if row.admin_actor_id else None
        items.append(
            AdminAuditRead(
                id=row.id,
                actor="已删除管理员" if actor is None else actor.display_name,
                role=row.admin_role_snapshot,
                action=row.action,
                target_type=row.target_type,
                target=row.target_id,
                result=row.result,
                request_ref=row.request_ref,
                metadata=row.metadata_json or {},
                created_at=row.created_at,
            )
        )
    next_cursor = (
        _encode_cursor(rows[-1].created_at, rows[-1].id)
        if has_more and rows
        else None
    )
    return AdminAuditPage(items=items, next_cursor=next_cursor)


def system_settings_projection(
    *,
    settings: Settings | None = None,
) -> AdminSystemSettingsRead:
    cfg = settings or get_settings()
    sections = [
        AdminSettingSectionRead(
            key="ai",
            title="AI 服务",
            items=[
                AdminSettingRead(
                    key="ai_enabled",
                    label="AI 整理服务",
                    classification="需要重新部署",
                    value=cfg.ai_provider != "disabled",
                ),
                AdminSettingRead(
                    key="ai_model",
                    label="当前模型",
                    classification="需要重新部署",
                    value=cfg.ai_model or "未配置",
                ),
                AdminSettingRead(
                    key="ai_timeout",
                    label="请求超时",
                    classification="需要重新部署",
                    value=cfg.ai_timeout_seconds,
                ),
                AdminSettingRead(
                    key="ai_input_limit",
                    label="单次输入上限",
                    classification="需要重新部署",
                    value=cfg.ai_max_input_chars,
                ),
                AdminSettingRead(
                    key="ai_output_limit",
                    label="单次输出上限",
                    classification="需要重新部署",
                    value=cfg.ai_max_output_tokens,
                ),
                AdminSettingRead(
                    key="ai_endpoint",
                    label="服务地址",
                    classification="只读",
                    value=_safe_host(cfg.ai_base_url) or "未配置",
                ),
                AdminSettingRead(
                    key="ai_credential",
                    label="访问凭证",
                    classification="敏感配置",
                    value=None,
                    configured=bool(cfg.ai_api_key.strip()),
                    help_text="配置来源：服务器安全配置",
                ),
            ],
        ),
        AdminSettingSectionRead(
            key="asr",
            title="语音识别",
            items=[
                AdminSettingRead(
                    key="asr_enabled",
                    label="语音识别服务",
                    classification="需要重新部署",
                    value=cfg.asr_provider != "disabled",
                ),
                AdminSettingRead(
                    key="asr_model",
                    label="当前模型",
                    classification="需要重新部署",
                    value=cfg.asr_model,
                ),
                AdminSettingRead(
                    key="asr_timeout",
                    label="请求超时",
                    classification="需要重新部署",
                    value=cfg.asr_timeout_seconds,
                ),
                AdminSettingRead(
                    key="asr_confidence",
                    label="最低识别可信度",
                    classification="需要重新部署",
                    value=cfg.asr_min_confidence,
                ),
                AdminSettingRead(
                    key="asr_credential",
                    label="访问凭证",
                    classification="敏感配置",
                    value=None,
                    configured=bool(cfg.asr_api_key.strip()),
                    help_text="配置来源：服务器安全配置",
                ),
            ],
        ),
        AdminSettingSectionRead(
            key="embedding",
            title="记忆检索",
            items=[
                AdminSettingRead(
                    key="embedding_enabled",
                    label="记忆检索服务",
                    classification="需要重新部署",
                    value=cfg.embedding_provider != "disabled",
                ),
                AdminSettingRead(
                    key="embedding_model",
                    label="当前模型",
                    classification="只读",
                    value=cfg.embedding_model,
                ),
                AdminSettingRead(
                    key="embedding_dimensions",
                    label="向量维度",
                    classification="只读",
                    value=cfg.embedding_dimensions,
                ),
                AdminSettingRead(
                    key="embedding_timeout",
                    label="请求超时",
                    classification="需要重新部署",
                    value=cfg.embedding_timeout_seconds,
                ),
                AdminSettingRead(
                    key="embedding_input_limit",
                    label="单次输入上限",
                    classification="只读",
                    value=cfg.embedding_max_input_chars,
                ),
                AdminSettingRead(
                    key="embedding_endpoint",
                    label="服务地址",
                    classification="只读",
                    value=_safe_host(cfg.embedding_base_url) or "未配置",
                ),
                AdminSettingRead(
                    key="embedding_credential",
                    label="访问凭证",
                    classification="敏感配置",
                    value=None,
                    configured=bool(cfg.embedding_api_key.strip()),
                    help_text="配置来源：服务器安全配置",
                ),
            ],
        ),
        AdminSettingSectionRead(
            key="storage",
            title="文件存储",
            items=[
                AdminSettingRead(
                    key="storage_backend",
                    label="存储服务",
                    classification="需要重新部署",
                    value="已启用" if cfg.storage_backend == "s3" else "未启用",
                ),
                AdminSettingRead(
                    key="storage_bucket",
                    label="存储空间",
                    classification="只读",
                    value=cfg.storage_bucket or "未配置",
                ),
                AdminSettingRead(
                    key="storage_region",
                    label="区域",
                    classification="只读",
                    value=cfg.storage_region or "未配置",
                ),
                AdminSettingRead(
                    key="storage_endpoint",
                    label="服务地址",
                    classification="只读",
                    value=_safe_host(cfg.storage_endpoint_url) or "默认服务地址",
                ),
                AdminSettingRead(
                    key="storage_presign_ttl",
                    label="临时访问有效期",
                    classification="需要重新部署",
                    value=cfg.storage_presign_ttl_seconds,
                ),
                AdminSettingRead(
                    key="storage_addressing",
                    label="寻址方式",
                    classification="需要重新部署",
                    value=cfg.storage_addressing_style,
                ),
                AdminSettingRead(
                    key="storage_prefix",
                    label="对象命名空间",
                    classification="需要重新部署",
                    value=cfg.storage_object_prefix,
                ),
                AdminSettingRead(
                    key="storage_settle",
                    label="删除确认等待（秒）",
                    classification="需要重新部署",
                    value=cfg.storage_delete_settle_seconds,
                ),
                AdminSettingRead(
                    key="storage_credential",
                    label="访问凭证",
                    classification="敏感配置",
                    value=None,
                    configured=bool(
                        cfg.storage_access_key_id.strip()
                        and cfg.storage_secret_access_key.strip()
                    ),
                    help_text="配置来源：服务器安全配置",
                ),
            ],
        ),
        AdminSettingSectionRead(
            key="location",
            title="足迹识别",
            items=[
                AdminSettingRead(
                    key="location_radius",
                    label="到访识别半径（米）",
                    classification="需要重新部署",
                    value=cfg.location_visit_radius_m,
                ),
                AdminSettingRead(
                    key="location_gap",
                    label="连续到访最大间隔（秒）",
                    classification="需要重新部署",
                    value=cfg.location_visit_max_gap_seconds,
                ),
                AdminSettingRead(
                    key="location_duration",
                    label="最短到访时长（秒）",
                    classification="需要重新部署",
                    value=cfg.location_visit_min_duration_seconds,
                ),
                AdminSettingRead(
                    key="location_min_points",
                    label="最少位置点",
                    classification="需要重新部署",
                    value=cfg.location_visit_min_points,
                ),
                AdminSettingRead(
                    key="location_retention",
                    label="原始位置保留天数",
                    classification="需要重新部署",
                    value=cfg.location_raw_retention_days,
                ),
                AdminSettingRead(
                    key="location_late_arrival",
                    label="历史位置回补窗口（秒）",
                    classification="需要重新部署",
                    value=cfg.location_late_arrival_grace_seconds,
                ),
                AdminSettingRead(
                    key="location_future_skew",
                    label="设备时间未来偏差上限（秒）",
                    classification="需要重新部署",
                    value=cfg.location_future_skew_seconds,
                ),
                AdminSettingRead(
                    key="location_precision",
                    label="地点聚合精度",
                    classification="需要重新部署",
                    value=cfg.location_place_geohash_precision,
                ),
            ],
        ),
        AdminSettingSectionRead(
            key="auth",
            title="登录保护",
            items=[
                AdminSettingRead(
                    key="auth_rate_limit",
                    label="登录保护",
                    classification="只读",
                    value=cfg.auth_rate_limit_enabled,
                ),
                AdminSettingRead(
                    key="register_ip_limit",
                    label="注册来源限制",
                    classification="需要重新部署",
                    value=cfg.auth_register_ip_limit,
                ),
                AdminSettingRead(
                    key="register_window",
                    label="注册限制窗口（秒）",
                    classification="需要重新部署",
                    value=cfg.auth_register_window_seconds,
                ),
                AdminSettingRead(
                    key="login_ip_limit",
                    label="登录来源限制",
                    classification="需要重新部署",
                    value=cfg.auth_login_ip_limit,
                ),
                AdminSettingRead(
                    key="login_window",
                    label="登录限制窗口（秒）",
                    classification="需要重新部署",
                    value=cfg.auth_login_window_seconds,
                ),
                AdminSettingRead(
                    key="login_account_limit",
                    label="账号登录失败限制",
                    classification="需要重新部署",
                    value=cfg.auth_login_account_ip_limit,
                ),
                AdminSettingRead(
                    key="login_backoff_threshold",
                    label="触发失败等待的连续次数",
                    classification="需要重新部署",
                    value=cfg.auth_login_backoff_after_failures,
                ),
                AdminSettingRead(
                    key="login_backoff",
                    label="失败等待上限（秒）",
                    classification="需要重新部署",
                    value=cfg.auth_login_backoff_max_seconds,
                ),
            ],
        ),
        AdminSettingSectionRead(
            key="analytics",
            title="数据统计保留",
            items=[
                AdminSettingRead(
                    key="analytics_retrieval_retention",
                    label="检索统计保留天数",
                    classification="需要重新部署",
                    value=cfg.analytics_retrieval_retention_days,
                ),
                AdminSettingRead(
                    key="analytics_active_retention",
                    label="活跃统计保留天数",
                    classification="需要重新部署",
                    value=cfg.analytics_active_day_retention_days,
                ),
            ],
        ),
    ]
    return AdminSystemSettingsRead(sections=sections)


def system_health_projection(
    db: Session,
    *,
    settings: Settings | None = None,
) -> AdminSystemHealthRead:
    cfg = settings or get_settings()
    total_storage = int(
        db.scalar(
            select(func.coalesce(func.sum(MediaAsset.size_bytes), 0)).where(
                MediaAsset.status.in_((MediaStatus.PENDING, MediaStatus.READY))
            )
        )
        or 0
    )
    return AdminSystemHealthRead(
        environment=cfg.app_env,
        api_status="正常",
        database_status="正常",
        storage_status="正常" if cfg.storage_backend == "s3" else "未启用",
        ai_status="正常"
        if _service_configured(cfg.ai_provider, cfg.ai_api_key, cfg.ai_model)
        else "未启用",
        asr_status="正常"
        if _service_configured(cfg.asr_provider, cfg.asr_api_key, cfg.asr_model)
        else "未启用",
        embedding_status="正常"
        if _service_configured(
            cfg.embedding_provider,
            cfg.embedding_api_key,
            cfg.embedding_model,
        )
        else "未启用",
        app_version=cfg.app_version,
        git_sha=cfg.app_git_sha.strip() or None,
        build_time=cfg.app_build_time.strip() or None,
        total_storage_used_bytes=total_storage,
    )
