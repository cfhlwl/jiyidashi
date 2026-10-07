from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
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


class MaintenanceJobType(StrEnum):
    DATA_DELETE = "DATA_DELETE"
    ACCOUNT_DELETE = "ACCOUNT_DELETE"
    MEDIA_PENDING_CLEANUP = "MEDIA_PENDING_CLEANUP"
    SECURITY_ALERT_DELIVERY = "SECURITY_ALERT_DELIVERY"
    ANALYTICS_RETENTION = "ANALYTICS_RETENTION"
    LOCATION_RETENTION = "LOCATION_RETENTION"
    EXPORT = "EXPORT"
    NOTIFICATION_FANOUT = "NOTIFICATION_FANOUT"
    NOTIFICATION_DELIVERY = "NOTIFICATION_DELIVERY"


class MaintenanceJobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MaintenanceJob(Base):
    """Durable PostgreSQL-authoritative maintenance work item.

    Payload/resource identity is immutable after enqueue. Claim/lease fields are the
    only execution ownership authority; an in-process lock is never sufficient.
    """

    __tablename__ = "maintenance_jobs"
    __table_args__ = (
        UniqueConstraint(
            "job_type",
            "dedupe_key",
            name="uq_maintenance_jobs_type_dedupe",
        ),
        CheckConstraint(
            "job_type IN ('DATA_DELETE', 'ACCOUNT_DELETE', 'MEDIA_PENDING_CLEANUP', "
            "'SECURITY_ALERT_DELIVERY', 'ANALYTICS_RETENTION', 'LOCATION_RETENTION', "
            "'EXPORT', 'NOTIFICATION_FANOUT', 'NOTIFICATION_DELIVERY')",
            name="ck_maintenance_jobs_known_type",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_maintenance_jobs_attempt_count",
        ),
        CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 100",
            name="ck_maintenance_jobs_max_attempts",
        ),
        Index(
            "ix_maintenance_jobs_due",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index(
            "ix_maintenance_jobs_lease",
            "status",
            "lease_expires_at",
        ),
        Index(
            "ix_maintenance_jobs_owner_created",
            "owner_user_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resource_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(
        String(32),
        default=MaintenanceJobStatus.PENDING.value,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        nullable=False,
    )

    claimed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    claim_token: Mapped[UUID | None] = mapped_column(nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
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
