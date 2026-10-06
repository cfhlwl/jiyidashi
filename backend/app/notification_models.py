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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


class PushPlatform(StrEnum):
    IOS = "IOS"
    ANDROID = "ANDROID"


class PushProvider(StrEnum):
    # TEST is deterministic and is never enabled as a production network provider.
    TEST = "TEST"
    # Live provider adapters are intentionally deferred to NOTIFY-001B.
    APNS = "APNS"
    FCM = "FCM"
    HMS = "HMS"


class NotificationCategory(StrEnum):
    REMINDER = "REMINDER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"
    APP_UPDATE = "APP_UPDATE"
    EXPORT_COMPLETE = "EXPORT_COMPLETE"
    FAMILY = "FAMILY"


class NotificationSourceType(StrEnum):
    REMINDER = "REMINDER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"
    APP_UPDATE = "APP_UPDATE"
    EXPORT_COMPLETE = "EXPORT_COMPLETE"
    FAMILY = "FAMILY"


class NotificationRouteIntent(StrEnum):
    HOME = "HOME"
    REMINDER = "REMINDER"
    MEMORY = "MEMORY"
    APP_UPDATE = "APP_UPDATE"
    FAMILY = "FAMILY"
    EXPORT = "EXPORT"


class NotificationTargetPlatform(StrEnum):
    ALL = "ALL"
    IOS = "IOS"
    ANDROID = "ANDROID"


class NotificationAudienceType(StrEnum):
    ALL_ELIGIBLE_DEVICES = "ALL_ELIGIBLE_DEVICES"
    USER_IDS = "USER_IDS"
    DEVICE_IDS = "DEVICE_IDS"


class NotificationCampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    FANOUT = "FANOUT"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class NotificationDeliveryStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    ACCEPTED = "ACCEPTED"
    RETRY_WAIT = "RETRY_WAIT"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


_CATEGORY_VALUES = ",".join(f"'{item.value}'" for item in NotificationCategory)
_SOURCE_VALUES = ",".join(f"'{item.value}'" for item in NotificationSourceType)
_ROUTE_VALUES = ",".join(f"'{item.value}'" for item in NotificationRouteIntent)
_TARGET_PLATFORM_VALUES = ",".join(
    f"'{item.value}'" for item in NotificationTargetPlatform
)
_AUDIENCE_VALUES = ",".join(f"'{item.value}'" for item in NotificationAudienceType)
_CAMPAIGN_STATUS_VALUES = ",".join(
    f"'{item.value}'" for item in NotificationCampaignStatus
)
_DELIVERY_STATUS_VALUES = ",".join(
    f"'{item.value}'" for item in NotificationDeliveryStatus
)


class NotificationMessage(Base):
    """Provider-neutral immutable notification content.

    Provider-specific request bodies never become canonical message state.
    """

    __tablename__ = "notification_messages"
    __table_args__ = (
        CheckConstraint(
            f"category IN ({_CATEGORY_VALUES})",
            name="ck_notification_messages_category",
        ),
        CheckConstraint(
            f"source_type IN ({_SOURCE_VALUES})",
            name="ck_notification_messages_source_type",
        ),
        CheckConstraint(
            f"route_intent IN ({_ROUTE_VALUES})",
            name="ck_notification_messages_route",
        ),
        CheckConstraint(
            "payload_version >= 1 AND payload_version <= 100",
            name="ck_notification_messages_payload_version",
        ),
        Index(
            "ix_notification_messages_source",
            "source_type",
            "source_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    route_intent: Mapped[str] = mapped_column(String(32), nullable=False)
    route_resource_id: Mapped[UUID | None] = mapped_column(nullable=True)
    payload_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    safe_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NotificationCampaign(Base):
    """Durable targeting, scheduling and fan-out progress authority."""

    __tablename__ = "notification_campaigns"
    __table_args__ = (
        CheckConstraint(
            f"target_platform IN ({_TARGET_PLATFORM_VALUES})",
            name="ck_notification_campaigns_platform",
        ),
        CheckConstraint(
            f"audience_type IN ({_AUDIENCE_VALUES})",
            name="ck_notification_campaigns_audience",
        ),
        CheckConstraint(
            f"status IN ({_CAMPAIGN_STATUS_VALUES})",
            name="ck_notification_campaigns_status",
        ),
        CheckConstraint(
            "revision >= 0",
            name="ck_notification_campaigns_revision",
        ),
        Index(
            "ix_notification_campaigns_due",
            "status",
            "send_at",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_platform: Mapped[str] = mapped_column(String(16), nullable=False)
    audience_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=NotificationCampaignStatus.DRAFT.value,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audience_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fanout_cursor_device_id: Mapped[UUID | None] = mapped_column(nullable=True)
    fanout_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class NotificationCampaignTarget(Base):
    """Bounded normalized USER_IDS / DEVICE_IDS targeting rows.

    Foreign keys make account/device removal automatically retire stale targets.
    ALL_ELIGIBLE_DEVICES campaigns have no rows here.
    """

    __tablename__ = "notification_campaign_targets"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND device_id IS NULL) OR "
            "(user_id IS NULL AND device_id IS NOT NULL)",
            name="ck_notification_campaign_targets_exactly_one",
        ),
        UniqueConstraint(
            "campaign_id",
            "user_id",
            name="uq_notification_campaign_targets_user",
        ),
        UniqueConstraint(
            "campaign_id",
            "device_id",
            name="uq_notification_campaign_targets_device",
        ),
        Index(
            "ix_notification_campaign_targets_campaign",
            "campaign_id",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class NotificationDelivery(Base):
    """One logical campaign/device delivery with stale-attempt fencing."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "device_id",
            name="uq_notification_deliveries_campaign_device",
        ),
        CheckConstraint(
            f"status IN ({_DELIVERY_STATUS_VALUES})",
            name="ck_notification_deliveries_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_notification_deliveries_attempt_count",
        ),
        CheckConstraint(
            "revision >= 0",
            name="ck_notification_deliveries_revision",
        ),
        Index(
            "ix_notification_deliveries_campaign_status",
            "campaign_id",
            "status",
        ),
        Index(
            "ix_notification_deliveries_owner_created",
            "owner_user_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform_snapshot: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    token_digest_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=NotificationDeliveryStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_token: Mapped[UUID | None] = mapped_column(nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )
