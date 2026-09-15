from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Memory,
    MemorySource,
    MemoryType,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
)
from app.schemas import MemoryCreate


@dataclass(frozen=True)
class TrustedMemoryWrite:
    """Internal-only trusted write contract.

    Public API schemas intentionally do not expose confidence or confirmation flags.
    """

    memory_type: MemoryType
    content: str
    source_type: SourceType
    occurred_at: datetime
    confidence: float
    is_confirmed: bool
    title: str | None = None
    place_id: UUID | None = None
    latitude: float | None = None
    longitude: float | None = None
    metadata: dict = field(default_factory=dict)
    source_id: str | None = None
    evidence_text: str | None = None


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def create_trusted_memory(
    db: Session,
    user_id: UUID,
    write: TrustedMemoryWrite,
) -> Memory:
    is_ai = write.source_type == SourceType.AI_INFERENCE
    confirmed = False if is_ai else write.is_confirmed
    confidence = min(write.confidence, 0.5) if is_ai else write.confidence

    memory = Memory(
        user_id=user_id,
        memory_type=write.memory_type,
        title=write.title,
        content=write.content.strip(),
        occurred_at=ensure_utc(write.occurred_at),
        source_type=write.source_type,
        confidence=confidence,
        place_id=write.place_id,
        latitude=write.latitude,
        longitude=write.longitude,
        is_confirmed=confirmed,
        metadata_json=write.metadata,
    )
    db.add(memory)
    db.flush()

    db.add(
        MemorySource(
            memory_id=memory.id,
            source_type=write.source_type,
            source_id=write.source_id,
            raw_text=write.evidence_text or memory.content,
            confidence=confidence,
        )
    )
    return memory


def create_user_memory(
    db: Session,
    user_id: UUID,
    payload: MemoryCreate,
) -> Memory:
    source_type = payload.capture_source.to_source_type()
    return create_trusted_memory(
        db,
        user_id,
        TrustedMemoryWrite(
            memory_type=payload.memory_type,
            title=payload.title,
            content=payload.content,
            occurred_at=payload.occurred_at or datetime.now(UTC),
            source_type=source_type,
            confidence=1.0,
            is_confirmed=True,
            place_id=payload.place_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            metadata=payload.metadata,
            evidence_text=payload.content,
        ),
    )


def get_memory_for_user(
    db: Session,
    user_id: UUID,
    memory_id: UUID,
) -> Memory | None:
    return db.scalar(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.user_id == user_id,
            Memory.is_deleted.is_(False),
        )
    )


def soft_delete_memory(db: Session, memory: Memory) -> None:
    memory.is_deleted = True
    db.execute(
        update(ObjectLocation)
        .where(
            ObjectLocation.memory_id == memory.id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
        )
        .values(status=ObjectLocationStatus.STALE)
    )
