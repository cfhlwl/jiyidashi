from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictInt, model_validator

from app.admin_models import AdminRole

MAX_QUOTA_VALUE = 9_223_372_036_854_775_807


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AdminSessionRead(BaseModel):
    admin_id: UUID
    email: str
    display_name: str
    role: AdminRole
    expires_at: datetime


class AdminMessage(BaseModel):
    message: str


class AdminAccountRead(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: AdminRole
    disabled: bool
    revision: int
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=12, max_length=128)
    role: AdminRole
    confirmation: str = Field(min_length=1, max_length=64)


class AdminAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: AdminRole | None = None
    disabled: bool | None = None
    confirmation: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set.intersection({"display_name", "role", "disabled"}):
            raise ValueError("at least one admin-account change is required")
        return self


class AdminPasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    new_password: str = Field(min_length=12, max_length=128)
    confirmation: str = Field(min_length=1, max_length=64)


class AdminQuotaPlanRead(BaseModel):
    plan_code: str
    revision: int
    storage_bytes: int
    ai_provider_requests: int
    ai_input_tokens: int
    ai_output_tokens: int
    updated_at: datetime


class AdminQuotaCatalogRead(BaseModel):
    initialized: bool
    plans: list[AdminQuotaPlanRead]


class AdminQuotaPlanWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_code: str
    expected_revision: int | None = Field(default=None, ge=0)
    storage_bytes: StrictInt = Field(ge=0, le=MAX_QUOTA_VALUE)
    ai_provider_requests: StrictInt = Field(ge=0, le=MAX_QUOTA_VALUE)
    ai_input_tokens: StrictInt = Field(ge=0, le=MAX_QUOTA_VALUE)
    ai_output_tokens: StrictInt = Field(ge=0, le=MAX_QUOTA_VALUE)


class AdminQuotaCatalogWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plans: list[AdminQuotaPlanWrite] = Field(min_length=4, max_length=4)
    confirmation: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_complete_catalog(self):
        expected = {"FREE", "PERSONAL", "FAMILY", "PREMIUM"}
        actual = [row.plan_code for row in self.plans]
        if set(actual) != expected or len(set(actual)) != 4:
            raise ValueError("quota catalog must contain each commercial plan exactly once")
        return self


class AdminEntitlementAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    plan_code: str
    expires_at: datetime | None = None
    confirmation: str = Field(min_length=1, max_length=64)


class AdminAuditRead(BaseModel):
    id: UUID
    actor: str
    role: str
    action: str
    target_type: str
    target: str | None
    result: str
    request_ref: str | None
    metadata: dict
    created_at: datetime


class AdminAuditPage(BaseModel):
    items: list[AdminAuditRead]
    next_cursor: str | None = None


class AdminDashboardOverview(BaseModel):
    registered_users: int
    new_users_today: int
    active_users_today: int
    memories_created_today: int
    successful_retrievals_today: int
    active_account_deletions: int
    pending_data_deletions: int
    security_alerts_needing_attention: int


class AdminServiceStatus(BaseModel):
    key: str
    label: str
    status: str
    detail: str


class AdminDashboardTrendPoint(BaseModel):
    day: date
    active_users: int
    successful_retrievals: int


class AdminDashboardRead(BaseModel):
    overview: AdminDashboardOverview
    services: list[AdminServiceStatus]
    trend: list[AdminDashboardTrendPoint]


class AdminUserListItem(BaseModel):
    id: UUID
    display_name: str
    email: str | None
    created_at: datetime
    last_active_at: datetime | None
    device_count: int
    plan_code: str
    family_role: str | None
    storage_used_bytes: int
    account_deletion_in_progress: bool
    data_deletion_in_progress: bool


class AdminUserPage(BaseModel):
    items: list[AdminUserListItem]
    next_cursor: str | None = None


class AdminUserEntitlementRead(BaseModel):
    plan_code: str
    revision: int
    effective_at: datetime
    expires_at: datetime | None
    storage_used_bytes: int
    storage_limit_bytes: int | None
    ai_requests_used: int
    ai_requests_limit: int | None


class AdminUserDetail(BaseModel):
    user: AdminUserListItem
    entitlement: AdminUserEntitlementRead
    family_id: UUID | None
    data_deletion_status: str | None
    account_deletion_started_at: datetime | None


class AdminFamilyListItem(BaseModel):
    id: UUID
    owner_user_id: UUID
    owner_display_name: str
    owner_email: str | None
    member_count: int
    grant_count: int
    created_at: datetime


class AdminFamilyPage(BaseModel):
    items: list[AdminFamilyListItem]
    next_cursor: str | None = None


class AdminFamilyMemberRead(BaseModel):
    user_id: UUID
    display_name: str
    email: str | None
    role: str
    joined_at: datetime


class AdminFamilyGrantSummary(BaseModel):
    permission_code: str
    grant_count: int


class AdminFamilyDetail(BaseModel):
    family: AdminFamilyListItem
    members: list[AdminFamilyMemberRead]
    grants: list[AdminFamilyGrantSummary]


class AdminDataDeletionItem(BaseModel):
    id: UUID
    user_id: UUID
    user_display_name: str
    user_email: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    storage_wait_until: datetime | None
    retryable: bool
    safe_message: str
    deleted_counts: dict[str, int]


class AdminDataDeletionPage(BaseModel):
    items: list[AdminDataDeletionItem]
    next_cursor: str | None = None


class AdminAccountDeletionItem(BaseModel):
    id: UUID
    user_id: UUID
    user_display_name: str
    user_email: str | None
    created_at: datetime
    updated_at: datetime
    safe_phase: str
    safe_message: str


class AdminAccountDeletionPage(BaseModel):
    items: list[AdminAccountDeletionItem]
    next_cursor: str | None = None


class AdminSecurityAlertItem(BaseModel):
    id: UUID
    severity: str
    category: str
    delivery_status: str
    signal_count: int
    first_seen_at: datetime
    latest_seen_at: datetime
    next_retry_at: datetime | None
    safe_message: str


class AdminSecurityAlertPage(BaseModel):
    items: list[AdminSecurityAlertItem]
    next_cursor: str | None = None


class AdminSettingRead(BaseModel):
    key: str
    label: str
    classification: str
    value: str | int | float | bool | None
    configured: bool | None = None
    help_text: str | None = None


class AdminSettingSectionRead(BaseModel):
    key: str
    title: str
    items: list[AdminSettingRead]


class AdminSystemSettingsRead(BaseModel):
    sections: list[AdminSettingSectionRead]


class AdminSystemHealthRead(BaseModel):
    environment: str
    api_status: str
    database_status: str
    database_schema_status: str
    database_schema_version: str | None
    storage_status: str
    storage_alerts_needing_attention: int
    ai_status: str
    asr_status: str
    embedding_status: str
    ai_requests_current_month: int
    ai_input_tokens_current_month: int
    ai_output_tokens_current_month: int
    app_version: str
    git_sha: str | None
    build_time: str | None
    total_storage_used_bytes: int
