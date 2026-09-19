"""add stage2 location/visit derivation foundation

Revision ID: 0010_location_visit
Revises: 0009_account_deletion
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_location_visit"
down_revision: str | None = "0009_account_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # [人工注释][S2-008] 旧 Place 继续合法存在；只有自动位置派生 Place 才写 cluster_key。
    # nullable + owner-scoped unique 允许无 cluster_key 的历史/未来人工 Place 共存。
    with op.batch_alter_table("places") as batch_op:
        batch_op.add_column(sa.Column("cluster_key", sa.String(length=16), nullable=True))
        batch_op.create_unique_constraint(
            "uq_places_user_cluster_key",
            ["user_id", "cluster_key"],
        )

    # [人工注释][S2-007][S2-014] Visit 把 source 时间边界/点数/fingerprint 固化在派生行上，
    # raw LocationPoint 后续按 retention 清理后，长期 Visit 仍不依赖已删除行才能解释来源。
    with op.batch_alter_table("visits") as batch_op:
        batch_op.add_column(sa.Column("derivation_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("centroid_latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("centroid_longitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("source_point_count", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("source_started_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("source_ended_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("source_fingerprint", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("algorithm_version", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_unique_constraint(
            "uq_visits_user_derivation_key",
            ["user_id", "derivation_key"],
        )
        batch_op.create_index(
            "ix_visits_user_arrived",
            ["user_id", "arrived_at"],
            unique=False,
        )

    op.create_table(
        "location_derivation_states",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("finalized_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("location_derivation_states")

    with op.batch_alter_table("visits") as batch_op:
        batch_op.drop_index("ix_visits_user_arrived")
        batch_op.drop_constraint("uq_visits_user_derivation_key", type_="unique")
        batch_op.drop_column("finalized_at")
        batch_op.drop_column("algorithm_version")
        batch_op.drop_column("source_fingerprint")
        batch_op.drop_column("source_ended_at")
        batch_op.drop_column("source_started_at")
        batch_op.drop_column("source_point_count")
        batch_op.drop_column("centroid_longitude")
        batch_op.drop_column("centroid_latitude")
        batch_op.drop_column("derivation_key")

    with op.batch_alter_table("places") as batch_op:
        batch_op.drop_constraint("uq_places_user_cluster_key", type_="unique")
        batch_op.drop_column("cluster_key")
