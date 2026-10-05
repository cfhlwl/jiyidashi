"""add durable maintenance job authority

Revision ID: 0032_maintenance_jobs
Revises: 0031_sec016_abuse_concurrency
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_maintenance_jobs"
down_revision: str | None = "0031_sec016_abuse_concurrency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "account_deletion_operations",
        sa.Column("local_cleanup_ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "media_assets",
        sa.Column(
            "upload_capability_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_table(
        "maintenance_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("dedupe_key", sa.String(length=160), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("resource_key", sa.String(length=200), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_by", sa.String(length=120), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "job_type IN ('DATA_DELETE', 'ACCOUNT_DELETE', 'MEDIA_PENDING_CLEANUP', "
            "'SECURITY_ALERT_DELIVERY', 'ANALYTICS_RETENTION', 'LOCATION_RETENTION')",
            name="ck_maintenance_jobs_known_type",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_maintenance_jobs_attempt_count",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1 AND max_attempts <= 100",
            name="ck_maintenance_jobs_max_attempts",
        ),
        sa.UniqueConstraint(
            "job_type",
            "dedupe_key",
            name="uq_maintenance_jobs_type_dedupe",
        ),
    )
    op.create_index(
        "ix_maintenance_jobs_due",
        "maintenance_jobs",
        ["status", "next_attempt_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_maintenance_jobs_lease",
        "maintenance_jobs",
        ["status", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_maintenance_jobs_owner_created",
        "maintenance_jobs",
        ["owner_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_maintenance_jobs_owner_created",
        table_name="maintenance_jobs",
    )
    op.drop_index("ix_maintenance_jobs_lease", table_name="maintenance_jobs")
    op.drop_index("ix_maintenance_jobs_due", table_name="maintenance_jobs")
    op.drop_table("maintenance_jobs")
    op.drop_column("media_assets", "upload_capability_expires_at")
    op.drop_column("account_deletion_operations", "local_cleanup_ready_at")
