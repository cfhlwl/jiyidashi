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


class LifeStageKind(StrEnum):
    WORK = "WORK"
    EDUCATION = "EDUCATION"
    FAMILY = "FAMILY"
    RESIDENCE = "RESIDENCE"
    TRAVEL = "TRAVEL"
    OTHER = "OTHER"


class LifeStage(Base):
    __tablename__ = "life_stages"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_life_stages_id_user_id"),
        Index("ix_life_stages_user_started", "user_id", "started_at"),
        Index("ix_life_stages_user_kind", "user_id", "stage_kind"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    stage_kind: Mapped[LifeStageKind] = mapped_column(
        Enum(LifeStageKind, native_enum=False)
    )
    title: Mapped[str] = mapped_column(String(240))
    custom_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class LifeStageEventLink(Base):
    __tablename__ = "life_stage_event_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["life_stage_id", "user_id"],
            ["life_stages.id", "life_stages.user_id"],
            name="fk_life_stage_event_links_stage_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["life_event_id", "user_id"],
            ["life_events.id", "life_events.user_id"],
            name="fk_life_stage_event_links_event_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "life_stage_id",
            "life_event_id",
            name="uq_life_stage_event_links_stage_event",
        ),
        Index(
            "ix_life_stage_event_links_user_stage",
            "user_id",
            "life_stage_id",
        ),
        Index(
            "ix_life_stage_event_links_user_event",
            "user_id",
            "life_event_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    life_stage_id: Mapped[UUID] = mapped_column(index=True)
    life_event_id: Mapped[UUID] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
