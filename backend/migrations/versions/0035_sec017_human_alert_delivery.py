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
