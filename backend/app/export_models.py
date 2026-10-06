from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class UserExportStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class UserExportJob(Base):
    """Owner-scoped public export authority.

    MaintenanceJob is only the execution queue. This row is the durable user-visible
    state and the sole authority for artifact publication/download.
    """

    __tablename__ = "user_export_jobs"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_user_export_jobs_owner_idempotency",
        ),
        UniqueConstraint(
            "artifact_object_key",
            name="uq_user_export_jobs_artifact_object_key",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', "
            "'CANCELLED', 'EXPIRED')",
            name="ck_user_export_jobs_known_status",
        ),
        CheckConstraint(
            "revision >= 0",
            name="ck_user_export_jobs_revision",
        ),
        CheckConstraint(
            "artifact_size_bytes IS NULL OR artifact_size_bytes >= 0",
            name="ck_user_export_jobs_artifact_size",
        ),
        Index(
            "ix_user_export_jobs_owner_requested",
            "owner_user_id",
            "requested_at",
        ),
        Index(
            "ix_user_export_jobs_status_expires",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default=UserExportStatus.PENDING.value,
        nullable=False,
    )
    format_version: Mapped[str] = mapped_column(
        String(64),
        default="jiyidashi.user-export.v1",
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    artifact_object_key: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    artifact_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
