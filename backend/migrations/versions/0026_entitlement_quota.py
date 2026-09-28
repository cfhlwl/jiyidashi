"""add BIZ entitlement and quota foundation

Revision ID: 0026_entitlement_quota
Revises: 0025_security_alerting
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_entitlement_quota"
down_revision: str | None = "0025_security_alerting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_entitlements",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_code", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 0", name="ck_user_entitlements_revision"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_user_entitlements_plan_code",
        "user_entitlements",
        ["plan_code"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO user_entitlements (
                user_id,
                plan_code,
                revision,
                effective_at,
                expires_at,
                created_at,
                updated_at
            )
            SELECT
                id,
                'LEGACY_FULL',
                0,
                CURRENT_TIMESTAMP,
                NULL,
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM users
            """
        )
    )

    op.create_table(
        "ai_quota_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_requests", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider_requests >= 0",
            name="ck_ai_quota_provider_requests",
        ),
        sa.CheckConstraint("input_tokens >= 0", name="ck_ai_quota_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_ai_quota_output_tokens"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "period_start",
            "period_end",
            name="uq_ai_quota_period_user_range",
        ),
    )
    op.create_index("ix_ai_quota_periods_user_id", "ai_quota_periods", ["user_id"])

    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("gateway_request_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("provider_invocation_reserved", sa.Boolean(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_ai_usage_input_tokens",
        ),
        sa.CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_ai_usage_output_tokens",
        ),
        sa.ForeignKeyConstraint(
            ["period_id"],
            ["ai_quota_periods.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "gateway_request_id",
            name="uq_ai_usage_user_gateway_request",
        ),
    )
    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"])
    op.create_index(
        "ix_ai_usage_user_created",
        "ai_usage_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_usage_user_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_user_id", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
    op.drop_index("ix_ai_quota_periods_user_id", table_name="ai_quota_periods")
    op.drop_table("ai_quota_periods")
    op.drop_index("ix_user_entitlements_plan_code", table_name="user_entitlements")
    op.drop_table("user_entitlements")
