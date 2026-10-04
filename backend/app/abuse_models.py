from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class ConcurrencyGuard(Base):
    """Canonical serialization row for one concurrency scope."""

    __tablename__ = "concurrency_guards"

    scope_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class WorkPermit(Base):
    """Durable, expiring permit shared by all application workers."""

    __tablename__ = "work_permits"
    __table_args__ = (
        Index("ix_work_permits_service_expires", "service_class", "expires_at"),
        Index("ix_work_permits_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    service_class: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
