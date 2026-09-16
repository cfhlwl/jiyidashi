from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models import utcnow


# [人工注释][S1-005][S1-006] 原始图片先成为用户私有媒体，完成对象存储校验与
# staging -> final 晋升后，才能通过 MediaEvidenceLink 进入可信 Evidence 链。
class MediaKind(StrEnum):
    IMAGE = "IMAGE"


class MediaStatus(StrEnum):
    PENDING = "PENDING"
    READY = "READY"


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "client_upload_id",
            name="uq_media_assets_user_client_upload_id",
        ),
        UniqueConstraint(
            "upload_object_key",
            name="uq_media_assets_upload_object_key",
        ),
        UniqueConstraint("object_key", name="uq_media_assets_object_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    client_upload_id: Mapped[UUID] = mapped_column()
    kind: Mapped[MediaKind] = mapped_column(
        Enum(MediaKind, native_enum=False), default=MediaKind.IMAGE
    )
    status: Mapped[MediaStatus] = mapped_column(
        Enum(MediaStatus, native_enum=False), default=MediaStatus.PENDING
    )
    upload_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MediaEvidenceLink(Base):
    __tablename__ = "media_evidence_links"
    __table_args__ = (
        UniqueConstraint("media_id", name="uq_media_evidence_links_media_id"),
        UniqueConstraint(
            "memory_source_id",
            name="uq_media_evidence_links_memory_source_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    media_id: Mapped[UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    memory_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_sources.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
