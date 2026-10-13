"""add isolated WeChat Mini Program identity exchange receipts

Revision ID: 0041_auth_wechat_miniprogram
Revises: 0040_auth_wechat_login_exchange
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041_auth_wechat_miniprogram"
down_revision: str | None = "0040_auth_wechat_login_exchange"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0002 created the provider projection with the length of
    # ``EMAIL_PASSWORD``.  The Mini Program provider value is longer, so widen
    # the existing VARCHAR before the metadata drift gate compares the schema.
    with op.batch_alter_table("auth_identities") as batch_op:
        batch_op.alter_column(
            "provider",
            existing_type=sa.String(length=14),
            type_=sa.String(length=18),
            existing_nullable=False,
        )

    op.create_table(
        "auth_wechat_miniprogram_exchanges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_key_version", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("client_platform", sa.String(length=32), nullable=True),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("resolved_user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resolved_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_wechat_miniprogram_request_id"),
        sa.UniqueConstraint(
            "credential_fingerprint",
            name="uq_wechat_miniprogram_credential_fingerprint",
        ),
        sa.CheckConstraint(
            "state IN ('RESERVED', 'COMPLETED', 'PROVIDER_REJECTED', 'PROVIDER_UNKNOWN')",
            name="ck_wechat_miniprogram_exchange_state",
        ),
    )
    op.create_index(
        "ix_wechat_miniprogram_state_expires",
        "auth_wechat_miniprogram_exchanges",
        ["state", "expires_at"],
    )
    op.create_index(
        "ix_wechat_miniprogram_lease",
        "auth_wechat_miniprogram_exchanges",
        ["state", "lease_expires_at"],
    )
    op.create_index(
        "ix_auth_wechat_miniprogram_exchanges_resolved_user_id",
        "auth_wechat_miniprogram_exchanges",
        ["resolved_user_id"],
    )
    op.create_index(
        "ix_auth_wechat_miniprogram_exchanges_session_id",
        "auth_wechat_miniprogram_exchanges",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_wechat_miniprogram_exchanges_session_id",
        table_name="auth_wechat_miniprogram_exchanges",
    )
    op.drop_index(
        "ix_auth_wechat_miniprogram_exchanges_resolved_user_id",
        table_name="auth_wechat_miniprogram_exchanges",
    )
    op.drop_index(
        "ix_wechat_miniprogram_lease",
        table_name="auth_wechat_miniprogram_exchanges",
    )
    op.drop_index(
        "ix_wechat_miniprogram_state_expires",
        table_name="auth_wechat_miniprogram_exchanges",
    )
    op.drop_table("auth_wechat_miniprogram_exchanges")
