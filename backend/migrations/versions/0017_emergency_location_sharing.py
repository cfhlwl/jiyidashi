"""add Stage 4F-A emergency location sharing

Revision ID: 0017_emergency_location_sharing
Revises: 0016_family_privacy_audit
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_emergency_location_sharing"
down_revision: str | None = "0016_family_privacy_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "family_emergency_location_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("resource_owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "resource_owner_user_id <> grantee_user_id",
            name="ck_family_emergency_location_shares_distinct_users",
        ),
        sa.ForeignKeyConstraint(
            ["family_id", "resource_owner_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_emergency_share_owner_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id", "grantee_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_emergency_share_grantee_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_family_emergency_shares_participants",
        "family_emergency_location_shares",
        ["family_id", "resource_owner_user_id", "grantee_user_id", "expires_at"],
        unique=False,
    )

    op.add_column(
        "family_access_audit_events",
        sa.Column(
            "authority_type",
            sa.String(length=24),
            nullable=False,
            server_default="EXACT_GRANT",
        ),
    )
    op.alter_column(
        "family_access_audit_events",
        "permission_code",
        existing_type=sa.String(length=40),
        nullable=True,
    )
    op.drop_constraint(
        "ck_family_access_audit_permission_code",
        "family_access_audit_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_family_access_audit_action",
        "family_access_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_family_access_audit_authority_type",
        "family_access_audit_events",
        "authority_type IN ('EXACT_GRANT', 'EMERGENCY_SHARE')",
    )
    op.create_check_constraint(
        "ck_family_access_audit_authority_permission",
        "family_access_audit_events",
        "(authority_type = 'EXACT_GRANT' AND permission_code IN "
        "('VIEW_CURRENT_LOCATION', 'VIEW_FOOTPRINT', 'VIEW_MEMORY', 'VIEW_PHOTOS')) "
        "OR (authority_type = 'EMERGENCY_SHARE' AND permission_code IS NULL)",
    )
    op.create_check_constraint(
        "ck_family_access_audit_action",
        "family_access_audit_events",
        "action IN "
        "('READ_CURRENT_LOCATION', 'READ_TODAY_FOOTPRINT', 'READ_MEMORY', "
        "'LIST_PHOTOS', 'DOWNLOAD_PHOTO', 'READ_EMERGENCY_LOCATION')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_family_access_audit_action",
        "family_access_audit_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_family_access_audit_authority_permission",
        "family_access_audit_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_family_access_audit_authority_type",
        "family_access_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_family_access_audit_permission_code",
        "family_access_audit_events",
        "permission_code IN "
        "('VIEW_CURRENT_LOCATION', 'VIEW_FOOTPRINT', 'VIEW_MEMORY', 'VIEW_PHOTOS')",
    )
    op.create_check_constraint(
        "ck_family_access_audit_action",
        "family_access_audit_events",
        "action IN "
        "('READ_CURRENT_LOCATION', 'READ_TODAY_FOOTPRINT', 'READ_MEMORY', "
        "'LIST_PHOTOS', 'DOWNLOAD_PHOTO')",
    )
    op.alter_column(
        "family_access_audit_events",
        "permission_code",
        existing_type=sa.String(length=40),
        nullable=False,
    )
    op.drop_column("family_access_audit_events", "authority_type")
    op.drop_index(
        "ix_family_emergency_shares_participants",
        table_name="family_emergency_location_shares",
    )
    op.drop_table("family_emergency_location_shares")
