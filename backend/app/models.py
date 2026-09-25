from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class MemoryType(StrEnum):
    NOTE = "NOTE"
    VOICE = "VOICE"
    PHOTO = "PHOTO"
    PLACE = "PLACE"
    OBJECT_LOCATION = "OBJECT_LOCATION"
    REMINDER = "REMINDER"
    EVENT = "EVENT"


class SourceType(StrEnum):
    USER_TEXT = "USER_TEXT"
    USER_VOICE = "USER_VOICE"
    USER_PHOTO = "USER_PHOTO"
    GPS = "GPS"
    PHOTO_EXIF = "PHOTO_EXIF"
    SYSTEM_PLACE = "SYSTEM_PLACE"
    AI_INFERENCE = "AI_INFERENCE"


class ObjectLocationStatus(StrEnum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ReminderStatus(StrEnum):
    PENDING = "PENDING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    nickname: Mapped[str] = mapped_column(String(80), default="新用户")
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    locale: Mapped[str] = mapped_column(String(32), default="zh-CN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("user_id", "client_uuid", name="uq_devices_user_client_uuid"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_uuid: Mapped[str] = mapped_column(String(80))
    platform: Mapped[str] = mapped_column(String(32))
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    push_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Place(Base):
    __tablename__ = "places"
    __table_args__ = (
        UniqueConstraint("user_id", "cluster_key", name="uq_places_user_cluster_key"),
        UniqueConstraint("id", "user_id", name="uq_places_id_user_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # [人工注释][S2-009][S2-010] name 继续作为向后兼容的“当前展示名”缓存；
    # 自动候选和用户纠正必须分别持久化，不能再靠一个字符串推断来源。
    name: Mapped[str] = mapped_column(String(200))
    automatic_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    automatic_name_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_revision: Mapped[int] = mapped_column(Integer, default=0)
    name_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # [人工注释][S2-008] cluster_key 只用于服务端自动 Place 的稳定空间桶；
    # 用户命名/纠正不能改写该 key，也不能改写 Visit provenance。
    cluster_key: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    first_visited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_visited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    visit_count: Mapped[int] = mapped_column(Integer, default=0)
    is_user_named: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def name_source(self) -> str:
        if self.user_name is not None:
            return "USER"
        if self.automatic_name is not None:
            return "AUTOMATIC"
        return "UNNAMED"


class PlaceNameCorrection(Base):
    __tablename__ = "place_name_corrections"
    __table_args__ = (
        UniqueConstraint(
            "place_id",
            "revision",
            name="uq_place_name_corrections_place_revision",
        ),
        Index(
            "ix_place_name_corrections_user_created",
            "user_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    place_id: Mapped[UUID] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    # client_uuid 同时进入 ClientMutation 幂等账本；这里保留它是为了用户数据导出/审计，
    # 但不让本表承担跨资源的通用幂等职责。
    client_uuid: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    previous_user_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    new_user_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        # [人工注释][S3-009] MemoryEmbedding 的 owner partition 必须由数据库直接
        # 绑定到 authoritative Memory owner；复合 UNIQUE 为下游复合 FK 提供可信锚点。
        UniqueConstraint("id", "user_id", name="uq_memories_id_user_id"),
        Index("ix_memories_user_occurred", "user_id", "occurred_at"),
        Index("ix_memories_user_type", "user_id", "memory_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    memory_type: Mapped[MemoryType] = mapped_column(
        Enum(MemoryType, native_enum=False), default=MemoryType.NOTE
    )
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False), default=SourceType.USER_TEXT
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    place_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("places.id", ondelete="SET NULL"), nullable=True
    )
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # 当前 Memory 是用户可见快照；编辑 revision 与时间不覆盖原始 MemorySource。
    edit_revision: Mapped[int] = mapped_column(Integer, default=0)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MemorySource(Base):
    __tablename__ = "memory_sources"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, native_enum=False))
    source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MemoryEdit(Base):
    __tablename__ = "memory_edits"
    __table_args__ = (
        UniqueConstraint("memory_id", "revision", name="uq_memory_edits_memory_revision"),
        UniqueConstraint("memory_source_id", name="uq_memory_edits_memory_source"),
        Index("ix_memory_edits_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    previous_title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    previous_content: Mapped[str] = mapped_column(Text)
    new_title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    new_content: Mapped[str] = mapped_column(Text)
    changed_title: Mapped[bool] = mapped_column(Boolean)
    changed_content: Mapped[bool] = mapped_column(Boolean)
    # 只有正文变化才会关联新的 USER_TEXT source；标题-only 编辑不能伪造正文 Evidence。
    memory_source_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LocationPoint(Base):
    __tablename__ = "location_points"
    __table_args__ = (
        Index("ix_location_points_user_recorded", "user_id", "recorded_at"),
        UniqueConstraint(
            "user_id", "client_uuid", name="uq_location_points_user_client_uuid"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    client_uuid: Mapped[str] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LocationIngestReceipt(Base):
    __tablename__ = "location_ingest_receipts"

    # [人工注释][S2-006] raw GPS 可以按 retention 删除，但 client_uuid 的幂等记忆
    # 必须活到用户主动删除数据。receipt 只留 canonical payload hash + recorded_at，
    # 不长期保存纬度/经度本身。
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    client_uuid: Mapped[str] = mapped_column(String(80), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "derivation_key",
            name="uq_visits_user_derivation_key",
        ),
        Index("ix_visits_user_arrived", "user_id", "arrived_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    place_id: Mapped[UUID] = mapped_column(
        ForeignKey("places.id", ondelete="CASCADE"), index=True
    )
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.85)
    source: Mapped[str] = mapped_column(String(64), default="LOCATION_CLUSTER")
    # [人工注释][S2-007][S2-014] Visit 必须自带可长期保存的派生谱系摘要。
    # raw LocationPoint 过期后，时间边界、点数和 fingerprint 仍能说明这条事实从哪批证据派生。
    derivation_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    centroid_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    centroid_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_point_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    algorithm_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LocationDerivationState(Base):
    __tablename__ = "location_derivation_states"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # [人工注释][S2-014] finalized_through 是 raw cleanup 的 durable 安全水位：
    # 只有 recorded_at <= 此值的点才允许进入 retention 删除候选。
    finalized_through: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ObjectItem(Base):
    __tablename__ = "objects"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "normalized_name", name="uq_objects_user_normalized_name"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    normalized_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ObjectLocation(Base):
    __tablename__ = "object_locations"
    __table_args__ = (
        Index("ix_object_locations_object_recorded", "object_id", "recorded_at"),
        Index(
            "uq_object_locations_one_current",
            "object_id",
            unique=True,
            postgresql_where=text("status = 'CURRENT'"),
            sqlite_where=text("status = 'CURRENT'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey("objects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    memory_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    location_text: Mapped[str] = mapped_column(Text)
    place_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("places.id", ondelete="SET NULL"), nullable=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[ObjectLocationStatus] = mapped_column(
        Enum(ObjectLocationStatus, native_enum=False),
        default=ObjectLocationStatus.CURRENT,
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    memory_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[ReminderStatus] = mapped_column(
        Enum(ReminderStatus, native_enum=False), default=ReminderStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrivacyState(Base):
    __tablename__ = "privacy_states"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    recording_paused_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recording_paused_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PrivacyPauseInterval(Base):
    __tablename__ = "privacy_pause_intervals"
    __table_args__ = (
        Index(
            "ix_privacy_pause_intervals_user_time",
            "user_id",
            "started_at",
            "ended_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FamilyMember(Base):
    __tablename__ = "family_members"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "member_user_id", name="uq_family_owner_member"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    member_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FamilyPermission(Base):
    __tablename__ = "family_permissions"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "member_user_id",
            "permission",
            name="uq_family_permission",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    member_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    permission: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
