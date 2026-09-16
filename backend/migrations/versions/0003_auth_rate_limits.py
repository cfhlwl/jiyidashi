"""add persistent authentication rate limit buckets

Revision ID: 0003_auth_rate_limits
Revises: 0002_stage1_auth
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_auth_rate_limits"
down_revision: str | None = "0002_stage1_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # [人工注释][S1-FIX-003] 多 worker 共用数据库 bucket，在 Argon2 前阻断匿名认证滥用。
    op.create_table(
        "auth_rate_limit_buckets",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_auth_rate_limit_buckets_scope",
        "auth_rate_limit_buckets",
        ["scope"],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limit_buckets_scope", table_name="auth_rate_limit_buckets")
    op.drop_table("auth_rate_limit_buckets")
