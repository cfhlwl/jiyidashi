"""add memory edit audit trail

Revision ID: 0007_memory_edit
Revises: 0006_client_mutations
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_memory_edit"
down_revision: str | None = "0006_client_mutations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 当前 Memory 保存用户可见快照；原始 MemorySource 不迁移、不重写。
    op.add_column(
        "memories",
        sa.Column("edit_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "memories",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 每次实际修改保留 before/after；正文修正可关联一条新的 USER_TEXT MemorySource。
    op.create_table(
        "memory_edits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_title", sa.String(length=240), nullable=True),
        sa.Column("previous_content", sa.Text(), nullable=False),
        sa.Column("new_title", sa.String(length=240), nullable=True),
        sa.Column("new_content", sa.Text(), nullable=False),
        sa.Column("changed_title", sa.Boolean(), nullable=False),
        sa.Column("changed_content", sa.Boolean(), nullable=False),
        sa.Column("memory_source_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["memory_source_id"], ["memory_sources.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "memory_id", "revision", name="uq_memory_edits_memory_revision"
        ),
        sa.UniqueConstraint(
            "memory_source_id", name="uq_memory_edits_memory_source"
        ),
    )
    op.create_index(
        op.f("ix_memory_edits_memory_id"),
        "memory_edits",
        ["memory_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_memory_edits_user_id"),
        "memory_edits",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_edits_user_created",
        "memory_edits",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_memory_edits_user_created", table_name="memory_edits")
    op.drop_index(op.f("ix_memory_edits_user_id"), table_name="memory_edits")
    op.drop_index(op.f("ix_memory_edits_memory_id"), table_name="memory_edits")
    op.drop_table("memory_edits")
    op.drop_column("memories", "edited_at")
    op.drop_column("memories", "edit_revision")
