from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class DataDeletionStatus(StrEnum):
    STORAGE_PENDING = "STORAGE_PENDING"
    WAITING_STORAGE_EXPIRY = "WAITING_STORAGE_EXPIRY"
    WAITING_STORAGE_QUIET = "WAITING_STORAGE_QUIET"
    STORAGE_FAILED = "STORAGE_FAILED"
    DB_PENDING = "DB_PENDING"
    DB_FAILED = "DB_FAILED"
    COMPLETED = "COMPLETED"


class DataDeletionOperation(Base):
    """Durable receipt/state machine for a user-data deletion request.

    The User/AuthIdentity account survives S1-021. This row is therefore retained as a
    minimal idempotency receipt; object keys are removed once cleanup completes.
    """

    __tablename__ = "data_deletion_operations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "request_id",
            name="uq_data_deletion_operations_user_request",
        ),
        Index(
            "uq_data_deletion_operations_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status != 'COMPLETED'"),
            sqlite_where=text("status != 'COMPLETED'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[DataDeletionStatus] = mapped_column(
        Enum(DataDeletionStatus, native_enum=False),
        default=DataDeletionStatus.STORAGE_PENDING,
    )
    storage_capability_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    storage_quiet_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    deleted_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DataDeletionObject(Base):
    """Object-storage obligation captured before destructive DB cleanup."""

    __tablename__ = "data_deletion_objects"
    __table_args__ = (
        UniqueConstraint(
            "deletion_id",
            "object_key",
            name="uq_data_deletion_objects_deletion_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    deletion_id: Mapped[UUID] = mapped_column(
        ForeignKey("data_deletion_operations.id", ondelete="CASCADE"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
