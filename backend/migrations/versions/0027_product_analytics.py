"""add retrieval and retention analytics foundation

Revision ID: 0027_product_analytics
Revises: 0026_entitlement_quota
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_product_analytics"
down_revision: str | None = "0026_entitlement_quota"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "retrieval_analytics_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "surface",
            sa.Enum(
                "MEMORY_QUERY",
                "STRUCTURED_RETRIEVAL",
                "MEMORY_RAG",
                name="retrievalsurface",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "SUCCESS",
                "NO_EVIDENCE",
                "FAILED",
                name="retrievaloutcome",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("answerable_count", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result_count >= 0 AND result_count <= 10000",
            name="ck_retrieval_analytics_result_count",
        ),
        sa.CheckConstraint(
            "answerable_count >= 0 AND answerable_count <= 10000",
            name="ck_retrieval_analytics_answerable_count",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "operation_id",
            "surface",
            name="uq_retrieval_analytics_user_operation_surface",
        ),
    )
    op.create_index(
        "ix_retrieval_analytics_attempts_user_id",
        "retrieval_analytics_attempts",
        ["user_id"],
    )
    op.create_index(
        "ix_retrieval_analytics_attempts_outcome",
        "retrieval_analytics_attempts",
        ["outcome"],
    )
    op.create_index(
        "ix_retrieval_analytics_occurred",
        "retrieval_analytics_attempts",
        ["occurred_at"],
    )

    op.create_table(
        "product_active_days",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("activity_date_utc", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "activity_date_utc",
            name="uq_product_active_days_user_date",
        ),
    )
    op.create_index(
        "ix_product_active_days_user_id",
        "product_active_days",
        ["user_id"],
    )
    op.create_index(
        "ix_product_active_days_date",
        "product_active_days",
        ["activity_date_utc"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_active_days_date", table_name="product_active_days")
    op.drop_index("ix_product_active_days_user_id", table_name="product_active_days")
    op.drop_table("product_active_days")
    op.drop_index(
        "ix_retrieval_analytics_occurred",
        table_name="retrieval_analytics_attempts",
    )
    op.drop_index(
        "ix_retrieval_analytics_attempts_outcome",
        table_name="retrieval_analytics_attempts",
    )
    op.drop_index(
        "ix_retrieval_analytics_attempts_user_id",
        table_name="retrieval_analytics_attempts",
    )
    op.drop_table("retrieval_analytics_attempts")
