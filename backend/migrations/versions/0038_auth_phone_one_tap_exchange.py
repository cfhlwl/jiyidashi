"""add durable phone one-tap exchange authority

Revision ID: 0038_auth_phone_one_tap_exchange
Revises: 0037_auth_identity_foundation
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038_auth_phone_one_tap_exchange"
down_revision: str | None = "0037_auth_identity_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_phone_one_tap_exchanges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("token_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_key_version", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("recovery_state", sa.String(length=16), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("client_platform", sa.String(length=32), nullable=True),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("resolved_user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("replacement_session_id", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("recovery_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resolved_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["replacement_session_id"], ["auth_sessions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_phone_one_tap_request_id"),
        sa.UniqueConstraint(
            "token_fingerprint", name="uq_phone_one_tap_token_fingerprint"
        ),
        sa.CheckConstraint(
            "state IN ('RESERVED', 'COMPLETED', 'PROVIDER_REJECTED', 'PROVIDER_UNKNOWN')",
            name="ck_phone_one_tap_exchange_state",
        ),
        sa.CheckConstraint(
            "recovery_state IN ('OPEN', 'CLOSED')",
            name="ck_phone_one_tap_recovery_state",
        ),
    )
    op.create_index(
        "ix_phone_one_tap_state_expires",
        "auth_phone_one_tap_exchanges",
        ["state", "expires_at"],
    )
    op.create_index(
        "ix_phone_one_tap_lease",
        "auth_phone_one_tap_exchanges",
        ["state", "lease_expires_at"],
    )
    op.create_index(
        "ix_phone_one_tap_created",
        "auth_phone_one_tap_exchanges",
        ["created_at"],
    )
    op.create_index(
        "ix_auth_phone_one_tap_exchanges_resolved_user_id",
        "auth_phone_one_tap_exchanges",
        ["resolved_user_id"],
    )
    op.create_index(
        "ix_auth_phone_one_tap_exchanges_session_id",
        "auth_phone_one_tap_exchanges",
        ["session_id"],
    )
    op.create_index(
        "ix_auth_phone_one_tap_exchanges_replacement_session_id",
        "auth_phone_one_tap_exchanges",
        ["replacement_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_phone_one_tap_exchanges_replacement_session_id",
        table_name="auth_phone_one_tap_exchanges",
    )
    op.drop_index(
        "ix_auth_phone_one_tap_exchanges_session_id",
        table_name="auth_phone_one_tap_exchanges",
    )
    op.drop_index(
        "ix_auth_phone_one_tap_exchanges_resolved_user_id",
        table_name="auth_phone_one_tap_exchanges",
    )
    op.drop_index("ix_phone_one_tap_created", table_name="auth_phone_one_tap_exchanges")
    op.drop_index("ix_phone_one_tap_lease", table_name="auth_phone_one_tap_exchanges")
    op.drop_index(
        "ix_phone_one_tap_state_expires", table_name="auth_phone_one_tap_exchanges"
    )
    op.drop_table("auth_phone_one_tap_exchanges")
