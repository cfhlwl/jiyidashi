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
    Reminder,
    ReminderStatus,
    SourceType,
)
from app.schemas import MemoryCreate
from app.services.embedding_service import invalidate_memory_embedding


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
    *,
    for_update: bool = False,
) -> Memory | None:
    query = select(Memory).where(
        Memory.id == memory_id,
        Memory.user_id == user_id,
        Memory.is_deleted.is_(False),
    )
    if for_update:
        # [人工注释][S1-025] 删除 Memory 与创建 Reminder 共用这一行锁，
        # 保证不会在软删除提交后留下一个新的 PENDING reminder。
        query = query.with_for_update()
    return db.scalar(query)


def soft_delete_memory(db: Session, memory: Memory) -> None:
    memory.is_deleted = True
    # A deleted Memory must not retain a nearest-neighbor candidate. The trusted
    # owner-scoped Memory lock is already held by the caller before invalidation.
    invalidate_memory_embedding(db, memory.id)
    db.execute(
        update(ObjectLocation)
        .where(
            ObjectLocation.memory_id == memory.id,
            ObjectLocation.status == ObjectLocationStatus.CURRENT,
        )
        .values(status=ObjectLocationStatus.STALE)
    )
    # [人工注释][S1-025] 删除 backing Memory 后，尚未触发的提醒不能继续作为有效任务存在。
    # 已完成/已取消历史保持不变，便于用户理解过去发生过什么。
    db.execute(
        update(Reminder)
        .where(
            Reminder.memory_id == memory.id,
            Reminder.status == ReminderStatus.PENDING,
        )
        .values(status=ReminderStatus.CANCELLED)
    )
    # 软删除不会触发数据库 FK 的 ON DELETE SET NULL，因此这里主动把所有 reminder
    # 与已删除 Memory 脱钩；DONE/CANCELLED 历史状态保留，但不再悬挂 deleted memory_id。
    db.execute(
        update(Reminder)
        .where(Reminder.memory_id == memory.id)
        .values(memory_id=None)
    )
