from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import (
    Memory,
    MemorySource,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
)
from app.schemas import ObjectCreate, ObjectLocationCreate, ObjectLocationRead, ObjectRead
from app.services.memory_service import TrustedMemoryWrite, create_trusted_memory, ensure_utc

router = APIRouter(prefix="/objects", tags=["objects"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


@router.post("", response_model=ObjectRead, status_code=status.HTTP_201_CREATED)
def create_object(payload: ObjectCreate, user_id: CurrentUser, db: DbSession) -> ObjectItem:
    normalized = normalize_name(payload.name)
    existing = db.scalar(
        select(ObjectItem).where(
            ObjectItem.user_id == user_id,
            ObjectItem.normalized_name == normalized,
        )
    )
    if existing is not None:
        return existing

    item = ObjectItem(
        user_id=user_id,
        name=payload.name.strip(),
        normalized_name=normalized,
        category=payload.category,
        description=payload.description,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        # [人工注释][S1-FIX-006] 并发首次创建同名物品时，
        # 唯一键竞争必须回退为幂等读取，不能返回 500。
        db.rollback()
        existing = db.scalar(
            select(ObjectItem).where(
                ObjectItem.user_id == user_id,
                ObjectItem.normalized_name == normalized,
            )
        )
        if existing is not None:
            return existing
        raise

    db.refresh(item)
    return item


@router.get("", response_model=list[ObjectRead])
def list_objects(user_id: CurrentUser, db: DbSession) -> list[ObjectItem]:
    return list(
        db.scalars(
            select(ObjectItem)
            .where(ObjectItem.user_id == user_id)
            .order_by(ObjectItem.name)
        ).all()
    )


def _latest_invalidation(
    db: Session,
    object_id: UUID,
    user_id: UUID,
) -> ObjectLocation | None:
    # [人工注释][S1-011] UNKNOWN ObjectLocation 是“用户已明确否定此前位置”的持久化时间水位。
    # 晚到位置只有 recorded_at 晚于该水位，才可能再次成为 CURRENT。
    return db.scalar(
        select(ObjectLocation)
        .where(
            ObjectLocation.user_id == user_id,
            ObjectLocation.object_id == object_id,
            ObjectLocation.status == ObjectLocationStatus.UNKNOWN,
        )
        .order_by(ObjectLocation.recorded_at.desc())
        .limit(1)
    )


@router.post(
    "/{object_id}/locations",
    response_model=ObjectLocationRead,
    status_code=status.HTTP_201_CREATED,
)
def add_object_location(
    object_id: UUID,
    payload: ObjectLocationCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> ObjectLocation:
    # [人工注释][S1-011] add 与 stale 必须锁同一 Object 行，
    # 让“新位置写入”和“用户明确失效”在 PostgreSQL 上形成单一串行顺序。
    item = db.scalar(
        select(ObjectItem)
        .where(ObjectItem.id == object_id, ObjectItem.user_id == user_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="OBJECT_NOT_FOUND")

    recorded_at = ensure_utc(payload.recorded_at or datetime.now(UTC))
    current = db.scalar(
        select(ObjectLocation)
        .where(
            ObjectLocation.user_id == user_id,
            ObjectLocation.object_id == object_id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
        )
        .order_by(ObjectLocation.recorded_at.desc())
        .limit(1)
    )
    invalidation = _latest_invalidation(db, object_id, user_id)
    invalidated_at = (
        ensure_utc(invalidation.recorded_at) if invalidation is not None else None
    )

    is_newer_than_invalidation = invalidated_at is None or recorded_at > invalidated_at
    is_newer_than_current = current is None or recorded_at > ensure_utc(current.recorded_at)
    becomes_current = is_newer_than_invalidation and is_newer_than_current

    if becomes_current and current is not None:
        current.status = ObjectLocationStatus.STALE
        db.flush()

    source_type = payload.capture_source.to_source_type()
    memory = create_trusted_memory(
        db,
        user_id,
        TrustedMemoryWrite(
            memory_type=MemoryType.OBJECT_LOCATION,
            title=item.name,
            content=f"{item.name}放在{payload.location_text.strip()}",
            occurred_at=recorded_at,
            source_type=source_type,
            confidence=1.0,
            is_confirmed=True,
            place_id=payload.place_id,
            metadata={"object_id": str(object_id)},
            evidence_text=f"{item.name}放在{payload.location_text.strip()}",
        ),
    )

    location = ObjectLocation(
        object_id=object_id,
        user_id=user_id,
        memory_id=memory.id,
        location_text=payload.location_text.strip(),
        place_id=payload.place_id,
        recorded_at=recorded_at,
        confidence=1.0,
        status=(
            ObjectLocationStatus.CURRENT if becomes_current else ObjectLocationStatus.STALE
        ),
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


def _eligible_current_location(
    db: Session, object_id: UUID, user_id: UUID
) -> ObjectLocation | None:
    evidence_exists = select(MemorySource.id).where(
        MemorySource.memory_id == Memory.id,
        MemorySource.source_type != SourceType.AI_INFERENCE,
        MemorySource.confidence >= 0.6,
    ).exists()
    return db.scalar(
        select(ObjectLocation)
        .join(Memory, Memory.id == ObjectLocation.memory_id)
        .where(
            ObjectLocation.object_id == object_id,
            ObjectLocation.user_id == user_id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
            Memory.is_deleted.is_(False),
            Memory.is_confirmed.is_(True),
            Memory.source_type != SourceType.AI_INFERENCE,
            evidence_exists,
        )
        .order_by(ObjectLocation.recorded_at.desc())
        .limit(1)
    )


@router.get("/{object_id}/location", response_model=ObjectLocationRead)
def current_object_location(
    object_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> ObjectLocation:
    location = _eligible_current_location(db, object_id, user_id)
    if location is None:
        raise HTTPException(status_code=404, detail="OBJECT_LOCATION_NOT_FOUND")
    return location


@router.post("/{object_id}/location/stale", response_model=ObjectLocationRead)
def mark_object_location_stale(
    object_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> ObjectLocation:
    # [人工注释][S1-011] stale 与 add 共用 Object FOR UPDATE 锁。
    # 失效提交完成前，其他位置写入不能绕过 invalidation watermark。
    item = db.scalar(
        select(ObjectItem)
        .where(ObjectItem.id == object_id, ObjectItem.user_id == user_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="OBJECT_NOT_FOUND")

    location = _eligible_current_location(db, object_id, user_id)
    if location is None:
        raise HTTPException(status_code=404, detail="OBJECT_LOCATION_NOT_FOUND")

    # [人工注释][S1-011] 水位严格取用户执行失效操作的服务器时间 T；
    # 不能受旧客户端未来 recorded_at 影响，否则可能把合法的新位置长期误判为旧数据。
    invalidated_at = datetime.now(UTC)
    location.status = ObjectLocationStatus.STALE
    db.flush()

    # [人工注释][S1-011] UNKNOWN 行不是“新位置”，而是用户确认旧位置已经失效的时间水位。
    # 它保留在历史中，使离线补传的旧位置在 CURRENT 已为空时也不能复活。
    db.add(
        ObjectLocation(
            object_id=object_id,
            user_id=user_id,
            memory_id=None,
            location_text="用户已确认原位置失效",
            recorded_at=invalidated_at,
            confidence=1.0,
            status=ObjectLocationStatus.UNKNOWN,
        )
    )
    db.commit()
    db.refresh(location)
    return location
