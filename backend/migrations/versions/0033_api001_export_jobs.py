"""add async export job authority

Revision ID: 0033_api001_export_jobs
Revises: 0032_maintenance_jobs
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_api001_export_jobs"
down_revision: str | None = "0032_maintenance_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = (
    "DATA_DELETE", "ACCOUNT_DELETE", "MEDIA_PENDING_CLEANUP",
    "SECURITY_ALERT_DELIVERY", "ANALYTICS_RETENTION", "LOCATION_RETENTION"
)
_NEW_TYPES = (*_OLD_TYPES, "EXPORT")


def _job_type_check(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"job_type IN ({quoted})"


def upgrade() -> None:
    with op.batch_alter_table("maintenance_jobs", recreate="auto") as batch:
        batch.drop_constraint("ck_maintenance_jobs_known_type", type_="check")
        batch.create_check_constraint(
            "ck_maintenance_jobs_known_type",
            _job_type_check(_NEW_TYPES),
        )

    op.create_table(
        "user_export_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("format_version", sa.String(length=64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_object_key", sa.String(length=512), nullable=True),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_user_export_jobs_owner_idempotency",
        ),
        sa.UniqueConstraint(
            "artifact_object_key",
            name="uq_user_export_jobs_artifact_object_key",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', "
            "'CANCELLED', 'EXPIRED')",
            name="ck_user_export_jobs_known_status",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_user_export_jobs_revision",
        ),
        sa.CheckConstraint(
            "artifact_size_bytes IS NULL OR artifact_size_bytes >= 0",
            name="ck_user_export_jobs_artifact_size",
        ),
    )
    op.create_index(
        "ix_user_export_jobs_owner_user_id",
        "user_export_jobs",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_export_jobs_owner_requested",
        "user_export_jobs",
        ["owner_user_id", "requested_at"],
        unique=False,
    )
    op.create_index(
        "ix_user_export_jobs_status_expires",
        "user_export_jobs",
        ["status", "expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_export_jobs_status_expires",
        table_name="user_export_jobs",
    )
    op.drop_index(
        "ix_user_export_jobs_owner_requested",
        table_name="user_export_jobs",
    )
    op.drop_index(
        "ix_user_export_jobs_owner_user_id",
        table_name="user_export_jobs",
    )
    op.drop_table("user_export_jobs")

    with op.batch_alter_table("maintenance_jobs", recreate="auto") as batch:
        batch.drop_constraint("ck_maintenance_jobs_known_type", type_="check")
        batch.create_check_constraint(
            "ck_maintenance_jobs_known_type",
            _job_type_check(_OLD_TYPES),
        )
