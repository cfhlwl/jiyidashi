from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL
from app.models import utcnow
from app.vector_support import vector_type


class MemoryEmbedding(Base):
    """One current derived embedding row for one authoritative Memory."""

    __tablename__ = "memory_embeddings"
    __table_args__ = (
        # [人工注释][S3-009] memory_id 与 user_id 必须作为一个数据库事实绑定，
        # 防止合法 FK 组合出 “A 的 Memory + B 的 owner partition”。
        ForeignKeyConstraint(
            ["memory_id", "user_id"],
            ["memories.id", "memories.user_id"],
            name="fk_memory_embeddings_memory_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            f"dimensions = {MEMORY_EMBEDDING_DIMENSIONS}",
            name="ck_memory_embeddings_dimensions",
        ),
        Index("ix_memory_embeddings_user_id", "user_id"),
        Index(
            "ix_memory_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    memory_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    memory_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default=MEMORY_EMBEDDING_MODEL,
    )
    dimensions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=MEMORY_EMBEDDING_DIMENSIONS,
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(
        vector_type(MEMORY_EMBEDDING_DIMENSIONS),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
