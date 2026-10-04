"""add durable provider runtime configuration

Revision ID: 0030_provider_configuration
Revises: 0029_auth_persistent_session
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_provider_configuration"
down_revision: str | None = "0029_auth_persistent_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_configurations",
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("max_input_chars", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("min_confidence", sa.Float(), nullable=True),
        sa.Column("credential_override", sa.Boolean(), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "service IN ('AI','ASR','EMBEDDING')",
            name="ck_provider_config_service",
        ),
        sa.CheckConstraint(
            "provider_type IN ('openai')",
            name="ck_provider_config_type",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_provider_config_revision",
        ),
        sa.CheckConstraint(
            "timeout_seconds >= 1 AND timeout_seconds <= 120",
            name="ck_provider_config_timeout",
        ),
        sa.CheckConstraint(
            "max_input_chars IS NULL OR max_input_chars > 0",
            name="ck_provider_config_input_limit",
        ),
        sa.CheckConstraint(
            "max_output_tokens IS NULL OR max_output_tokens > 0",
            name="ck_provider_config_output_limit",
        ),
        sa.CheckConstraint(
            "min_confidence IS NULL OR (min_confidence >= 0 AND min_confidence <= 1)",
            name="ck_provider_config_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_admin_id"],
            ["admin_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("service"),
    )


    op.create_table(
        "provider_runtime_evidence",
        sa.Column("service", sa.String(length=32), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "service IN ('AI','ASR','EMBEDDING')",
            name="ck_provider_runtime_evidence_service",
        ),
        sa.PrimaryKeyConstraint("service", "config_fingerprint"),
    )
    op.create_index(
        "ix_provider_runtime_evidence_service_updated",
        "provider_runtime_evidence",
        ["service", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_runtime_evidence_service_updated",
        table_name="provider_runtime_evidence",
    )
    op.drop_table("provider_runtime_evidence")
    op.drop_table("provider_configurations")
