from __future__ import annotations

import argparse
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.account_deletion_models import AccountDeletionOperation
from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    SessionLocal,
    UserDataAdmission,
)
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.models import LocationDerivationState, LocationPoint, User
from app.services.location_service import (
    LocationMaintenanceResult,
    maintain_location_history,
)


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--now must include an explicit timezone offset")
    return parsed.astimezone(UTC)


def discover_location_maintenance_owner_ids() -> set[UUID]:
    with SessionLocal() as discovery:
        owner_ids: set[UUID] = set(
            discovery.scalars(select(LocationPoint.user_id).distinct())
        )
        owner_ids.update(discovery.scalars(select(LocationDerivationState.user_id)))
        return owner_ids


def _admit_location_maintenance(db: Session, user_id: UUID) -> bool:
    # [人工注释][S2-014][S1-021] maintenance 也是 user-data writer：先持有 User
    # KEY SHARE 并建立与普通 API 相同的 deletion generation admission。Data Delete /
    # Account Delete 的 User FOR UPDATE 只能在本事务结束后越过，从数据库层串行化两边。
    existing = db.scalar(
        select(User.id)
        .where(User.id == user_id)
        .with_for_update(read=True, key_share=True)
    )
    if existing is None:
        db.rollback()
        return False

    active_account_delete = db.scalar(
        select(AccountDeletionOperation.id)
        .where(AccountDeletionOperation.user_id == user_id)
        .limit(1)
    )
    active_data_delete = db.scalar(
        select(DataDeletionOperation.id)
        .where(
            DataDeletionOperation.user_id == user_id,
            DataDeletionOperation.status != DataDeletionStatus.COMPLETED,
        )
        .limit(1)
    )
    if active_account_delete is not None or active_data_delete is not None:
        db.rollback()
        return False

    deletion_generation = int(
        db.scalar(
            select(func.count(DataDeletionOperation.id)).where(
                DataDeletionOperation.user_id == user_id
            )
        )
        or 0
    )
    db.info[USER_DATA_ADMISSION_INFO_KEY] = UserDataAdmission(
        user_id=user_id,
        deletion_generation=deletion_generation,
    )

    # [人工注释][S2-014] discovery 只是快照。若 owner 在 discovery 后完成 S1-021，
    # raw 与 derivation state 都会消失；这里必须 no-op，绝不能为了“跑一次 sweep”
    # 再调用 lock_location_derivation_state() 把已删除的 state 复活。
    has_raw = db.scalar(
        select(LocationPoint.id)
        .where(LocationPoint.user_id == user_id)
        .limit(1)
    )
    has_state = db.scalar(
        select(LocationDerivationState.user_id)
        .where(LocationDerivationState.user_id == user_id)
        .limit(1)
    )
    if has_raw is None and has_state is None:
        db.info.pop(USER_DATA_ADMISSION_INFO_KEY, None)
        db.rollback()
        return False
    return True


def maintain_discovered_location_owner(
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> LocationMaintenanceResult | None:
    effective_now = now or datetime.now(UTC)
    with SessionLocal() as db:
        if not _admit_location_maintenance(db, user_id):
            return None
        return maintain_location_history(
            db,
            user_id=user_id,
            now=effective_now,
        )


def sweep_all_location_history(*, now: datetime | None = None) -> tuple[int, int]:
    effective_now = now or datetime.now(UTC)
    owner_ids = discover_location_maintenance_owner_ids()

    deleted = 0
    for user_id in sorted(owner_ids, key=str):
        # [人工注释][S2-014] 每个 owner 独立事务；stale discovery 在 admission 处
        # 收敛为 no-op。调度器可安全重跑，且单账号失败不会回滚已完成的其它 owner。
        result = maintain_discovered_location_owner(
            user_id,
            now=effective_now,
        )
        if result is not None:
            deleted += result.raw_deleted
    return len(owner_ids), deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Advance location derivation watermarks and delete expired raw GPS."
    )
    parser.add_argument(
        "--now",
        help="Optional ISO-8601 UTC/offset timestamp for controlled maintenance runs.",
    )
    args = parser.parse_args()
    owners, deleted = sweep_all_location_history(now=_parse_now(args.now))
    print(f"location retention sweep: owners={owners} raw_deleted={deleted}")


if __name__ == "__main__":
    main()
