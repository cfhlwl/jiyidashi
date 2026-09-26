"""add Stage 4G-A elder mode preference

Revision ID: 0019_elder_mode_foundation
Revises: 0018_arrival_home_reminder
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_elder_mode_foundation"
down_revision: str | None = "0018_arrival_home_reminder"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "elder_mode_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "elder_mode_enabled")
