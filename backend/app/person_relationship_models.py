from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
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


class PersonRelationshipKind(StrEnum):
    FAMILY = "FAMILY"
    FRIEND = "FRIEND"
    COLLEAGUE = "COLLEAGUE"
    CLASSMATE = "CLASSMATE"
    OTHER = "OTHER"


class PersonRelationship(Base):
    __tablename__ = "person_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["person_low_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_relationships_low_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["person_high_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_relationships_high_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "person_low_id <> person_high_id",
            name="ck_person_relationships_no_self_edge",
        ),
        CheckConstraint(
            "person_low_id < person_high_id",
            name="ck_person_relationships_canonical_order",
        ),
        UniqueConstraint(
            "user_id",
            "person_low_id",
            "person_high_id",
            name="uq_person_relationships_owner_pair",
        ),
        Index(
            "ix_person_relationships_user_low",
            "user_id",
            "person_low_id",
        ),
        Index(
            "ix_person_relationships_user_high",
            "user_id",
            "person_high_id",
        ),
        Index(
            "ix_person_relationships_user_kind",
            "user_id",
            "relationship_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    person_low_id: Mapped[UUID] = mapped_column(index=True)
    person_high_id: Mapped[UUID] = mapped_column(index=True)
    relationship_kind: Mapped[PersonRelationshipKind] = mapped_column(
        Enum(PersonRelationshipKind, native_enum=False)
    )
    custom_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
