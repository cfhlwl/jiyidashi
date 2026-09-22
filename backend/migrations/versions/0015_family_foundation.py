"""add Stage 4 family membership and permission foundation

Revision ID: 0015_family_foundation
Revises: 0014_memory_feedback
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_family_foundation"
down_revision: str | None = "0014_memory_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "families",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "family_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('OWNER', 'MEMBER')",
            name="ck_family_memberships_role",
        ),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "family_id",
            "user_id",
            name="uq_family_memberships_family_user",
        ),
        sa.UniqueConstraint(
            "user_id",
            name="uq_family_memberships_one_family_per_user",
        ),
    )
    op.create_index(
        "uq_family_memberships_one_owner",
        "family_memberships",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("role = 'OWNER'"),
        sqlite_where=sa.text("role = 'OWNER'"),
    )

    op.create_table(
        "family_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("inviter_user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_family_invites_not_accepted_and_revoked",
        ),
        sa.CheckConstraint(
            "((accepted_at IS NULL AND accepted_by_user_id IS NULL) "
            "OR (accepted_at IS NOT NULL AND accepted_by_user_id IS NOT NULL))",
            name="ck_family_invites_accept_pair",
        ),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["inviter_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_family_invites_token_hash"),
    )
    op.create_index(
        "ix_family_invites_family_created",
        "family_invites",
        ["family_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "family_permission_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("resource_owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_user_id", sa.Uuid(), nullable=False),
        sa.Column("permission_code", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "resource_owner_user_id <> grantee_user_id",
            name="ck_family_permission_grants_distinct_users",
        ),
        sa.CheckConstraint(
            "permission_code IN "
            "('VIEW_CURRENT_LOCATION', 'VIEW_FOOTPRINT', 'VIEW_MEMORY', 'VIEW_PHOTOS')",
            name="ck_family_permission_grants_code",
        ),
        sa.ForeignKeyConstraint(
            ["family_id", "resource_owner_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_grants_resource_owner_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id", "grantee_user_id"],
            ["family_memberships.family_id", "family_memberships.user_id"],
            name="fk_family_grants_grantee_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "family_id",
            "resource_owner_user_id",
            "grantee_user_id",
            "permission_code",
            name="uq_family_permission_grants_semantic_key",
        ),
    )
    op.create_index(
        "ix_family_permission_grants_grantee_code",
        "family_permission_grants",
        ["grantee_user_id", "permission_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_family_permission_grants_grantee_code",
        table_name="family_permission_grants",
    )
    op.drop_table("family_permission_grants")
    op.drop_index("ix_family_invites_family_created", table_name="family_invites")
    op.drop_table("family_invites")
    op.drop_index("uq_family_memberships_one_owner", table_name="family_memberships")
    op.drop_table("family_memberships")
    op.drop_table("families")
