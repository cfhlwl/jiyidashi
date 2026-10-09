from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)

from app.media_models import MediaKind, MediaStatus
from app.models import MemoryType, ObjectLocationStatus, ReminderStatus, SourceType


def _require_timezone_aware_datetime(value: datetime) -> datetime:
    # [人工注释][FND-026] 服务端用于时间顺序判断的显式 recorded_at 必须携带时区。
    # 禁止把客户端本地 naive 时间直接误当成 UTC。
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("recorded_at must include a timezone offset")
    return value


def _require_iana_timezone(value: str) -> str:
    # [人工注释][S1-002] 用户时区必须是可解析的 IANA 名称，防止时间轴在运行期才失败。
    normalized = value.strip()
    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return normalized


TimezoneAwareDateTime = Annotated[datetime, AfterValidator(_require_timezone_aware_datetime)]
TimezoneName = Annotated[
    str,
    Field(min_length=1, max_length=64),
    AfterValidator(_require_iana_timezone),
]
# [人工注释][S1-FIX-005] 资料字段先 strip 再执行长度校验，纯空白输入必须在 schema 层返回 422。
NicknameText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]
LocaleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=32),
]
ReminderTitleText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]
ReminderContentText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]
LocationClientUuid = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=80),
]
PlaceNameText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCaptureSource(StrEnum):
    """Public clients may only declare a user-origin capture channel.

    Trust, confidence and confirmation status are server-owned fields.
    """

    USER_TEXT = "USER_TEXT"
    USER_VOICE = "USER_VOICE"
    USER_PHOTO = "USER_PHOTO"

    def to_source_type(self) -> SourceType:
        return SourceType(self.value)


class EvidenceProvenance(StrEnum):
    ORIGINAL_SOURCE = "ORIGINAL_SOURCE"
    USER_EDIT = "USER_EDIT"


class PlaceDisplayNameSource(StrEnum):
    UNNAMED = "UNNAMED"
    AUTOMATIC = "AUTOMATIC"
    USER = "USER"


class TimelineItemKind(StrEnum):
    MEMORY = "MEMORY"
    VISIT = "VISIT"


class ImageContentType(StrEnum):
    # [人工注释][S1-005] Stage 1 静态图片类型继续沿用已冻结协议。
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    HEIC = "image/heic"
    HEIF = "image/heif"


class AudioContentType(StrEnum):
    # 客户端声明的 MIME 只是候选元数据；READY 前服务端仍会检查真实文件头。
    # Flutter 使用 M4A/MPEG-4 容器；容器通过后仍必须由服务端 ASR 证明音频可用。
    MPEG = "audio/mpeg"
    MP4 = "audio/mp4"


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    nickname: NicknameText
    timezone: TimezoneName = "Asia/Shanghai"
    locale: LocaleText = "zh-CN"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    device_id: str = Field(default="legacy-client", min_length=1, max_length=120)
    client_platform: str | None = Field(default=None, max_length=32)
    device_name: str | None = Field(default=None, max_length=120)


class PhoneOneTapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_token: str = Field(min_length=1, max_length=512)
    request_id: UUID
    device_id: str = Field(min_length=1, max_length=120)
    client_platform: str | None = Field(default=None, max_length=32)
    device_name: str | None = Field(default=None, max_length=120)


class SmsOtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(min_length=1, max_length=32)
    device_id: str = Field(default="legacy-client", min_length=1, max_length=120)
    client_platform: str | None = Field(default=None, max_length=32)
    device_name: str | None = Field(default=None, max_length=120)


class SmsOtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    device_id: str = Field(default="legacy-client", min_length=1, max_length=120)
    client_platform: str | None = Field(default=None, max_length=32)
    device_name: str | None = Field(default=None, max_length=120)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=32, max_length=512)


class EmailVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=512)
    device_id: str = Field(default="legacy-client", min_length=1, max_length=120)
    client_platform: str | None = Field(default=None, max_length=32)
    device_name: str | None = Field(default=None, max_length=120)


class EmailResendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=512)
    new_password: str = Field(min_length=10, max_length=128)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)


class DevTokenRequest(BaseModel):
    user_id: UUID | None = None
    nickname: str = Field(default="测试用户", min_length=1, max_length=80)
    device_id: str | None = Field(default=None, min_length=1, max_length=120)


class RegistrationResponse(BaseModel):
    user_id: UUID
    verification_required: bool = True
    verification_delivery_pending: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    session_id: UUID
    token_type: str = "bearer"
    user_id: UUID
    access_expires_at: datetime
    refresh_expires_at: datetime
    # 注销恢复导航提示，不是授权位。
    account_deletion_in_progress: bool = False


class SmsOtpRequestResponse(BaseModel):
    request_id: UUID
    expires_at: datetime
    cooldown_until: datetime


class EmailVerificationResponse(BaseModel):
    verified: bool = True
    already_verified: bool = False
    session: TokenResponse | None = None


class AuthSessionRead(BaseModel):
    id: UUID
    device_id: str
    client_platform: str | None
    device_name: str | None
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    current: bool = False


class AuthAcceptedResponse(BaseModel):
    accepted: bool = True


class UserRead(ORMModel):
    id: UUID
    nickname: str
    phone: str | None
    email: str | None
    timezone: str
    locale: str
    elder_mode_enabled: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: NicknameText | None = None
    timezone: TimezoneName | None = None
    locale: LocaleText | None = None
    elder_mode_enabled: StrictBool | None = None


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_type: MemoryType = MemoryType.NOTE
    title: str | None = Field(default=None, max_length=240)
    content: str = Field(min_length=1, max_length=20000)
    occurred_at: datetime | None = None
    capture_source: UserCaptureSource = UserCaptureSource.USER_TEXT
    place_id: UUID | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_unverified_media_source(self):
        # [人工注释][S1-004][S1-005][S1-007] USER_PHOTO / USER_VOICE 都不能由通用
        # Memory API 裸声明。必须分别走 READY media -> 专用服务端 Evidence 流程，
        # 防止客户端把字符串或伪造 ASR 直接升级为 confirmed fact。
        if self.capture_source == UserCaptureSource.USER_PHOTO:
            raise ValueError("USER_PHOTO requires a verified media object")
        if self.capture_source == UserCaptureSource.USER_VOICE:
            raise ValueError("USER_VOICE requires verified audio and server ASR")
        return self


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # expected_revision 是并发前置条件，不是可编辑业务字段；必须来自最近一次服务端 GET。
    expected_revision: int = Field(ge=0)
    title: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def validate_edit_fields(self):
        if not self.model_fields_set.intersection({"title", "content"}):
            raise ValueError("at least one editable field is required")
        if "content" in self.model_fields_set:
            if self.content is None or not self.content.strip():
                raise ValueError("content must not be empty")
        return self


class MemoryRead(ORMModel):
    id: UUID
    user_id: UUID
    memory_type: MemoryType
    title: str | None
    content: str
    occurred_at: datetime
    source_type: SourceType
    confidence: float
    place_id: UUID | None
    latitude: float | None
    longitude: float | None
    is_confirmed: bool
    metadata_json: dict
    edit_revision: int
    edited_at: datetime | None
    created_at: datetime


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: UUID
    title: ReminderTitleText
    content: ReminderContentText | None = None
    # [人工注释][S1-025] remind_at 必须携带明确 offset/Z；客户端本地 naive 时间
    # 不能由服务端猜测成某个时区，避免 DST/跨时区提醒落到错误时刻。
    remind_at: TimezoneAwareDateTime


class ReminderRead(ORMModel):
    id: UUID
    user_id: UUID
    memory_id: UUID | None
    title: str
    content: str | None
    remind_at: datetime
    status: ReminderStatus
    created_at: datetime


class SignedTransfer(BaseModel):
    # [人工注释][S1-006] URL 只是临时能力票据；expires_at/headers 属于冻结协议，
    # 客户端不得把 URL 持久化为永久资源地址。
    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class MediaUploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # [人工注释][S1-004][S1-006] 图片与语音复用同一个 opaque 上传协议；
    # client_upload_id 只在用户域内做重试幂等，客户端仍不能提交任何 storage key。
    client_upload_id: UUID
    kind: MediaKind = MediaKind.IMAGE
    content_type: ImageContentType | AudioContentType
    size_bytes: int = Field(gt=0, le=50 * 1024 * 1024)
    original_filename: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_kind_content_type_pair(self):
        if self.kind == MediaKind.IMAGE and not isinstance(
            self.content_type, ImageContentType
        ):
            raise ValueError("IMAGE requires an image content type")
        if self.kind == MediaKind.AUDIO and not isinstance(
            self.content_type, AudioContentType
        ):
            raise ValueError("AUDIO requires an audio content type")
        return self


class MediaRead(ORMModel):
    # [人工注释][S1-006] 公共媒体协议只暴露业务元数据；storage_etag 留在服务端内部，
    # 避免把 S3/COS/OSS 的实现细节冻结成客户端契约。
    id: UUID
    kind: MediaKind
    status: MediaStatus
    content_type: str
    size_bytes: int
    original_filename: str | None
    created_at: datetime
    completed_at: datetime | None


class MediaUploadResponse(MediaRead):
    upload: SignedTransfer | None


class MediaCompleteResponse(MediaRead):
    cache_version: str


class MediaDownloadResponse(BaseModel):
    media_id: UUID
    # Opaque server-owned content version for local presentation cache identity.
    # It must not expose storage object keys, raw ETag values, or signed URL lifetime.
    cache_version: str
    download: SignedTransfer


class PhotoMemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # [人工注释][S1-005] 图片文本只能来自用户主动输入；本阶段没有 OCR/Vision
    # 输出字段，也没有任何客户端可信度/确认状态字段。
    title: str | None = Field(default=None, max_length=240)
    content: str = Field(min_length=1, max_length=20000)
    occurred_at: TimezoneAwareDateTime | None = None


class PhotoMemoryResponse(BaseModel):
    media: MediaRead
    memory: MemoryRead


class VoiceMemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # [人工注释][S1-004][S1-007] 客户端只能为这段主动录音附加标题/发生时间；
    # transcript、confidence、confirmed、provider 状态全部由服务端 ASR/Evidence 链产生。
    title: str | None = Field(default=None, max_length=240)
    occurred_at: TimezoneAwareDateTime | None = None


class VoiceMemoryResponse(BaseModel):
    media: MediaRead
    memory: MemoryRead


class ObjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)


class ObjectRead(ORMModel):
    id: UUID
    name: str
    category: str | None
    description: str | None
    created_at: datetime


class ObjectPageResponse(BaseModel):
    items: list[ObjectRead] = Field(default_factory=list)
    next_cursor: str | None = None


class ObjectLocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_text: str = Field(min_length=1, max_length=2000)
    recorded_at: TimezoneAwareDateTime | None = None
    capture_source: UserCaptureSource = UserCaptureSource.USER_TEXT
    place_id: UUID | None = None

    @model_validator(mode="after")
    def reject_unverified_media_source(self):
        # [人工注释][S1-004][S1-005][S1-007] 当前对象位置 API 只接受 USER_TEXT。
        # 图片/语音必须等待各自 verified media 派生链；不能仅靠 capture_source
        # 字符串冒充 Evidence。
        if self.capture_source == UserCaptureSource.USER_PHOTO:
            raise ValueError(
                "USER_PHOTO object locations require a future verified media flow"
            )
        if self.capture_source == UserCaptureSource.USER_VOICE:
            raise ValueError(
                "USER_VOICE object locations require verified audio and server ASR"
            )
        return self


class ObjectLocationRead(ORMModel):
    id: UUID
    object_id: UUID
    location_text: str
    recorded_at: datetime
    confidence: float
    status: ObjectLocationStatus
    memory_id: UUID | None


class MemoryQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class Evidence(BaseModel):
    # [人工注释][S1-FIX-002] kind 描述证据实体类型；source_type 才是 USER_TEXT/GPS 等真实来源。
    kind: str
    id: UUID
    source_type: SourceType
    memory_source_id: UUID
    # 当前文字若来自用户后续修正，必须显式区别于最初采集来源。
    provenance: EvidenceProvenance = EvidenceProvenance.ORIGINAL_SOURCE
    occurred_at: datetime
    excerpt: str
    confidence: float
    # [人工注释][S1-004][S1-005] 图片/语音 Evidence 都只暴露 opaque media_id；
    # 原始媒体读取仍必须再走 owner 校验和短时下载签名。
    media_id: UUID | None = None


class MemoryQueryResponse(BaseModel):
    answer: str | None
    can_answer: bool
    certainty: str
    reason: str | None = None
    intent: str
    evidence: list[Evidence] = Field(default_factory=list)
    memory_ids: list[UUID] = Field(default_factory=list)
    # CORE-002 structured historical authority. Clients render this directly for
    # whereabouts queries instead of parsing natural-language answer text.
    day_footprint: DayFootprintResponse | None = None


class LocationPointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_uuid: LocationClientUuid
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    speed: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    recorded_at: TimezoneAwareDateTime


class LocationBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[LocationPointCreate] = Field(min_length=1, max_length=500)


class LocationBatchResponse(BaseModel):
    accepted: int
    duplicates: int = 0
    rejected_privacy: int = 0
    rejected_finalized: int = 0
    derived_visits: int = 0
    raw_deleted: int = 0
    finalized_through: datetime | None = None


class VisitRead(ORMModel):
    id: UUID
    place_id: UUID
    arrived_at: datetime
    left_at: datetime | None
    duration_seconds: int | None
    confidence: float
    source: str
    centroid_latitude: float | None
    centroid_longitude: float | None
    source_point_count: int | None
    source_started_at: datetime | None
    source_ended_at: datetime | None
    source_fingerprint: str | None
    algorithm_version: str | None
    finalized_at: datetime | None


class PlaceNameCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_uuid: UUID
    # null 表示显式撤销用户纠正，展示名回退到最新 automatic candidate / 未命名地点。
    name: PlaceNameText | None


class PlaceNameCorrectionRead(ORMModel):
    id: UUID
    place_id: UUID
    client_uuid: UUID
    revision: int
    previous_user_name: str | None
    new_user_name: str | None
    created_at: datetime


class PlaceRead(ORMModel):
    id: UUID
    # name 是服务端按 USER > AUTOMATIC > UNNAMED 计算后的兼容展示字段。
    name: str
    automatic_name: str | None
    automatic_name_source: str | None
    user_name: str | None
    name_source: PlaceDisplayNameSource
    name_revision: int
    name_updated_at: datetime | None
    latitude: float | None
    longitude: float | None
    address: str | None
    category: str | None
    first_visited_at: datetime | None
    last_visited_at: datetime | None
    visit_count: int
    is_user_named: bool


class DayFootprintVisit(BaseModel):
    # [人工注释][CORE-002] Day Footprint 是 Visit + Place 的 canonical 只读投影。
    # 不暴露 raw LocationPoint/route；地点元数据只来自当前 owner 的 trusted Place。
    id: UUID
    place_id: UUID
    place_name: str
    place_latitude: float | None = None
    place_longitude: float | None = None
    place_address: str | None = None
    place_category: str | None = None
    arrived_at: datetime
    left_at: datetime | None = None
    arrived_at_local: datetime
    left_at_local: datetime | None = None
    confidence: float
    visit_source: str
    visit_finalized: bool


class DayFootprintResponse(BaseModel):
    timezone: str
    day: date
    empty: bool
    visits: list[DayFootprintVisit] = Field(default_factory=list)


class TodayFootprintVisit(DayFootprintVisit):
    pass


class TodayFootprintResponse(DayFootprintResponse):
    visits: list[TodayFootprintVisit] = Field(default_factory=list)


class TimelineItem(BaseModel):
    # [人工注释][S2-011] Timeline 是只读聚合，不复制成新的事实表；id 始终指向
    # 原始 Memory/Visit，客户端必须结合 kind 解释其来源。
    kind: TimelineItemKind
    id: UUID
    occurred_at: datetime
    ended_at: datetime | None = None
    place_id: UUID | None = None
    place_name: str | None = None

    # Memory-only fields.
    memory_type: MemoryType | None = None
    title: str | None = None
    content: str | None = None
    source_type: SourceType | None = None
    is_confirmed: bool | None = None
    # PHOTO-only canonical media identity. Never expose storage keys or signed URLs here.
    media_id: UUID | None = None

    # Shared/Visit evidence metadata.
    confidence: float
    visit_source: str | None = None
    visit_finalized: bool | None = None


class TimelinePageResponse(BaseModel):
    timezone: str
    day: date | None
    items: list[TimelineItem] = Field(default_factory=list)
    next_cursor: str | None = None


class PlaceDetailVisitRead(BaseModel):
    id: UUID
    arrived_at: datetime
    left_at: datetime | None
    duration_seconds: int | None
    confidence: float
    source: str
    finalized_at: datetime | None
    visit_finalized: bool


class PlaceDetailResponse(BaseModel):
    # [人工注释][S2-013] Place detail 只组合现有 retained facts；
    # place 继续使用 S2-009/S2-010 的权威命名 read model，不复制第二份名称语义。
    place: PlaceRead
    visits: list[PlaceDetailVisitRead] = Field(default_factory=list)
    next_cursor: str | None = None


class PrivacyPauseRequest(BaseModel):
    duration_minutes: int | None = Field(default=None, ge=1, le=60 * 24)
    until: datetime | None = None

    @model_validator(mode="after")
    def validate_mode(self):
        if (self.duration_minutes is None) == (self.until is None):
            raise ValueError("Provide exactly one of duration_minutes or until")
        return self


class PrivacyStatusResponse(BaseModel):
    recording_paused: bool
    paused_since: datetime | None
    paused_until: datetime | None


class RecordingHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    RECOVERING = "RECOVERING"
    UNKNOWN = "UNKNOWN"


class RecordingHealthReason(StrEnum):
    RECENT_CAPTURE_AND_ACK = "RECENT_CAPTURE_AND_ACK"
    PRIVACY_PAUSED = "PRIVACY_PAUSED"
    PERMISSION_BLOCKED = "PERMISSION_BLOCKED"
    LOCATION_SERVICES_OFF = "LOCATION_SERVICES_OFF"
    AUTOMATIC_DISABLED = "AUTOMATIC_DISABLED"
    PLATFORM_RESTRICTED = "PLATFORM_RESTRICTED"
    QUEUE_BACKLOG = "QUEUE_BACKLOG"
    QUEUE_CAPACITY_PRESSURE = "QUEUE_CAPACITY_PRESSURE"
    DELIVERY_BACKLOG = "DELIVERY_BACKLOG"
    DELIVERY_FAILURE = "DELIVERY_FAILURE"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    PRODUCER_NOT_RUNNING = "PRODUCER_NOT_RUNNING"
    NO_RECENT_FIX = "NO_RECENT_FIX"
    NO_RECENT_ACK = "NO_RECENT_ACK"
    RECORDED_GAP = "RECORDED_GAP"
    NATIVE_STATE_UNAVAILABLE = "NATIVE_STATE_UNAVAILABLE"
    CLIENT_STATE_STALE = "CLIENT_STATE_STALE"


class RecordingPermissionState(StrEnum):
    BACKGROUND = "BACKGROUND"
    FOREGROUND = "FOREGROUND"
    DENIED = "DENIED"
    RESTRICTED = "RESTRICTED"
    NOT_DETERMINED = "NOT_DETERMINED"
    UNKNOWN = "UNKNOWN"


class RecordingLocationServicesState(StrEnum):
    ON = "ON"
    OFF = "OFF"
    UNKNOWN = "UNKNOWN"


class RecordingBackgroundRuntimeState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


class RecordingBatteryOptimizationState(StrEnum):
    EXEMPT = "EXEMPT"
    OPTIMIZED = "OPTIMIZED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"


class RecordingProducerState(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"


class RecordingDeliveryErrorCode(StrEnum):
    NETWORK_UNAVAILABLE = "NETWORK_UNAVAILABLE"
    SERVER_RETRYABLE = "SERVER_RETRYABLE"
    AUTHORITY_REJECTED = "AUTHORITY_REJECTED"
    PRIVACY_REJECTED = "PRIVACY_REJECTED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    QUEUE_ERROR = "QUEUE_ERROR"
    UNKNOWN = "UNKNOWN"


class RecordingGapReason(StrEnum):
    PERMISSION_BLOCKED = "PERMISSION_BLOCKED"
    LOCATION_SERVICES_OFF = "LOCATION_SERVICES_OFF"
    PRIVACY_PAUSED = "PRIVACY_PAUSED"
    PLATFORM_RESTRICTED = "PLATFORM_RESTRICTED"
    QUEUE_CAPACITY_PRESSURE = "QUEUE_CAPACITY_PRESSURE"
    DELIVERY_BACKLOG = "DELIVERY_BACKLOG"
    PRODUCER_NOT_RUNNING = "PRODUCER_NOT_RUNNING"
    NO_RECENT_FIX = "NO_RECENT_FIX"
    UNKNOWN = "UNKNOWN"


class RecordingGapState(StrEnum):
    NONE = "NONE"
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class RecordingCoverageState(StrEnum):
    HEALTHY = "HEALTHY"
    PARTIAL = "PARTIAL"
    GAPPED = "GAPPED"
    UNKNOWN = "UNKNOWN"


class RecordingClientState(BaseModel):
    """Privacy-safe local diagnostics supplied by the authenticated Flutter owner.

    This is evidence for one projection request, not a second producer and not a durable
    route log. Raw coordinates, content and device identifiers are intentionally absent.
    """

    model_config = ConfigDict(extra="forbid")

    observed_at: TimezoneAwareDateTime
    platform: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=16),
    ]
    automatic_enabled: StrictBool
    permission_state: RecordingPermissionState
    location_services_state: RecordingLocationServicesState
    background_runtime_state: RecordingBackgroundRuntimeState
    battery_optimization_state: RecordingBatteryOptimizationState | None = None
    native_producer_state: RecordingProducerState

    native_queue_schema_version: int = Field(default=0, ge=0, le=100)
    native_queue_depth: int = Field(default=0, ge=0, le=100000)
    native_queue_capacity: int = Field(default=0, ge=0, le=100000)
    native_oldest_pending_at: TimezoneAwareDateTime | None = None
    native_queue_corrupt: StrictBool = False
    native_queue_storage_unavailable: StrictBool = False

    sqlite_queue_depth: int = Field(default=0, ge=0, le=100000)
    sqlite_oldest_pending_at: TimezoneAwareDateTime | None = None
    capacity_pressure: StrictBool = False
    dropped_sample_count: int = Field(default=0, ge=0, le=100000)

    last_fix_at: TimezoneAwareDateTime | None = None
    last_enqueue_at: TimezoneAwareDateTime | None = None
    last_handoff_at: TimezoneAwareDateTime | None = None
    last_upload_attempt_at: TimezoneAwareDateTime | None = None

    delivery_failure_count: int = Field(default=0, ge=0, le=100000)
    last_delivery_error_code: RecordingDeliveryErrorCode | None = None
    recovery_pending: StrictBool = False


class RecordingGapSummary(BaseModel):
    reason: RecordingGapReason
    started_at: datetime
    ended_at: datetime
    duration_seconds: int = Field(ge=0)


class RecordingTodayCoverage(BaseModel):
    local_day: date
    timezone: TimezoneName
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    trusted_location_sample_count: int = Field(ge=0)
    visit_count: int = Field(ge=0)
    memory_count: int = Field(ge=0)
    covered_duration_seconds: int = Field(ge=0)
    known_gap_duration_seconds: int = Field(ge=0)
    largest_known_gap_seconds: int = Field(ge=0)
    coverage_state: RecordingCoverageState
    has_capacity_pressure: bool
    has_recorded_gap: bool
    has_unexplained_gap: bool
    recent_gaps: list[RecordingGapSummary] = Field(default_factory=list, max_length=8)


class RecordingHealthAggregates(BaseModel):
    healthy_days_7d: int = Field(ge=0, le=7)
    healthy_days_30d: int = Field(ge=0, le=30)
    evidence_days_7d: int = Field(ge=0, le=7)
    evidence_days_30d: int = Field(ge=0, le=30)
    # Location Gap Hours V1 counts only evidence-bounded intervals produced by the reviewed
    # gap policy. Day edges without authority are excluded rather than invented. When an
    # entire window has no evidence, the metric is unavailable (null), not a fabricated 0.
    gap_hours_7d: float | None = Field(default=None, ge=0)
    gap_hours_30d: float | None = Field(default=None, ge=0)
    bounded_gap_hours_7d: float = Field(ge=0)
    bounded_gap_hours_30d: float = Field(ge=0)
    days_with_capacity_pressure: int | None = Field(default=None, ge=0, le=30)
    days_with_permission_block: int | None = Field(default=None, ge=0, le=30)
    current_capacity_pressure: bool | None = None
    current_permission_block: bool | None = None


class RecordingHealthSnapshot(BaseModel):
    status: RecordingHealthStatus
    status_reason: RecordingHealthReason
    automatic_enabled: bool | None
    privacy_paused: bool

    permission_state: RecordingPermissionState | None
    location_services_state: RecordingLocationServicesState | None
    background_runtime_state: RecordingBackgroundRuntimeState | None
    battery_optimization_state: RecordingBatteryOptimizationState | None

    native_producer_state: RecordingProducerState | None
    native_queue_depth: int = Field(ge=0)
    native_queue_capacity: int = Field(ge=0)
    native_oldest_pending_at: datetime | None
    sqlite_queue_depth: int = Field(ge=0)
    capacity_pressure: bool

    last_fix_at: datetime | None
    last_enqueue_at: datetime | None
    last_handoff_at: datetime | None
    last_upload_attempt_at: datetime | None
    last_upload_success_at: datetime | None
    last_server_ack_at: datetime | None
    last_visit_at: datetime | None

    delivery_failure_count: int = Field(ge=0)
    last_delivery_error_code: RecordingDeliveryErrorCode | None
    recovery_pending: bool
    recording_gap_state: RecordingGapState
    updated_at: datetime


class RecordingHealthResponse(BaseModel):
    health: RecordingHealthSnapshot
    today: RecordingTodayCoverage
    aggregates: RecordingHealthAggregates
    recent_gaps: list[RecordingGapSummary] = Field(default_factory=list, max_length=8)
    active_gap_reasons: list[RecordingGapReason] = Field(default_factory=list, max_length=8)
    server_observed_at: datetime
    native_state_observed: bool


class DaySummaryResponse(BaseModel):
    date: str
    memory_count: int
    place_count: int
    summary: str
