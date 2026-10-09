"""add provider-neutral SMS OTP challenge authority

Revision ID: 0039_auth_sms_otp
Revises: 0038_auth_phone_one_tap_exchange
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_auth_sms_otp"
down_revision: str | None = "0038_auth_phone_one_tap_exchange"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_sms_otp_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("active_key", sa.String(length=64), nullable=True),
        sa.Column("phone_subject", sa.String(length=32), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("code_key_version", sa.String(length=16), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("client_platform", sa.String(length=32), nullable=True),
        sa.Column("device_name", sa.String(length=120), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("resolved_user_id", sa.Uuid(), nullable=True),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["resolved_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_auth_sms_otp_request_id"),
        sa.UniqueConstraint("active_key", name="uq_auth_sms_otp_active_key"),
        sa.CheckConstraint(
            "state IN ('PENDING', 'VERIFIED', 'EXPIRED', 'LOCKED', 'PROVIDER_ERROR')",
            name="ck_auth_sms_otp_state",
        ),
    )
    op.create_index(
        "ix_auth_sms_otp_state_expires", "auth_sms_otp_challenges", ["state", "expires_at"]
    )
    op.create_index(
        "ix_auth_sms_otp_phone_created", "auth_sms_otp_challenges", ["phone_subject", "created_at"]
    )
    op.create_index(
        "ix_auth_sms_otp_challenges_resolved_user_id", "auth_sms_otp_challenges", ["resolved_user_id"]
    )
    op.create_index(
        "ix_auth_sms_otp_challenges_session_id", "auth_sms_otp_challenges", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sms_otp_challenges_session_id", table_name="auth_sms_otp_challenges")
    op.drop_index("ix_auth_sms_otp_challenges_resolved_user_id", table_name="auth_sms_otp_challenges")
    op.drop_index("ix_auth_sms_otp_phone_created", table_name="auth_sms_otp_challenges")
    op.drop_index("ix_auth_sms_otp_state_expires", table_name="auth_sms_otp_challenges")
    op.drop_table("auth_sms_otp_challenges")
