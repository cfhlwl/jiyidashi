"""add durable user-data deletion orchestration

Revision ID: 0008_data_deletion
Revises: 0007_memory_edit
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_data_deletion"
down_revision: str | None = "0007_memory_edit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


data_deletion_status = sa.Enum(
    "STORAGE_PENDING",
    "WAITING_STORAGE_EXPIRY",
    "WAITING_STORAGE_QUIET",
    "STORAGE_FAILED",
    "DB_PENDING",
    "DB_FAILED",
    "COMPLETED",
    name="datadeletionstatus",
    native_enum=False,
)


def upgrade() -> None:
    # [人工注释][S1-021] 删除任务本身必须先持久化，才能在对象存储或 DB 任一步失败后
    # 用同一 request_id 恢复；User/AuthIdentity 在 S1-022 前明确保留。
    op.create_table(
        "data_deletion_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("status", data_deletion_status, nullable=False),
        sa.Column("storage_capability_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storage_quiet_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("deleted_counts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "request_id",
            name="uq_data_deletion_operations_user_request",
        ),
    )
    op.create_index(
        op.f("ix_data_deletion_operations_user_id"),
        "data_deletion_operations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_data_deletion_operations_one_active",
        "data_deletion_operations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status != 'COMPLETED'"),
        sqlite_where=sa.text("status != 'COMPLETED'"),
    )

    # [人工注释][S1-021] object key 只在删除未完成期间作为 durable obligation 保存；
    # cleanup 成功后立即删除这些 key 行，避免删除账本反而长期保留媒体路径。
    op.create_table(
        "data_deletion_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("deletion_id", sa.Uuid(), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["deletion_id"],
            ["data_deletion_operations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "deletion_id",
            "object_key",
            name="uq_data_deletion_objects_deletion_key",
        ),
    )
    op.create_index(
        op.f("ix_data_deletion_objects_deletion_id"),
        "data_deletion_objects",
        ["deletion_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_data_deletion_objects_deletion_id"),
        table_name="data_deletion_objects",
    )
    op.drop_table("data_deletion_objects")
    op.drop_index(
        "uq_data_deletion_operations_one_active",
        table_name="data_deletion_operations",
    )
    op.drop_index(
        op.f("ix_data_deletion_operations_user_id"),
        table_name="data_deletion_operations",
    )
    op.drop_table("data_deletion_operations")
