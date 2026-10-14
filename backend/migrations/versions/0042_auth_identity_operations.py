"""add durable AUTH-005 identity mutation receipts

Revision ID: 0042_auth_identity_operations
Revises: 0041_auth_wechat_miniprogram
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_auth_identity_operations"
down_revision: str | None = "0041_auth_wechat_miniprogram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_identity_operations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_key_version", sa.String(length=16), nullable=False),
        sa.Column("operation_type", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=24), nullable=True),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("subject_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["auth_sessions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"], ["auth_identities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_auth_identity_operation_request_id"),
        sa.CheckConstraint(
            "operation_type IN ('LINK', 'UNLINK')",
            name="ck_auth_identity_operation_type",
        ),
        sa.CheckConstraint(
            "state IN ('RESERVED', 'COMPLETED', 'REJECTED')",
            name="ck_auth_identity_operation_state",
        ),
    )
    op.create_index(
        "ix_auth_identity_operation_user_created",
        "auth_identity_operations",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_auth_identity_operation_state_created",
        "auth_identity_operations",
        ["state", "created_at"],
    )
    op.create_index(
        "ix_auth_identity_operations_session_id",
        "auth_identity_operations",
        ["session_id"],
    )
    op.create_index(
        "ix_auth_identity_operations_identity_id",
        "auth_identity_operations",
        ["identity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_identity_operations_identity_id",
        table_name="auth_identity_operations",
    )
    op.drop_index(
        "ix_auth_identity_operations_session_id",
        table_name="auth_identity_operations",
    )
    op.drop_index(
        "ix_auth_identity_operation_state_created",
        table_name="auth_identity_operations",
    )
    op.drop_index(
        "ix_auth_identity_operation_user_created",
        table_name="auth_identity_operations",
    )
    op.drop_table("auth_identity_operations")
