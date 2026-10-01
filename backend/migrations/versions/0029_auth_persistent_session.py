"""add persistent public auth sessions and one-time tokens

Revision ID: 0029_auth_persistent_session
Revises: 0028_admin_console
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_auth_persistent_session"
down_revision: str | None = "0028_admin_console"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "auth_identities",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing production identities predate AUTH-001 and are migration-compatible:
    # keep them usable instead of silently locking every existing account.
    op.execute(
        "UPDATE auth_identities SET verified_at = created_at "
        "WHERE provider = 'EMAIL_PASSWORD' AND verified_at IS NULL"
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("refresh_digest", sa.String(length=64), nullable=False),
        sa.Column("rotation_revision", sa.Integer(), nullable=False),
        sa.Column("client_platform", sa.String(length=32), nullable=True),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.CheckConstraint("rotation_revision >= 0", name="ck_auth_sessions_rotation"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("refresh_digest", name="uq_auth_sessions_refresh_digest"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index(
        "ix_auth_sessions_user_expires",
        "auth_sessions",
        ["user_id", "expires_at"],
    )
    # Pre-0029 access JWTs contain only sub/iat/exp.  Their user UUID is the
    # deterministic compatibility session ID; the JWT's original exp still
    # bounds access, while this row preserves the new durable-session check.
    op.execute(
        """
        INSERT INTO auth_sessions (
            id, user_id, device_id, refresh_digest, rotation_revision,
            client_platform, device_name, created_at, last_used_at, expires_at
        )
        SELECT
            id,
            id,
            'legacy-access-token',
            replace(id::text, '-', '') || replace(id::text, '-', ''),
            0,
            'legacy',
            'Pre-session access token',
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP + INTERVAL '30 days'
        FROM users
        """
    )

    op.create_table(
        "auth_refresh_token_receipts",
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("rotation_revision", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rotation_revision >= 0",
            name="ck_auth_refresh_receipts_rotation",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["auth_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("digest"),
    )
    op.create_index(
        "ix_auth_refresh_receipts_session",
        "auth_refresh_token_receipts",
        ["session_id", "consumed_at"],
    )

    op.create_table(
        "auth_one_time_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "EMAIL_VERIFY",
                "PASSWORD_RESET",
                name="authonetimepurpose",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("digest", name="uq_auth_one_time_tokens_digest"),
    )
    op.create_index(
        "ix_auth_one_time_tokens_user_id",
        "auth_one_time_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_auth_one_time_user_purpose",
        "auth_one_time_tokens",
        ["user_id", "purpose", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_one_time_user_purpose", table_name="auth_one_time_tokens")
    op.drop_index("ix_auth_one_time_tokens_user_id", table_name="auth_one_time_tokens")
    op.drop_table("auth_one_time_tokens")

    op.drop_index(
        "ix_auth_refresh_receipts_session",
        table_name="auth_refresh_token_receipts",
    )
    op.drop_table("auth_refresh_token_receipts")

    op.drop_index("ix_auth_sessions_user_expires", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_column("auth_identities", "verified_at")
    op.drop_column("users", "auth_disabled_at")
