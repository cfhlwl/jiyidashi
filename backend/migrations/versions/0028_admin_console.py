"""add production admin console security foundation

Revision ID: 0028_admin_console
Revises: 0027_product_analytics
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_admin_console"
down_revision: str | None = "0027_product_analytics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('SUPER_ADMIN','OPERATOR','SUPPORT_READONLY')",
            name="ck_admin_accounts_role",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_admin_accounts_revision"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_admin_accounts_email"),
    )
    op.create_index("ix_admin_accounts_email", "admin_accounts", ["email"])

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("csrf_digest", sa.String(length=64), nullable=False),
        sa.Column("admin_revision_snapshot", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest", name="uq_admin_sessions_token_digest"),
    )
    op.create_index("ix_admin_sessions_admin_id", "admin_sessions", ["admin_id"])
    op.create_index(
        "ix_admin_sessions_admin_expires",
        "admin_sessions",
        ["admin_id", "expires_at"],
    )

    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_actor_id", sa.Uuid(), nullable=True),
        sa.Column("admin_role_snapshot", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("request_ref", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["admin_actor_id"],
            ["admin_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_audit_events_admin_actor_id",
        "admin_audit_events",
        ["admin_actor_id"],
    )
    op.create_index(
        "ix_admin_audit_created_id",
        "admin_audit_events",
        ["created_at", "id"],
    )
    op.create_index(
        "ix_admin_audit_actor_created",
        "admin_audit_events",
        ["admin_actor_id", "created_at"],
    )
    op.create_index(
        "ix_admin_audit_action_created",
        "admin_audit_events",
        ["action", "created_at"],
    )

    # PostgreSQL protects the audit table itself from accidental ORM/admin-console
    # mutation. V1 intentionally exposes no update/delete API for audit records.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION jiyi_admin_audit_append_only() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'ADMIN_AUDIT_APPEND_ONLY';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_admin_audit_append_only
            BEFORE UPDATE OR DELETE ON admin_audit_events
            FOR EACH ROW EXECUTE FUNCTION jiyi_admin_audit_append_only()
            """
        )

    op.create_table(
        "entitlement_quota_policies",
        sa.Column("plan_code", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("ai_provider_requests", sa.BigInteger(), nullable=False),
        sa.Column("ai_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("ai_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("updated_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "plan_code IN ('FREE','PERSONAL','FAMILY','PREMIUM')",
            name="ck_entitlement_quota_policy_plan",
        ),
        sa.CheckConstraint("revision >= 0", name="ck_entitlement_quota_policy_revision"),
        sa.CheckConstraint("storage_bytes >= 0", name="ck_entitlement_quota_storage"),
        sa.CheckConstraint(
            "ai_provider_requests >= 0",
            name="ck_entitlement_quota_ai_requests",
        ),
        sa.CheckConstraint("ai_input_tokens >= 0", name="ck_entitlement_quota_input"),
        sa.CheckConstraint("ai_output_tokens >= 0", name="ck_entitlement_quota_output"),
        sa.ForeignKeyConstraint(
            ["updated_by_admin_id"],
            ["admin_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("plan_code"),
    )


def downgrade() -> None:
    op.drop_table("entitlement_quota_policies")

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_admin_audit_append_only ON admin_audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS jiyi_admin_audit_append_only()")

    op.drop_index("ix_admin_audit_action_created", table_name="admin_audit_events")
    op.drop_index("ix_admin_audit_actor_created", table_name="admin_audit_events")
    op.drop_index("ix_admin_audit_created_id", table_name="admin_audit_events")
    op.drop_index(
        "ix_admin_audit_events_admin_actor_id",
        table_name="admin_audit_events",
    )
    op.drop_table("admin_audit_events")

    op.drop_index("ix_admin_sessions_admin_expires", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_admin_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")

    op.drop_index("ix_admin_accounts_email", table_name="admin_accounts")
    op.drop_table("admin_accounts")
