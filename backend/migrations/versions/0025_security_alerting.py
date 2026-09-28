"""add SEC-015 durable security alerting

Revision ID: 0025_security_alerting
Revises: 0024_life_stage_foundation
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_security_alerting"
down_revision: str | None = "0024_life_stage_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_signal_windows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("correlation_digest", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rule_code",
            "correlation_digest",
            "scope",
            "window_started_at",
            name="uq_security_signal_window_identity",
        ),
        sa.CheckConstraint(
            "signal_count > 0",
            name="ck_security_signal_window_count",
        ),
    )
    op.create_index(
        "ix_security_signal_windows_rule_code",
        "security_signal_windows",
        ["rule_code"],
    )
    op.create_index(
        "ix_security_signal_windows_window_started_at",
        "security_signal_windows",
        ["window_started_at"],
    )

    op.create_table(
        "security_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("correlation_digest", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False),
        sa.Column("delivery_status", sa.String(length=32), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_security_alerts_dedupe_key"),
        sa.CheckConstraint(
            "signal_count > 0",
            name="ck_security_alerts_signal_count",
        ),
        sa.CheckConstraint(
            "delivery_attempts >= 0",
            name="ck_security_alerts_delivery_attempts",
        ),
    )
    op.create_index(
        "ix_security_alerts_rule_code",
        "security_alerts",
        ["rule_code"],
    )
    op.create_index(
        "ix_security_alerts_severity",
        "security_alerts",
        ["severity"],
    )
    op.create_index(
        "ix_security_alerts_delivery_status",
        "security_alerts",
        ["delivery_status"],
    )
    op.create_index(
        "ix_security_alerts_retry_due",
        "security_alerts",
        ["delivery_status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_security_alerts_retry_due", table_name="security_alerts")
    op.drop_index("ix_security_alerts_delivery_status", table_name="security_alerts")
    op.drop_index("ix_security_alerts_severity", table_name="security_alerts")
    op.drop_index("ix_security_alerts_rule_code", table_name="security_alerts")
    op.drop_table("security_alerts")

    op.drop_index(
        "ix_security_signal_windows_window_started_at",
        table_name="security_signal_windows",
    )
    op.drop_index(
        "ix_security_signal_windows_rule_code",
        table_name="security_signal_windows",
    )
    op.drop_table("security_signal_windows")
