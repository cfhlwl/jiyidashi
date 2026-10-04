"""add SEC-016 durable abuse concurrency authority

Revision ID: 0031_sec016_abuse_concurrency
Revises: 0030_provider_configuration
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_sec016_abuse_concurrency"
down_revision: str | None = "0030_provider_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "concurrency_guards",
        sa.Column("scope_key", sa.String(length=160), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
    )
    op.create_table(
        "work_permits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("service_class", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_work_permits_token_digest"),
    )
    op.create_index(
        "ix_work_permits_service_expires",
        "work_permits",
        ["service_class", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_work_permits_user_expires",
        "work_permits",
        ["user_id", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_work_permits_user_expires", table_name="work_permits")
    op.drop_index("ix_work_permits_service_expires", table_name="work_permits")
    op.drop_table("work_permits")
    op.drop_table("concurrency_guards")
