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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class PersonMemoryRelationKind(StrEnum):
    RELATED = "RELATED"
    MET = "MET"


class PersonMemoryLink(Base):
    __tablename__ = "person_memory_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["person_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_memory_links_person_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["memory_id", "user_id"],
            ["memories.id", "memories.user_id"],
            name="fk_person_memory_links_memory_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "person_id",
            "memory_id",
            name="uq_person_memory_links_person_memory",
        ),
        Index(
            "ix_person_memory_links_user_person",
            "user_id",
            "person_id",
        ),
        Index(
            "ix_person_memory_links_user_relation",
            "user_id",
            "relation_kind",
        ),
        Index(
            "ix_person_memory_links_user_memory",
            "user_id",
            "memory_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    person_id: Mapped[UUID] = mapped_column(index=True)
    memory_id: Mapped[UUID] = mapped_column(index=True)
    relation_kind: Mapped[PersonMemoryRelationKind] = mapped_column(
        Enum(PersonMemoryRelationKind, native_enum=False)
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
