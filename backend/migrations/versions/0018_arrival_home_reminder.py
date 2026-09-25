"""add Stage 4F-B arrival-home reminders

Revision ID: 0018_arrival_home_reminder
Revises: 0017_emergency_location_sharing
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_arrival_home_reminder"
down_revision: str | None = "0017_emergency_location_sharing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("places") as batch:
        batch.create_unique_constraint(
            "uq_places_id_user_id",
            ["id", "user_id"],
        )

    op.create_table(
        "family_arrival_reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("resource_owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_user_id", sa.Uuid(), nullable=False),
        sa.Column("destination_place_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "resource_owner_user_id <> grantee_user_id",
            name="ck_family_arrival_reminders_distinct_users",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARRIVED', 'CANCELLED', 'EXPIRED')",
            name="ck_family_arrival_reminders_status",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_family_arrival_reminders_positive_window",
        ),
        sa.CheckConstraint(
            "(status = 'ARRIVED' AND arrived_at IS NOT NULL AND cancelled_at IS NULL) "
            "OR (status = 'CANCELLED' AND arrived_at IS NULL AND cancelled_at IS NOT NULL) "
            "OR (status IN ('ACTIVE', 'EXPIRED') AND arrived_at IS NULL "
            "AND cancelled_at IS NULL)",
            name="ck_family_arrival_reminders_terminal_fields",
        ),
        sa.ForeignKeyConstraint(
            ["family_id", "resource_owner_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_arrival_owner_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id", "grantee_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_arrival_grantee_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_place_id", "resource_owner_user_id"],
            ["places.id", "places.user_id"],
            name="fk_family_arrival_destination_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_family_arrival_active_tuple",
        "family_arrival_reminders",
        [
            "family_id",
            "resource_owner_user_id",
            "grantee_user_id",
            "destination_place_id",
            "status",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_family_arrival_active_tuple",
        table_name="family_arrival_reminders",
    )
    op.drop_table("family_arrival_reminders")
    with op.batch_alter_table("places") as batch:
        batch.drop_constraint("uq_places_id_user_id", type_="unique")
