from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.notification_models import (
    NotificationAudienceType,
    NotificationCampaignStatus,
    NotificationCategory,
    NotificationRouteIntent,
    NotificationSourceType,
    NotificationTargetPlatform,
    PushPlatform,
    PushProvider,
)

MAX_NOTIFICATION_TARGET_IDS = 500


class DevicePushRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_uuid: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    platform: PushPlatform
    provider: PushProvider
    push_token: str = Field(min_length=16, max_length=4096)
    app_version: str | None = Field(default=None, min_length=1, max_length=64)
    os_version: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_platform_provider(self):
        allowed = {
            PushPlatform.IOS: {PushProvider.APNS, PushProvider.TEST},
            PushPlatform.ANDROID: {
                PushProvider.FCM,
                PushProvider.HMS,
                PushProvider.TEST,
            },
        }
        if self.provider not in allowed[self.platform]:
            raise ValueError("provider is not valid for platform")
        if self.push_token != self.push_token.strip():
            raise ValueError("push_token must not contain surrounding whitespace")
        return self


class DevicePushStateRead(BaseModel):
    id: UUID
    client_uuid: str
    platform: PushPlatform
    provider: PushProvider | None
    push_enabled: bool
    push_token_updated_at: datetime | None
    push_invalidated_at: datetime | None
    app_version: str | None
    os_version: str | None
    last_active_at: datetime | None


class NotificationMessageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: NotificationCategory
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=1000)
    route_intent: NotificationRouteIntent
    route_resource_id: UUID | None = None
    source_type: NotificationSourceType
    source_id: UUID | None = None
    expires_at: datetime | None = None


class NotificationTargetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: NotificationTargetPlatform
    audience: NotificationAudienceType
    user_ids: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_NOTIFICATION_TARGET_IDS,
    )
    device_ids: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_NOTIFICATION_TARGET_IDS,
    )

    @model_validator(mode="after")
    def validate_target_shape(self):
        self.user_ids = list(dict.fromkeys(self.user_ids))
        self.device_ids = list(dict.fromkeys(self.device_ids))
        if self.audience == NotificationAudienceType.ALL_ELIGIBLE_DEVICES:
            if self.user_ids or self.device_ids:
                raise ValueError("ALL_ELIGIBLE_DEVICES cannot include explicit ids")
        elif self.audience == NotificationAudienceType.USER_IDS:
            if not self.user_ids or self.device_ids:
                raise ValueError("USER_IDS requires only user_ids")
        elif self.audience == NotificationAudienceType.DEVICE_IDS:
            if not self.device_ids or self.user_ids:
                raise ValueError("DEVICE_IDS requires only device_ids")
        return self


class AdminNotificationCampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: NotificationMessageDraft
    target: NotificationTargetSpec


class NotificationEligibleCounts(BaseModel):
    total: int
    ios: int
    android: int


class AdminNotificationCampaignPreview(BaseModel):
    campaign_id: UUID
    revision: int
    eligible: NotificationEligibleCounts
    confirmation_token: str


class AdminNotificationCampaignSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    confirmation_token: str = Field(min_length=16, max_length=128)
    send_at: datetime | None = None


class AdminNotificationCampaignCancel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class NotificationDeliveryCounts(BaseModel):
    pending: int = 0
    running: int = 0
    accepted: int = 0
    retry_wait: int = 0
    terminal_failure: int = 0
    cancelled: int = 0
    expired: int = 0


class AdminNotificationCampaignRead(BaseModel):
    id: UUID
    message_id: UUID
    category: NotificationCategory
    title: str
    body: str
    route_intent: NotificationRouteIntent
    route_resource_id: UUID | None
    source_type: NotificationSourceType
    source_id: UUID | None
    target_platform: NotificationTargetPlatform
    audience_type: NotificationAudienceType
    status: NotificationCampaignStatus
    revision: int
    send_at: datetime | None
    audience_cutoff_at: datetime | None
    fanout_completed_at: datetime | None
    submitted_at: datetime | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    eligible_preview: NotificationEligibleCounts
    delivery_counts: NotificationDeliveryCounts
