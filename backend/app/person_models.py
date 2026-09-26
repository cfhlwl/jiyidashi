from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Person(Base):
    __tablename__ = "persons"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_persons_id_user_id"),
        Index("ix_persons_user_display_name", "user_id", "display_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(200))
    relationship_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PersonAlias(Base):
    __tablename__ = "person_aliases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["person_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_aliases_person_owner",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "person_id", "normalized_alias", name="uq_person_aliases_person_normalized"
        ),
        Index("ix_person_aliases_user_alias", "user_id", "normalized_alias"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(index=True)
    person_id: Mapped[UUID] = mapped_column(index=True)
    alias: Mapped[str] = mapped_column(String(200))
    normalized_alias: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
