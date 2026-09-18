"""add client mutation idempotency ledger

Revision ID: 0006_client_mutations
Revises: 0005_voice_asr_claim
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_client_mutations"
down_revision: str | None = "0005_voice_asr_claim"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # response-loss 后客户端会携带同一个 client_uuid 重试；
    # 数据库唯一键负责跨请求/并发最终去重，业务资源与账本必须在同一事务提交。
    op.create_table(
        "client_mutations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_type", sa.String(length=80), nullable=False),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "operation_type",
            "client_uuid",
            name="uq_client_mutations_user_operation_uuid",
        ),
    )
    op.create_index(
        op.f("ix_client_mutations_user_id"),
        "client_mutations",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_client_mutations_user_id"), table_name="client_mutations")
    op.drop_table("client_mutations")
