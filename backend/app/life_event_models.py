from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class LifeEventKind(StrEnum):
    TRAVEL = "TRAVEL"
    MEDICAL = "MEDICAL"
    GATHERING = "GATHERING"
    WORK = "WORK"
    EDUCATION = "EDUCATION"
    FAMILY = "FAMILY"
    OTHER = "OTHER"


class LifeEvent(Base):
    __tablename__ = "life_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["place_id", "user_id"],
            ["places.id", "places.user_id"],
            name="fk_life_events_place_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "user_id", name="uq_life_events_id_user_id"),
        Index("ix_life_events_user_started", "user_id", "started_at"),
        Index("ix_life_events_user_kind", "user_id", "event_kind"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    event_kind: Mapped[LifeEventKind] = mapped_column(
        Enum(LifeEventKind, native_enum=False)
    )
    title: Mapped[str] = mapped_column(String(240))
    custom_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    place_id: Mapped[UUID | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class LifeEventMemoryLink(Base):
    __tablename__ = "life_event_memory_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["life_event_id", "user_id"],
            ["life_events.id", "life_events.user_id"],
            name="fk_life_event_memory_links_event_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["memory_id", "user_id"],
            ["memories.id", "memories.user_id"],
            name="fk_life_event_memory_links_memory_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "life_event_id",
            "memory_id",
            name="uq_life_event_memory_links_event_memory",
        ),
        Index(
            "ix_life_event_memory_links_user_event",
            "user_id",
            "life_event_id",
        ),
        Index(
            "ix_life_event_memory_links_user_memory",
            "user_id",
            "memory_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    life_event_id: Mapped[UUID] = mapped_column(index=True)
    memory_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
