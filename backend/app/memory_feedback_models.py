"""Server-owned audit model for explicit Memory feedback."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class MemoryFeedbackAction(StrEnum):
    CONFIRM = "CONFIRM"
    CORRECT = "CORRECT"
    DELETE = "DELETE"


class MemoryFeedback(Base):
    __tablename__ = "memory_feedbacks"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "client_uuid",
            name="uq_memory_feedbacks_user_client_uuid",
        ),
        UniqueConstraint(
            "user_id",
            "memory_id",
            "memory_revision",
            "action",
            name="uq_memory_feedbacks_revision_action",
        ),
        Index("ix_memory_feedbacks_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"),
        index=True,
    )
    client_uuid: Mapped[UUID] = mapped_column()
    memory_revision: Mapped[int] = mapped_column(Integer)
    result_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
