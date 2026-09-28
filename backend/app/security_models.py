from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class SecuritySignalCode(StrEnum):
    AUTH_RATE_LIMIT_TRIGGERED = "AUTH_RATE_LIMIT_TRIGGERED"
    AUTH_LOGIN_FAILURE_BURST = "AUTH_LOGIN_FAILURE_BURST"
    FAMILY_SENSITIVE_READ_DENIED = "FAMILY_SENSITIVE_READ_DENIED"
    FAMILY_SENSITIVE_DOWNLOAD_DENIED = "FAMILY_SENSITIVE_DOWNLOAD_DENIED"
    FAMILY_SENSITIVE_ACCESS_BURST = "FAMILY_SENSITIVE_ACCESS_BURST"
    DESTRUCTIVE_OPERATION_FAILURE = "DESTRUCTIVE_OPERATION_FAILURE"
    DESTRUCTIVE_OPERATION_RETRY_BURST = "DESTRUCTIVE_OPERATION_RETRY_BURST"
    STORAGE_CAPABILITY_FAILURE_BURST = "STORAGE_CAPABILITY_FAILURE_BURST"


class SecuritySeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityAlertDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


class SecuritySignalWindow(Base):
    """Durable anomaly window shared by all production workers."""

    __tablename__ = "security_signal_windows"
    __table_args__ = (
        UniqueConstraint(
            "rule_code",
            "correlation_digest",
            "scope",
            "window_started_at",
            name="uq_security_signal_window_identity",
        ),
        CheckConstraint("signal_count >= 0", name="ck_security_signal_window_count"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    rule_code: Mapped[str] = mapped_column(String(64), index=True)
    correlation_digest: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64))
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    window_seconds: Mapped[int] = mapped_column(Integer)
    signal_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SecurityAlert(Base):
    """One logical operator alert per reviewed dedupe/cooldown identity."""

    __tablename__ = "security_alerts"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_security_alerts_dedupe_key"),
        CheckConstraint("signal_count > 0", name="ck_security_alerts_signal_count"),
        CheckConstraint("delivery_attempts >= 0", name="ck_security_alerts_delivery_attempts"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_code: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    correlation_digest: Mapped[str] = mapped_column(String(64))
    scope: Mapped[str] = mapped_column(String(64))
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_seconds: Mapped[int] = mapped_column(Integer)
    signal_count: Mapped[int] = mapped_column(Integer)
    delivery_status: Mapped[str] = mapped_column(
        String(32),
        default=SecurityAlertDeliveryStatus.PENDING.value,
        index=True,
    )
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
