from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import MemoryType, ObjectItem, ObjectLocation, ObjectLocationStatus
from app.schemas import (
    MemoryCreate,
    ObjectCreate,
    ObjectLocationCreate,
    ObjectLocationRead,
    ObjectRead,
)
from app.services.memory_service import create_memory

router = APIRouter(prefix="/objects", tags=["objects"])


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


@router.post("", response_model=ObjectRead, status_code=status.HTTP_201_CREATED)
def create_object(
    payload: ObjectCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> ObjectItem:
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
def list_objects(
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[ObjectItem]:
    result = db.scalars(
        select(ObjectItem).where(ObjectItem.user_id == user_id).order_by(ObjectItem.name)
    )
    return list(result.all())


@router.post(
    "/{object_id}/locations",
    response_model=ObjectLocationRead,
    status_code=status.HTTP_201_CREATED,
)
def add_object_location(
    object_id: UUID,
    payload: ObjectLocationCreate,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> ObjectLocation:
    item = db.scalar(
        select(ObjectItem).where(
            ObjectItem.id == object_id,
            ObjectItem.user_id == user_id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="OBJECT_NOT_FOUND")

    recorded_at = payload.recorded_at or datetime.now(UTC)

    # Preserve history: old rows become STALE instead of being overwritten.
    db.execute(
        update(ObjectLocation)
        .where(
            ObjectLocation.user_id == user_id,
            ObjectLocation.object_id == object_id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
        )
        .values(status=ObjectLocationStatus.STALE)
    )

    memory = create_memory(
        db,
        user_id,
        MemoryCreate(
            memory_type=MemoryType.OBJECT_LOCATION,
            title=item.name,
            content=f"{item.name}放在{payload.location_text.strip()}",
            occurred_at=recorded_at,
            source_type=payload.source_type,
            confidence=payload.confidence,
            place_id=payload.place_id,
            is_confirmed=True,
            metadata={"object_id": str(object_id)},
        ),
    )

    location = ObjectLocation(
        object_id=object_id,
        user_id=user_id,
        memory_id=memory.id,
        location_text=payload.location_text.strip(),
        place_id=payload.place_id,
        recorded_at=recorded_at,
        confidence=payload.confidence,
        status=ObjectLocationStatus.CURRENT,
    )
    db.add(location)
    db.commit()
    db.refresh(location)
    return location


@router.get("/{object_id}/location", response_model=ObjectLocationRead)
def current_object_location(
    object_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> ObjectLocation:
    location = db.scalar(
        select(ObjectLocation)
        .where(
            ObjectLocation.object_id == object_id,
            ObjectLocation.user_id == user_id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
        )
        .order_by(ObjectLocation.recorded_at.desc())
        .limit(1)
    )
    if location is None:
        raise HTTPException(status_code=404, detail="OBJECT_LOCATION_NOT_FOUND")
    return location


@router.post("/{object_id}/location/stale", response_model=ObjectLocationRead)
def mark_object_location_stale(
    object_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> ObjectLocation:
    location = db.scalar(
        select(ObjectLocation)
        .where(
            ObjectLocation.object_id == object_id,
            ObjectLocation.user_id == user_id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
        )
        .order_by(ObjectLocation.recorded_at.desc())
        .limit(1)
    )
    if location is None:
        raise HTTPException(status_code=404, detail="OBJECT_LOCATION_NOT_FOUND")

    location.status = ObjectLocationStatus.STALE
    db.commit()
    db.refresh(location)
    return location
