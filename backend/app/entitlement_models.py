from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
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


class PlanCode(StrEnum):
    FREE = "FREE"
    PERSONAL = "PERSONAL"
    FAMILY = "FAMILY"
    PREMIUM = "PREMIUM"
    LEGACY_FULL = "LEGACY_FULL"


class CapabilityCode(StrEnum):
    CORE_MEMORY = "CORE_MEMORY"
    BASIC_SEARCH = "BASIC_SEARCH"
    EXTENDED_HISTORY = "EXTENDED_HISTORY"
    IMAGE_MEDIA = "IMAGE_MEDIA"
    VOICE_MEDIA = "VOICE_MEDIA"
    AI_INFERENCE = "AI_INFERENCE"
    FAMILY_FEATURES = "FAMILY_FEATURES"
    ELDER_MODE = "ELDER_MODE"
    ARRIVAL_REMINDER = "ARRIVAL_REMINDER"
    ANNUAL_MEMOIR = "ANNUAL_MEMOIR"
    LIFE_MEMOIR = "LIFE_MEMOIR"
    LONG_TERM_REASONING = "LONG_TERM_REASONING"


class QuotaDimension(StrEnum):
    STORAGE_BYTES = "STORAGE_BYTES"
    AI_PROVIDER_REQUESTS = "AI_PROVIDER_REQUESTS"
    AI_INPUT_TOKENS = "AI_INPUT_TOKENS"
    AI_OUTPUT_TOKENS = "AI_OUTPUT_TOKENS"


class UserEntitlement(Base):
    __tablename__ = "user_entitlements"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="ck_user_entitlements_revision"),
        CheckConstraint(
            "plan_code IN ('FREE','PERSONAL','FAMILY','PREMIUM','LEGACY_FULL')",
            name="ck_user_entitlements_plan_code",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at",
            name="ck_user_entitlements_effective_range",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    plan_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIQuotaPeriod(Base):
    __tablename__ = "ai_quota_periods"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "period_start",
            "period_end",
            name="uq_ai_quota_period_user_range",
        ),
        CheckConstraint("provider_requests >= 0", name="ck_ai_quota_provider_requests"),
        CheckConstraint("input_tokens >= 0", name="ck_ai_quota_input_tokens"),
        CheckConstraint("output_tokens >= 0", name="ck_ai_quota_output_tokens"),
        CheckConstraint(
            "period_end > period_start",
            name="ck_ai_quota_period_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "gateway_request_id",
            name="uq_ai_usage_user_gateway_request",
        ),
        Index(
            "ix_ai_usage_user_created",
            "user_id",
            "created_at",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_usage_input_tokens",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_usage_output_tokens",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    gateway_request_id: Mapped[UUID] = mapped_column(nullable=False)
    period_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_quota_periods.id", ondelete="CASCADE"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_invocation_reserved: Mapped[bool] = mapped_column(nullable=False, default=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
