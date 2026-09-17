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
    # [人工注释][S1-005] Stage 1 静态图片类型继续沿用已冻结协议。
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"
    HEIC = "image/heic"
    HEIF = "image/heif"


class AudioContentType(StrEnum):
    # [人工注释][S1-004][S1-007] E 线第一阶段只接受微信 RecorderManager 产出的 MP3；
    # 客户端声明 MIME 只是候选元数据，READY 前仍由服务端检查真实文件头。
    MPEG = "audio/mpeg"


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
    def reject_unverified_media_source(self):
        # [人工注释][S1-004][S1-005][S1-007] USER_PHOTO / USER_VOICE 都不能由通用
        # Memory API 裸声明。必须分别走 READY media -> 专用服务端 Evidence 流程，
        # 防止客户端把字符串或伪造 ASR 直接升级为 confirmed fact。
        if self.capture_source == UserCaptureSource.USER_PHOTO:
            raise ValueError("USER_PHOTO requires a verified media object")
        if self.capture_source == UserCaptureSource.USER_VOICE:
            raise ValueError("USER_VOICE requires verified audio and server ASR")
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


class MediaDownloadResponse(BaseModel):
    media_id: UUID
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


class ObjectLocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_text: str = Field(min_length=1, max_length=2000)
    recorded_at: TimezoneAwareDateTime | None = None
    capture_source: UserCaptureSource = UserCaptureSource.USER_TEXT
    place_id: UUID | None = None

    @model_validator(mode="after")
    def reject_unverified_media_source(self):
        # [人工注释][S1-004][S1-005][S1-007] 当前对象位置 API 只接受 USER_TEXT。
        # 图片/语音都必须等待各自 verified media 派生链，不能仅靠 capture_source 字符串冒充 Evidence。
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
