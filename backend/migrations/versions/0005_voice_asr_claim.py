"""add durable ASR single-flight claims

Revision ID: 0005_voice_asr_claim
Revises: 0004_stage1_media
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_voice_asr_claim"
down_revision: str | None = "0004_stage1_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # [人工注释][S1-PR18-FIX-002][S1-007] 同一 READY audio 的 provider side effect
    # 通过 durable claim 单飞；租约独立于 media READY 状态，进程异常后可过期恢复。
    op.create_table(
        "media_asr_claims",
        sa.Column("media_id", sa.Uuid(), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media_assets.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("media_id"),
    )


def downgrade() -> None:
    op.drop_table("media_asr_claims")
