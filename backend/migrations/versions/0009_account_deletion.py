"""add transient account deletion gate

Revision ID: 0009_account_deletion
Revises: 0008_data_deletion
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_account_deletion"
down_revision: str | None = "0008_data_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # [人工注释][S1-022] 本表仅覆盖“注销进行中”的跨请求门禁；最终 User 删除事务会
    # 显式删除它，不建立永久 completed tombstone，避免账号注销后继续保留身份关联记录。
    op.create_table(
        "account_deletion_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("data_deletion_request_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            name="uq_account_deletion_operations_user",
        ),
    )
    op.create_index(
        op.f("ix_account_deletion_operations_user_id"),
        "account_deletion_operations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_account_deletion_operations_user_id"),
        table_name="account_deletion_operations",
    )
    op.drop_table("account_deletion_operations")
