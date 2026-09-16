"""add private media assets and evidence links

Revision ID: 0004_stage1_media
Revises: 0003_auth_rate_limits
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_stage1_media"
down_revision: str | None = "0003_auth_rate_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

media_kind = sa.Enum("IMAGE", name="mediakind", native_enum=False)
media_status = sa.Enum("PENDING", "READY", name="mediastatus", native_enum=False)


def upgrade() -> None:
    # [人工注释][S1-005][S1-006] 媒体表只保存私有 staging/final key 与预期元数据，
    # 不保存永久公开 URL；user_id + client_upload_id 保证用户域内上传重试幂等。
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_upload_id", sa.Uuid(), nullable=False),
        sa.Column("kind", media_kind, nullable=False),
        sa.Column("status", media_status, nullable=False),
        sa.Column("upload_object_key", sa.String(512), nullable=False),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("storage_etag", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "client_upload_id",
            name="uq_media_assets_user_client_upload_id",
        ),
        sa.UniqueConstraint(
            "upload_object_key",
            name="uq_media_assets_upload_object_key",
        ),
        sa.UniqueConstraint("object_key", name="uq_media_assets_object_key"),
    )
    op.create_index("ix_media_assets_user_id", "media_assets", ["user_id"])

    # [人工注释][S1-005] 原始图片与参与 Evidence gate 的 MemorySource 一对一关联；
    # USER_PHOTO 可追溯到真实 READY media，而不是依赖客户端字符串声明。
    op.create_table(
        "media_evidence_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("media_id", sa.Uuid(), nullable=False),
        sa.Column("memory_source_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media_assets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_source_id"],
            ["memory_sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_id", name="uq_media_evidence_links_media_id"),
        sa.UniqueConstraint(
            "memory_source_id",
            name="uq_media_evidence_links_memory_source_id",
        ),
    )
    op.create_index(
        "ix_media_evidence_links_media_id",
        "media_evidence_links",
        ["media_id"],
    )
    op.create_index(
        "ix_media_evidence_links_memory_source_id",
        "media_evidence_links",
        ["memory_source_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_evidence_links_memory_source_id",
        table_name="media_evidence_links",
    )
    op.drop_index(
        "ix_media_evidence_links_media_id",
        table_name="media_evidence_links",
    )
    op.drop_table("media_evidence_links")
    op.drop_index("ix_media_assets_user_id", table_name="media_assets")
    op.drop_table("media_assets")
