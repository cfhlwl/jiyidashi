"""add Stage 4E family privacy audit

Revision ID: 0016_family_privacy_audit
Revises: 0015_family_foundation
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_family_privacy_audit"
down_revision: str | None = "0015_family_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "family_access_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("resource_owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("permission_code", sa.String(length=40), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "permission_code IN "
            "('VIEW_CURRENT_LOCATION', 'VIEW_FOOTPRINT', 'VIEW_MEMORY', 'VIEW_PHOTOS')",
            name="ck_family_access_audit_permission_code",
        ),
        sa.CheckConstraint(
            "resource_type IN ('CURRENT_LOCATION', 'TODAY_FOOTPRINT', 'MEMORY', 'PHOTO')",
            name="ck_family_access_audit_resource_type",
        ),
        sa.CheckConstraint(
            "action IN "
            "('READ_CURRENT_LOCATION', 'READ_TODAY_FOOTPRINT', 'READ_MEMORY', "
            "'LIST_PHOTOS', 'DOWNLOAD_PHOTO')",
            name="ck_family_access_audit_action",
        ),
        sa.CheckConstraint(
            "result IN ('ALLOWED', 'DENIED', 'UNAVAILABLE')",
            name="ck_family_access_audit_result",
        ),
        sa.CheckConstraint(
            "actor_user_id <> resource_owner_user_id",
            name="ck_family_access_audit_distinct_users",
        ),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resource_owner_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_family_access_audit_family_created",
        "family_access_audit_events",
        ["family_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_family_access_audit_family_created",
        table_name="family_access_audit_events",
    )
    op.drop_table("family_access_audit_events")
