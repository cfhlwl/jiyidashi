from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
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
    db.commit()
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
    # Row lock serializes writes for the same object on PostgreSQL. The partial
    # unique index remains the final database invariant for CURRENT.
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
    becomes_current = current is None or recorded_at > ensure_utc(current.recorded_at)

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
    location = _eligible_current_location(db, object_id, user_id)
    if location is None:
        raise HTTPException(status_code=404, detail="OBJECT_LOCATION_NOT_FOUND")

    db.execute(
        update(ObjectLocation)
        .where(ObjectLocation.id == location.id)
        .values(status=ObjectLocationStatus.STALE)
    )
    db.commit()
    db.refresh(location)
    return location
