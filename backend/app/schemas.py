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
