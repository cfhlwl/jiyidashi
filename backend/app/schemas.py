from datetime import datetime
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
    StringConstraints,
    model_validator,
)

from app.media_models import MediaKind, MediaStatus
from app.models import MemoryType, ObjectLocationStatus, SourceType


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


class ImageContentType(StrEnum):
    # [人工注释][S1-005] Stage 1 图片协议只冻结常见静态图片类型；不借媒体基础 PR 偷带音频/ASR 或 OCR 格式。
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    HEIC = "image/heic"
    HEIF = "image/heif"


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


class DevTokenRequest(BaseModel):
    user_id: UUID | None = None
    nickname: str = Field(default="测试用户", min_length=1, max_length=80)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: UUID


class UserRead(ORMModel):
    id: UUID
    nickname: str
    phone: str | None
    email: str | None
    timezone: str
    locale: str
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nickname: NicknameText | None = None
    timezone: TimezoneName | None = None
    locale: LocaleText | None = None


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
    def reject_unverified_photo_source(self):
        # [人工注释][S1-005] USER_PHOTO 不能再由通用 Memory API 裸声明；必须走 READY media -> /media/{id}/memory。
        if self.capture_source == UserCaptureSource.USER_PHOTO:
            raise ValueError("USER_PHOTO requires a verified media object")
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
    created_at: datetime


class SignedTransfer(BaseModel):
    # [人工注释][S1-006] URL 仅是临时能力票据；expires_at/headers 属于冻结协议的一部分，客户端不得持久化为永久资源地址。
    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class MediaUploadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # [人工注释][S1-006] client_upload_id 在用户域内承担重试幂等，不允许客户端提供 object_key/bucket/url。
    client_upload_id: UUID
    kind: MediaKind = MediaKind.IMAGE
    content_type: ImageContentType
    size_bytes: int = Field(gt=0, le=50 * 1024 * 1024)
    original_filename: str | None = Field(default=None, max_length=255)


class MediaRead(ORMModel):
    id: UUID
    kind: MediaKind
    status: MediaStatus
    content_type: str
    size_bytes: int
    original_filename: str | None
    storage_etag: str | None
    created_at: datetime
    completed_at: datetime | None


class MediaUploadResponse(MediaRead):
    upload: SignedTransfer | None


class MediaDownloadResponse(BaseModel):
    media_id: UUID
    download: SignedTransfer


class PhotoMemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # [人工注释][S1-005] 图片内容文本必须来自用户主动输入；本阶段没有 OCR/Vision 输出字段，也没有客户端可信度字段。
    title: str | None = Field(default=None, max_length=240)
    content: str = Field(min_length=1, max_length=20000)
    occurred_at: TimezoneAwareDateTime | None = None


class PhotoMemoryResponse(BaseModel):
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


class ObjectLocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_text: str = Field(min_length=1, max_length=2000)
    recorded_at: TimezoneAwareDateTime | None = None
    capture_source: UserCaptureSource = UserCaptureSource.USER_TEXT
    place_id: UUID | None = None

    @model_validator(mode="after")
    def reject_unverified_photo_source(self):
        # [人工注释][S1-005] 物品位置目前没有“图片 -> 位置”可信转换；禁止用 USER_PHOTO 字符串伪造图片 Evidence。
        if self.capture_source == UserCaptureSource.USER_PHOTO:
            raise ValueError("USER_PHOTO object locations require a future verified media flow")
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
    occurred_at: datetime
    excerpt: str
    confidence: float
    # [人工注释][S1-005] 图片 Evidence 只暴露 opaque media_id；读取原始文件必须再次通过 owner 校验获取短时下载签名。
    media_id: UUID | None = None


class MemoryQueryResponse(BaseModel):
    answer: str | None
    can_answer: bool
    certainty: str
    reason: str | None = None
    intent: str
    evidence: list[Evidence] = Field(default_factory=list)
    memory_ids: list[UUID] = Field(default_factory=list)


class LocationPointCreate(BaseModel):
    client_uuid: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    speed: float | None = None
    recorded_at: TimezoneAwareDateTime


class LocationBatchRequest(BaseModel):
    points: list[LocationPointCreate] = Field(min_length=1, max_length=500)


class LocationBatchResponse(BaseModel):
    accepted: int
    rejected_privacy: int = 0


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


class DaySummaryResponse(BaseModel):
    date: str
    memory_count: int
    place_count: int
    summary: str
