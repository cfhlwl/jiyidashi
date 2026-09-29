from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class RetrievalSurface(StrEnum):
    MEMORY_QUERY = "MEMORY_QUERY"
    STRUCTURED_RETRIEVAL = "STRUCTURED_RETRIEVAL"
    MEMORY_RAG = "MEMORY_RAG"


class RetrievalOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    NO_EVIDENCE = "NO_EVIDENCE"
    FAILED = "FAILED"


class ProductActivity(StrEnum):
    MEMORY_CREATE = "MEMORY_CREATE"
    MEMORY_QUERY = "MEMORY_QUERY"
    TIMELINE = "TIMELINE"
    TIMELINE_EVENTS = "TIMELINE_EVENTS"
    MEDIA_UPLOAD_RESERVED = "MEDIA_UPLOAD_RESERVED"
    MEDIA_UPLOAD_COMPLETED = "MEDIA_UPLOAD_COMPLETED"


class RetrievalAnalyticsAttempt(Base):
    __tablename__ = "retrieval_analytics_attempts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "operation_id",
            "surface",
            name="uq_retrieval_analytics_user_operation_surface",
        ),
        CheckConstraint(
            "result_count >= 0 AND result_count <= 10000",
            name="ck_retrieval_analytics_result_count",
        ),
        CheckConstraint(
            "answerable_count >= 0 AND answerable_count <= 10000",
            name="ck_retrieval_analytics_answerable_count",
        ),
        Index(
            "ix_retrieval_analytics_occurred",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    operation_id: Mapped[UUID] = mapped_column(nullable=False)
    surface: Mapped[RetrievalSurface] = mapped_column(
        Enum(RetrievalSurface, native_enum=False),
        nullable=False,
    )
    outcome: Mapped[RetrievalOutcome] = mapped_column(
        Enum(RetrievalOutcome, native_enum=False),
        nullable=False,
        index=True,
    )
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answerable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )


class ProductActiveDay(Base):
    __tablename__ = "product_active_days"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "activity_date_utc",
            name="uq_product_active_days_user_date",
        ),
        Index("ix_product_active_days_date", "activity_date_utc"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    activity_date_utc: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
