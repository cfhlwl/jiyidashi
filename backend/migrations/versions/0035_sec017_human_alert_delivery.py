"""add human security alert delivery attempt authority

Revision ID: 0035_sec017_human_alert_delivery
Revises: 0034_api001_object_capacity
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_sec017_human_alert_delivery"
down_revision: str | None = "0034_api001_object_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("security_alerts", recreate="auto") as batch:
        batch.add_column(
            sa.Column(
                "delivery_revision",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column("delivery_attempt_token", sa.Uuid(), nullable=True)
        )
        batch.add_column(
            sa.Column("delivery_provider", sa.String(length=32), nullable=True)
        )
        batch.add_column(
            sa.Column("delivery_error_code", sa.String(length=80), nullable=True)
        )
        batch.create_check_constraint(
            "ck_security_alerts_delivery_revision",
            "delivery_revision >= 0",
        )
        batch.alter_column("delivery_revision", server_default=None)

    # SEC-015 used delivery_status/attempts for structured-log flushing only.
    # SEC-017 reuses these fields as human-delivery authority for HIGH/CRITICAL,
    # so legacy log ACK/failure state must never be reinterpreted as a human ACK
    # or consume the new provider attempt budget.
    op.execute(
        sa.text(
            """
            UPDATE security_alerts
            SET delivery_status = 'PENDING',
                delivery_attempts = 0,
                next_retry_at = NULL,
                delivered_at = NULL,
                delivery_revision = 0,
                delivery_attempt_token = NULL,
                delivery_provider = NULL,
                delivery_error_code = NULL
            WHERE severity IN ('HIGH', 'CRITICAL')
            """
        )
    )

    # OPS-002 already created durable SECURITY_ALERT_DELIVERY rows before SEC-017.
    # Re-arm the same immutable job identity so legacy structured-log outcome cannot
    # block the freshly reset human-delivery authority through scheduler dedupe.
    security_alerts = sa.table(
        "security_alerts",
        sa.column("id", sa.Uuid()),
        sa.column("severity", sa.String()),
    )
    maintenance_jobs = sa.table(
        "maintenance_jobs",
        sa.column("job_type", sa.String()),
        sa.column("dedupe_key", sa.String()),
        sa.column("resource_key", sa.String()),
        sa.column("status", sa.String()),
        sa.column("attempt_count", sa.Integer()),
        sa.column("max_attempts", sa.Integer()),
        sa.column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.column("claimed_by", sa.String()),
        sa.column("claim_token", sa.Uuid()),
        sa.column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.column("last_error_code", sa.String()),
        sa.column("started_at", sa.DateTime(timezone=True)),
        sa.column("completed_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    human_resource_keys = sa.select(
        sa.literal("security-alert:") + sa.cast(security_alerts.c.id, sa.String())
    ).where(security_alerts.c.severity.in_(("HIGH", "CRITICAL")))
    op.execute(
        maintenance_jobs.update()
        .where(
            maintenance_jobs.c.job_type == "SECURITY_ALERT_DELIVERY",
            sa.or_(
                maintenance_jobs.c.resource_key.in_(human_resource_keys),
                maintenance_jobs.c.dedupe_key.in_(human_resource_keys),
            ),
        )
        .values(
            status="PENDING",
            attempt_count=0,
            max_attempts=5,
            next_attempt_at=sa.func.current_timestamp(),
            claimed_by=None,
            claim_token=None,
            lease_expires_at=None,
            last_error_code=None,
            started_at=None,
            completed_at=None,
            updated_at=sa.func.current_timestamp(),
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("security_alerts", recreate="auto") as batch:
        batch.drop_constraint(
            "ck_security_alerts_delivery_revision",
            type_="check",
        )
        batch.drop_column("delivery_error_code")
        batch.drop_column("delivery_provider")
        batch.drop_column("delivery_attempt_token")
        batch.drop_column("delivery_revision")
