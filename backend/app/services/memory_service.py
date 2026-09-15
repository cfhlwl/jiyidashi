from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory, MemorySource, SourceType
from app.schemas import MemoryCreate


def create_memory(
    db: Session,
    user_id: UUID,
    payload: MemoryCreate,
) -> Memory:
    memory = Memory(
        user_id=user_id,
        memory_type=payload.memory_type,
        title=payload.title,
        content=payload.content.strip(),
        occurred_at=payload.occurred_at or datetime.now(UTC),
        source_type=payload.source_type,
        confidence=payload.confidence,
        place_id=payload.place_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        is_confirmed=payload.is_confirmed,
        metadata_json=payload.metadata,
    )
    db.add(memory)
    db.flush()

    # Every user-provided memory gets at least one evidence row.
    if payload.source_type in {
        SourceType.USER_TEXT,
        SourceType.USER_VOICE,
        SourceType.USER_PHOTO,
    }:
        db.add(
            MemorySource(
                memory_id=memory.id,
                source_type=payload.source_type,
                raw_text=memory.content,
                confidence=payload.confidence,
            )
        )

    # Transaction ownership stays with the API/use-case layer so compound
    # operations (for example object location + memory evidence) are atomic.
    return memory


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
