from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.data_deletion_models import (
    DataDeletionObject,
    DataDeletionOperation,
    DataDeletionStatus,
)
from app.family_models import (
    Family,
    FamilyInvite,
    FamilyMembership,
    FamilyPermissionGrant,
    FamilyRole,
)
from app.idempotency_models import ClientMutation
from app.media_models import MediaASRClaim, MediaAsset, MediaEvidenceLink
from app.memory_feedback_models import MemoryFeedback
from app.models import (
    Device,
    FamilyMember,
    FamilyPermission,
    LocationDerivationState,
    LocationIngestReceipt,
    LocationPoint,
    Memory,
    MemoryEdit,
    MemorySource,
    ObjectItem,
    ObjectLocation,
    Place,
    PlaceNameCorrection,
    PrivacyPauseInterval,
    PrivacyState,
    Reminder,
    User,
    Visit,
)
from app.services.embedding_service import delete_owner_memory_embeddings
from app.services.object_storage import (
    DisabledObjectStorage,
    ObjectStorage,
    ObjectStorageError,
)

# Settings caps every media upload presign at <= 3600 seconds. A capability can start
# a PUT before expiry and finish afterwards, so expiry and in-flight settlement are
# intentionally modeled as two different durable phases.
MAX_OUTSTANDING_UPLOAD_TTL_SECONDS = 3600
OBJECT_KEY_DB_BATCH_SIZE = 500

# [人工注释][S1-021] 这是当前 user-owned 持久化面的显式清单。新增用户数据表时，
# 删除服务与测试必须同步扩展；User/AuthIdentity 是 S1-022 的账号身份，不在本阶段删除。
USER_DATA_INVENTORY = (
    "devices",
    "places",
    "place_name_corrections",
    "visits",
    "memories",
    "memory_edits",
    "memory_feedbacks",
    "memory_sources",
    "memory_embeddings",
    "location_derivation_states",
    "location_ingest_receipts",
    "location_points",
    "objects",
    "object_locations",
    "reminders",
    "privacy_states",
    "privacy_pause_intervals",
    "family_members",
    "family_permissions",
    "families",
    "family_memberships",
    "family_invites",
    "family_permission_grants",
    "media_assets",
    "media_asr_claims",
    "media_evidence_links",
    "client_mutations",
    "object_storage_final_prefix",
    "object_storage_staging_prefix",
)
PRESERVED_ACCOUNT_SURFACES = (
    "users",
    "account_deletion_operations",
    "auth_identities",
    "auth_rate_limit_buckets",
    "data_deletion_operations",
)


class DataDeletionError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class DataDeletionResult:
    request_id: UUID
    status: DataDeletionStatus
    completed: bool
    retry_after_seconds: int | None
    deleted_counts: dict[str, int]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _operation_result(operation: DataDeletionOperation) -> DataDeletionResult:
    retry_after: int | None = None
    deadline: datetime | None = None
    if operation.status == DataDeletionStatus.WAITING_STORAGE_EXPIRY:
        deadline = operation.storage_capability_expires_at
    elif operation.status == DataDeletionStatus.WAITING_STORAGE_QUIET:
        deadline = operation.storage_quiet_until
    if deadline is not None:
        retry_after = max(
            0,
            math.ceil((_as_utc(deadline) - datetime.now(UTC)).total_seconds()),
        )
    return DataDeletionResult(
        request_id=operation.request_id,
        status=operation.status,
        completed=operation.status == DataDeletionStatus.COMPLETED,
        retry_after_seconds=retry_after,
        deleted_counts={
            str(key): int(value) for key, value in (operation.deleted_counts or {}).items()
        },
    )


def _storage_prefixes(user_id: UUID) -> tuple[str, str]:
    # Keep this derivation identical to media_service._object_keys. Prefixes end with '/'
    # so one user's UUID cannot match another user's object namespace by string prefix.
    root = get_settings().storage_object_prefix.strip("/") or "media"
    return f"{root}/_staging/{user_id}/", f"{root}/{user_id}/"


def _storage_staging_prefix(user_id: UUID) -> str:
    return _storage_prefixes(user_id)[0]


def _settle_delta() -> timedelta:
    return timedelta(seconds=get_settings().storage_delete_settle_seconds)


def _extend_capability_and_quiet_window(
    operation: DataDeletionOperation,
    *,
    now: datetime,
) -> None:
    capability_expires_at = now + timedelta(seconds=MAX_OUTSTANDING_UPLOAD_TTL_SECONDS)
    if (
        operation.storage_capability_expires_at is None
        or _as_utc(operation.storage_capability_expires_at) < capability_expires_at
    ):
        operation.storage_capability_expires_at = capability_expires_at

    quiet_until = capability_expires_at + _settle_delta()
    if (
        operation.storage_quiet_until is None
        or _as_utc(operation.storage_quiet_until) < quiet_until
    ):
        operation.storage_quiet_until = quiet_until


def _reset_quiet_window(operation: DataDeletionOperation, *, now: datetime) -> None:
    quiet_until = now + _settle_delta()
    if operation.storage_capability_expires_at is not None:
        quiet_until = max(
            quiet_until,
            _as_utc(operation.storage_capability_expires_at) + _settle_delta(),
        )
    operation.storage_quiet_until = quiet_until


def _is_owned_storage_key(user_id: UUID, object_key: str) -> bool:
    return any(object_key.startswith(prefix) for prefix in _storage_prefixes(user_id))


def _db_media_keys(db: Session, user_id: UUID) -> set[str]:
    rows = db.execute(
        select(MediaAsset.upload_object_key, MediaAsset.object_key).where(
            MediaAsset.user_id == user_id
        )
    ).all()
    keys = {key for row in rows for key in row if key}
    if any(not _is_owned_storage_key(user_id, key) for key in keys):
        # [人工注释][S1-021] 即使 DB 被旧 bug/人工操作污染，也不能把存储 key
        # 当作可信 owner 信息。发现越界 key 时整次删除 fail closed，不碰任何 blob。
        raise DataDeletionError("DATA_DELETION_STORAGE_OWNERSHIP_INVALID", 500)
    return keys


def _key_batches(keys: set[str]):
    ordered = sorted(keys)
    for start in range(0, len(ordered), OBJECT_KEY_DB_BATCH_SIZE):
        yield ordered[start : start + OBJECT_KEY_DB_BATCH_SIZE]


def _add_db_key_obligations(
    db: Session,
    operation: DataDeletionOperation,
    keys: set[str],
) -> int:
    if not keys:
        return 0
    existing: set[str] = set()
    for batch in _key_batches(keys):
        existing.update(
            db.scalars(
                select(DataDeletionObject.object_key).where(
                    DataDeletionObject.deletion_id == operation.id,
                    DataDeletionObject.object_key.in_(batch),
                )
            ).all()
        )
    missing = keys - existing
    for key in missing:
        db.add(DataDeletionObject(deletion_id=operation.id, object_key=key))
    return len(missing)


def _capture_present_storage_keys(
    db: Session,
    operation_id: UUID,
    keys: set[str],
) -> int:
    """Persist keys proven present by LIST; reappearance resets an already-done obligation."""

    if not keys:
        return 0
    existing_rows: list[DataDeletionObject] = []
    for batch in _key_batches(keys):
        existing_rows.extend(
            db.scalars(
                select(DataDeletionObject).where(
                    DataDeletionObject.deletion_id == operation_id,
                    DataDeletionObject.object_key.in_(batch),
                )
            )
        )
    existing = {row.object_key: row for row in existing_rows}
    changed = 0
    for key in keys:
        row = existing.get(key)
        if row is None:
            db.add(DataDeletionObject(deletion_id=operation_id, object_key=key))
            changed += 1
        elif row.deleted_at is not None:
            # A previously deleted staging key can be recreated by an old presigned PUT.
            # Seeing it in LIST is authoritative evidence that cleanup is pending again.
            row.deleted_at = None
            changed += 1
    return changed


def _lock_user(db: Session, user_id: UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        db.rollback()
        raise DataDeletionError("USER_NOT_FOUND", 404)
    return user


def _find_operation(
    db: Session,
    user_id: UUID,
    request_id: UUID,
) -> DataDeletionOperation | None:
    return db.scalar(
        select(DataDeletionOperation).where(
            DataDeletionOperation.user_id == user_id,
            DataDeletionOperation.request_id == request_id,
        )
    )


def _begin_or_load_operation(
    db: Session,
    user_id: UUID,
    request_id: UUID,
) -> DataDeletionOperation:
    _lock_user(db, user_id)
    existing = _find_operation(db, user_id, request_id)
    if existing is not None:
        db.commit()
        return existing

    active = db.scalar(
        select(DataDeletionOperation).where(
            DataDeletionOperation.user_id == user_id,
            DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
        )
    )
    if active is not None:
        db.rollback()
        raise DataDeletionError("DATA_DELETION_ALREADY_IN_PROGRESS", 409)

    media_keys = _db_media_keys(db, user_id)
    operation = DataDeletionOperation(
        user_id=user_id,
        request_id=request_id,
        status=DataDeletionStatus.STORAGE_PENDING,
    )
    # [人工注释][S1-021-FIX-002] DB 中存在 MediaAsset 时，删除开始前最后一刻
    # 仍可能已经签出 PUT。先等 capability 上限，再等独立 in-flight settle window。
    if media_keys:
        _extend_capability_and_quiet_window(operation, now=datetime.now(UTC))

    db.add(operation)
    db.flush()
    _add_db_key_obligations(db, operation, media_keys)
    try:
        db.commit()
        return operation
    except IntegrityError:
        # PostgreSQL's user row lock normally serializes this path; the unique indexes are
        # still the final guard for SQLite/other races and must recover idempotently.
        db.rollback()
        existing = _find_operation(db, user_id, request_id)
        if existing is not None:
            return existing
        active = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
            )
        )
        db.rollback()
        if active is not None:
            raise DataDeletionError("DATA_DELETION_ALREADY_IN_PROGRESS", 409) from None
        raise


def _quiesce_and_capture_database_media(
    db: Session,
    operation_id: UUID,
    user_id: UUID,
) -> DataDeletionOperation:
    # [人工注释][S1-021] 普通请求在 deps.py 持有 User 的 KEY SHARE 锁；这里拿 UPDATE
    # 锁会先等已放行事务退出，再补抓其新建的 MediaAsset，封住 inventory 与删除之间的竞态。
    _lock_user(db, user_id)
    operation = db.scalar(
        select(DataDeletionOperation)
        .where(DataDeletionOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        db.rollback()
        raise DataDeletionError("DATA_DELETION_NOT_FOUND", 404)
    if operation.status == DataDeletionStatus.COMPLETED:
        db.commit()
        return operation

    added = _add_db_key_obligations(db, operation, _db_media_keys(db, user_id))
    if added:
        _extend_capability_and_quiet_window(operation, now=datetime.now(UTC))
    operation.status = DataDeletionStatus.STORAGE_PENDING
    operation.last_error_code = None
    db.commit()
    return operation


def _list_live_storage_keys(storage: ObjectStorage, user_id: UUID) -> set[str]:
    if isinstance(storage, DisabledObjectStorage):
        return set()
    keys: set[str] = set()
    try:
        for prefix in _storage_prefixes(user_id):
            for key in storage.iter_object_keys(prefix):
                if not key.startswith(prefix):
                    raise ObjectStorageError("storage returned object outside user prefix")
                keys.add(key)
    except ObjectStorageError:
        raise
    except Exception as exc:
        raise ObjectStorageError("failed to list user objects") from exc
    return keys


def _record_storage_listing(
    db: Session,
    operation_id: UUID,
    user_id: UUID,
    keys: set[str],
) -> int:
    operation = db.scalar(
        select(DataDeletionOperation)
        .where(DataDeletionOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        db.rollback()
        raise DataDeletionError("DATA_DELETION_NOT_FOUND", 404)
    if operation.status == DataDeletionStatus.COMPLETED:
        db.commit()
        return 0

    changed = _capture_present_storage_keys(db, operation_id, keys)
    if keys:
        now = datetime.now(UTC)
        # [人工注释][S1-021-FIX-002] 任何 late object 都重新开始真实 quiet window。
        # 若首次发现的是 DB 无引用 staging orphan，则还必须假设可能存在同批旧签名，
        # 从“首次发现时刻 + 最大 TTL”重新建立 capability expiry 上界。
        if (
            operation.storage_capability_expires_at is None
            and any(key.startswith(_storage_staging_prefix(user_id)) for key in keys)
        ):
            _extend_capability_and_quiet_window(operation, now=now)
        else:
            _reset_quiet_window(operation, now=now)
        operation.status = DataDeletionStatus.STORAGE_PENDING
        operation.last_error_code = None
    elif changed:
        operation.status = DataDeletionStatus.STORAGE_PENDING
        operation.last_error_code = None
    db.commit()
    return changed


def _mark_failure(
    db: Session,
    operation_id: UUID,
    status_value: DataDeletionStatus,
    code: str,
) -> None:
    try:
        operation = db.scalar(
            select(DataDeletionOperation)
            .where(DataDeletionOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None or operation.status == DataDeletionStatus.COMPLETED:
            db.rollback()
            return
        operation.status = status_value
        operation.last_error_code = code
        db.commit()
    except Exception:
        db.rollback()


def _capture_storage_listing(
    db: Session,
    operation_id: UUID,
    user_id: UUID,
    storage: ObjectStorage,
) -> set[str]:
    try:
        live_keys = _list_live_storage_keys(storage, user_id)
    except ObjectStorageError as exc:
        _mark_failure(
            db,
            operation_id,
            DataDeletionStatus.STORAGE_FAILED,
            "DATA_DELETION_STORAGE_UNAVAILABLE",
        )
        raise DataDeletionError("DATA_DELETION_STORAGE_UNAVAILABLE", 503) from exc
    _record_storage_listing(db, operation_id, user_id, live_keys)
    return live_keys


def _pending_storage_objects(db: Session, operation_id: UUID) -> list[tuple[UUID, str]]:
    rows = db.execute(
        select(DataDeletionObject.id, DataDeletionObject.object_key).where(
            DataDeletionObject.deletion_id == operation_id,
            DataDeletionObject.deleted_at.is_(None),
        )
    ).all()
    db.rollback()
    return [(row[0], row[1]) for row in rows]


def _delete_pending_storage(
    db: Session,
    operation_id: UUID,
    storage: ObjectStorage,
) -> None:
    for object_id, object_key in _pending_storage_objects(db, operation_id):
        try:
            # DeleteObject is intentionally retried if the process crashed after the remote
            # delete but before deleted_at commit; supported stores treat missing keys safely.
            storage.delete_object(object_key)
        except ObjectStorageError as exc:
            _mark_failure(
                db,
                operation_id,
                DataDeletionStatus.STORAGE_FAILED,
                "DATA_DELETION_STORAGE_UNAVAILABLE",
            )
            raise DataDeletionError("DATA_DELETION_STORAGE_UNAVAILABLE", 503) from exc

        row = db.scalar(
            select(DataDeletionObject)
            .where(DataDeletionObject.id == object_id)
            .with_for_update()
        )
        if row is not None and row.deleted_at is None:
            row.deleted_at = datetime.now(UTC)
        operation = db.get(DataDeletionOperation, operation_id)
        if operation is not None and operation.status != DataDeletionStatus.COMPLETED:
            operation.status = DataDeletionStatus.STORAGE_PENDING
            operation.last_error_code = None
        db.commit()


def _wait_for_storage_safety_window(
    db: Session,
    operation_id: UUID,
) -> DataDeletionResult | None:
    operation = db.scalar(
        select(DataDeletionOperation)
        .where(DataDeletionOperation.id == operation_id)
        .with_for_update()
    )
    if operation is None:
        db.rollback()
        raise DataDeletionError("DATA_DELETION_NOT_FOUND", 404)
    if operation.status == DataDeletionStatus.COMPLETED:
        db.commit()
        return _operation_result(operation)

    now = datetime.now(UTC)
    if (
        operation.storage_capability_expires_at is not None
        and _as_utc(operation.storage_capability_expires_at) > now
    ):
        operation.status = DataDeletionStatus.WAITING_STORAGE_EXPIRY
        operation.last_error_code = None
        db.commit()
        return _operation_result(operation)

    if (
        operation.storage_quiet_until is not None
        and _as_utc(operation.storage_quiet_until) > now
    ):
        operation.status = DataDeletionStatus.WAITING_STORAGE_QUIET
        operation.last_error_code = None
        db.commit()
        return _operation_result(operation)

    db.rollback()
    return None


def _delete_count(db: Session, statement) -> int:
    result = db.execute(statement)
    rowcount = getattr(result, "rowcount", 0)
    return int(rowcount) if isinstance(rowcount, int) and rowcount > 0 else 0


def _delete_owned_database_rows(db: Session, user_id: UUID) -> dict[str, int]:
    """Delete every current application-data surface, but preserve account identity."""

    media_ids = select(MediaAsset.id).where(MediaAsset.user_id == user_id)
    memory_ids = select(Memory.id).where(Memory.user_id == user_id)
    memory_source_ids = select(MemorySource.id).where(
        MemorySource.memory_id.in_(memory_ids)
    )

    counts: dict[str, int] = {}
    counts["media_evidence_links"] = _delete_count(
        db,
        delete(MediaEvidenceLink).where(
            or_(
                MediaEvidenceLink.media_id.in_(media_ids),
                MediaEvidenceLink.memory_source_id.in_(memory_source_ids),
            )
        ),
    )
    counts["media_asr_claims"] = _delete_count(
        db, delete(MediaASRClaim).where(MediaASRClaim.media_id.in_(media_ids))
    )
    counts["object_locations"] = _delete_count(
        db, delete(ObjectLocation).where(ObjectLocation.user_id == user_id)
    )
    counts["reminders"] = _delete_count(
        db, delete(Reminder).where(Reminder.user_id == user_id)
    )
    # [人工注释][S1-021][S1-018] MemoryEdit 保存 before/after 用户正文，属于完整用户数据。
    # 必须在 MemorySource/Memory 之前显式删除并计数，不能只依赖 FK cascade 隐式收敛。
    counts["memory_feedbacks"] = _delete_count(
        db, delete(MemoryFeedback).where(MemoryFeedback.user_id == user_id)
    )
    counts["memory_edits"] = _delete_count(
        db, delete(MemoryEdit).where(MemoryEdit.user_id == user_id)
    )
    counts["memory_embeddings"] = delete_owner_memory_embeddings(db, user_id)
    counts["memory_sources"] = _delete_count(
        db, delete(MemorySource).where(MemorySource.memory_id.in_(memory_ids))
    )
    counts["visits"] = _delete_count(db, delete(Visit).where(Visit.user_id == user_id))
    # [人工注释][S2-010] 纠正历史保存用户曾输入的地点名称，属于完整 user data；
    # 在 Place 之前显式删除并计数，不能只依赖 ON DELETE CASCADE。
    counts["place_name_corrections"] = _delete_count(
        db,
        delete(PlaceNameCorrection).where(PlaceNameCorrection.user_id == user_id),
    )
    # [人工注释][S2-014] finalized watermark 属于 owner 的位置数据控制面；
    # S1-021 必须显式清掉，后续同账号不能继承已删除历史的 retention 水位。
    counts["location_derivation_states"] = _delete_count(
        db,
        delete(LocationDerivationState).where(
            LocationDerivationState.user_id == user_id
        ),
    )
    counts["location_ingest_receipts"] = _delete_count(
        db,
        delete(LocationIngestReceipt).where(
            LocationIngestReceipt.user_id == user_id
        ),
    )
    counts["location_points"] = _delete_count(
        db, delete(LocationPoint).where(LocationPoint.user_id == user_id)
    )
    # [人工注释][S4-001~003] 正式 Family foundation 与 0001 legacy 占位表并存期间，
    # Data Delete 必须先清正式 grant/membership。OWNER 删除数据会解散整个 Family；
    # MEMBER 删除数据只退出自身 membership，不能影响同 Family 其他成员事实数据。
    family_membership = db.scalar(
        select(FamilyMembership).where(FamilyMembership.user_id == user_id)
    )
    if family_membership is not None and family_membership.role == FamilyRole.OWNER.value:
        family_id = family_membership.family_id
        counts["family_permission_grants"] = _delete_count(
            db,
            delete(FamilyPermissionGrant).where(
                FamilyPermissionGrant.family_id == family_id
            ),
        )
        counts["family_invites"] = _delete_count(
            db, delete(FamilyInvite).where(FamilyInvite.family_id == family_id)
        )
        counts["family_memberships"] = _delete_count(
            db,
            delete(FamilyMembership).where(FamilyMembership.family_id == family_id),
        )
        counts["families"] = _delete_count(
            db, delete(Family).where(Family.id == family_id)
        )
    else:
        counts["family_permission_grants"] = _delete_count(
            db,
            delete(FamilyPermissionGrant).where(
                or_(
                    FamilyPermissionGrant.resource_owner_user_id == user_id,
                    FamilyPermissionGrant.grantee_user_id == user_id,
                )
            ),
        )
        counts["family_invites"] = _delete_count(
            db,
            delete(FamilyInvite).where(
                or_(
                    FamilyInvite.inviter_user_id == user_id,
                    FamilyInvite.accepted_by_user_id == user_id,
                )
            ),
        )
        counts["family_memberships"] = _delete_count(
            db,
            delete(FamilyMembership).where(FamilyMembership.user_id == user_id),
        )
        counts["families"] = 0

    # Legacy pre-Stage4 placeholders are non-authoritative but remain part of the old
    # deletion inventory until a dedicated compatibility migration removes them.
    counts["family_permissions"] = _delete_count(
        db,
        delete(FamilyPermission).where(
            or_(
                FamilyPermission.owner_user_id == user_id,
                FamilyPermission.member_user_id == user_id,
            )
        ),
    )
    counts["family_members"] = _delete_count(
        db,
        delete(FamilyMember).where(
            or_(
                FamilyMember.owner_user_id == user_id,
                FamilyMember.member_user_id == user_id,
            )
        ),
    )
    counts["client_mutations"] = _delete_count(
        db, delete(ClientMutation).where(ClientMutation.user_id == user_id)
    )
    counts["privacy_pause_intervals"] = _delete_count(
        db, delete(PrivacyPauseInterval).where(PrivacyPauseInterval.user_id == user_id)
    )
    counts["privacy_states"] = _delete_count(
        db, delete(PrivacyState).where(PrivacyState.user_id == user_id)
    )
    counts["media_assets"] = _delete_count(
        db, delete(MediaAsset).where(MediaAsset.user_id == user_id)
    )
    counts["memories"] = _delete_count(
        db, delete(Memory).where(Memory.user_id == user_id)
    )
    counts["objects"] = _delete_count(
        db, delete(ObjectItem).where(ObjectItem.user_id == user_id)
    )
    counts["places"] = _delete_count(db, delete(Place).where(Place.user_id == user_id))
    counts["devices"] = _delete_count(db, delete(Device).where(Device.user_id == user_id))
    return counts


def _complete_database_cleanup(
    db: Session,
    operation_id: UUID,
    user_id: UUID,
) -> DataDeletionResult:
    try:
        # [人工注释][S1-021] 最终 DB 删除与 COMPLETED 状态同一事务提交；任意异常整体
        # rollback，绝不出现“业务行只删了一半但任务显示成功”。
        _lock_user(db, user_id)
        operation = db.scalar(
            select(DataDeletionOperation)
            .where(DataDeletionOperation.id == operation_id)
            .with_for_update()
        )
        if operation is None:
            raise DataDeletionError("DATA_DELETION_NOT_FOUND", 404)
        if operation.status == DataDeletionStatus.COMPLETED:
            db.commit()
            return _operation_result(operation)

        pending = db.scalar(
            select(DataDeletionObject.id).where(
                DataDeletionObject.deletion_id == operation_id,
                DataDeletionObject.deleted_at.is_(None),
            )
        )
        if pending is not None:
            operation.status = DataDeletionStatus.STORAGE_PENDING
            db.commit()
            raise DataDeletionError("DATA_DELETION_STORAGE_PENDING", 409)

        operation.status = DataDeletionStatus.DB_PENDING
        operation.last_error_code = None
        db.flush()
        counts = _delete_owned_database_rows(db, user_id)
        db.execute(
            delete(DataDeletionObject).where(DataDeletionObject.deletion_id == operation_id)
        )
        operation.deleted_counts = counts
        operation.status = DataDeletionStatus.COMPLETED
        operation.completed_at = datetime.now(UTC)
        operation.updated_at = datetime.now(UTC)
        db.commit()
        return _operation_result(operation)
    except DataDeletionError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        _mark_failure(
            db,
            operation_id,
            DataDeletionStatus.DB_FAILED,
            "DATA_DELETION_DATABASE_FAILED",
        )
        raise DataDeletionError("DATA_DELETION_DATABASE_FAILED", 503) from exc


def delete_all_user_data(
    db: Session,
    *,
    user_id: UUID,
    request_id: UUID,
    storage: ObjectStorage,
) -> DataDeletionResult:
    """Converge one destructive request across DB and object storage.

    Cache inventory note: the current backend has no user-scoped Redis/in-memory content
    cache. Its only user-adjacent ephemeral state is MediaASRClaim and ClientMutation,
    both deleted transactionally below. AuthRateLimitBucket stores only anonymous HMAC
    buckets and cannot be mapped back to a user, so it is intentionally preserved.
    """

    operation = _begin_or_load_operation(db, user_id, request_id)
    if operation.status == DataDeletionStatus.COMPLETED:
        return _operation_result(operation)

    operation = _quiesce_and_capture_database_media(db, operation.id, user_id)
    if operation.status == DataDeletionStatus.COMPLETED:
        return _operation_result(operation)

    # Capture DB-untracked orphan objects too; DB-only deletion is never sufficient.
    _capture_storage_listing(db, operation.id, user_id, storage)
    _delete_pending_storage(db, operation.id, storage)

    waiting = _wait_for_storage_safety_window(db, operation.id)
    if waiting is not None:
        return waiting

    # [人工注释][S1-021-FIX-002] quiet window 结束后只做一次最终 authoritative LIST。
    # 如果此刻又出现 late object，删除它并由 _record_storage_listing() 重新启动 quiet；
    # 绝不使用“瞬间连续 LIST N 次”冒充时间上的稳定为空。
    final_live_keys = _capture_storage_listing(db, operation.id, user_id, storage)
    if final_live_keys:
        _delete_pending_storage(db, operation.id, storage)
        waiting = _wait_for_storage_safety_window(db, operation.id)
        if waiting is not None:
            return waiting
        raise DataDeletionError("DATA_DELETION_STORAGE_PENDING", 409)

    return _complete_database_cleanup(db, operation.id, user_id)
