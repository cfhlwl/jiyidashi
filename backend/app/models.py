from __future__ import annotations

import enum
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class MemoryType(str, enum.Enum):
    NOTE = "NOTE"
    VOICE = "VOICE"
    PHOTO = "PHOTO"
    PLACE = "PLACE"
    OBJECT_LOCATION = "OBJECT_LOCATION"
    REMINDER = "REMINDER"
    EVENT = "EVENT"


class SourceType(str, enum.Enum):
    USER_TEXT = "USER_TEXT"
    USER_VOICE = "USER_VOICE"
    USER_PHOTO = "USER_PHOTO"
    GPS = "GPS"
    PHOTO_EXIF = "PHOTO_EXIF"
    SYSTEM_PLACE = "SYSTEM_PLACE"
    AI_INFERENCE = "AI_INFERENCE"


class ObjectLocationStatus(str, enum.Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ReminderStatus(str, enum.Enum):
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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_uuid: Mapped[str] = mapped_column(String(80))
    platform: Mapped[str] = mapped_column(String(32))
    device_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    device_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    push_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Place(Base):
    __tablename__ = "places"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    first_visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_visited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visit_count: Mapped[int] = mapped_column(Integer, default=0)
    is_user_named: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_user_occurred", "user_id", "occurred_at"),
        Index("ix_memories_user_type", "user_id", "memory_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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


class LocationPoint(Base):
    __tablename__ = "location_points"
    __table_args__ = (
        Index("ix_location_points_user_recorded", "user_id", "recorded_at"),
        UniqueConstraint("user_id", "client_uuid", name="uq_location_points_user_client_uuid"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    client_uuid: Mapped[str] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    place_id: Mapped[UUID] = mapped_column(ForeignKey("places.id", ondelete="CASCADE"), index=True)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.85)
    source: Mapped[str] = mapped_column(String(64), default="LOCATION_CLUSTER")


class ObjectItem(Base):
    __tablename__ = "objects"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", name="uq_objects_user_normalized_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    normalized_name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ObjectLocation(Base):
    __tablename__ = "object_locations"
    __table_args__ = (
        Index("ix_object_locations_object_recorded", "object_id", "recorded_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    object_id: Mapped[UUID] = mapped_column(
        ForeignKey("objects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    recording_paused_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


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
