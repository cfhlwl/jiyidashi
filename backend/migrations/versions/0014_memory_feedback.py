"""add revision-bound Memory feedback audit

Revision ID: 0014_memory_feedback
Revises: 0013_memory_embedding
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_memory_feedback"
down_revision: str | None = "0013_memory_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_feedbacks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column("memory_revision", sa.Integer(), nullable=False),
        sa.Column("result_revision", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "client_uuid",
            name="uq_memory_feedbacks_user_client_uuid",
        ),
        sa.UniqueConstraint(
            "user_id",
            "memory_id",
            "memory_revision",
            "action",
            name="uq_memory_feedbacks_revision_action",
        ),
    )
    op.create_index(
        op.f("ix_memory_feedbacks_memory_id"),
        "memory_feedbacks",
        ["memory_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_memory_feedbacks_user_id"),
        "memory_feedbacks",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_memory_feedbacks_user_created",
        "memory_feedbacks",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_memory_feedbacks_user_created", table_name="memory_feedbacks")
    op.drop_index(op.f("ix_memory_feedbacks_user_id"), table_name="memory_feedbacks")
    op.drop_index(op.f("ix_memory_feedbacks_memory_id"), table_name="memory_feedbacks")
    op.drop_table("memory_feedbacks")
