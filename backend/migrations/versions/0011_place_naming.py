"""add Stage 2Q Place naming and correction foundation

Revision ID: 0011_place_naming
Revises: 0010_location_visit
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_place_naming"
down_revision: str | None = "0010_location_visit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("places") as batch_op:
        batch_op.add_column(sa.Column("automatic_name", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column("automatic_name_source", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("user_name", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column(
                "name_revision",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column("name_updated_at", sa.DateTime(timezone=True), nullable=True)
        )

    places = sa.table(
        "places",
        sa.column("name", sa.String(length=200)),
        sa.column("automatic_name", sa.String(length=200)),
        sa.column("automatic_name_source", sa.String(length=64)),
        sa.column("user_name", sa.String(length=200)),
        sa.column("is_user_named", sa.Boolean()),
    )
    # [人工注释][S2-009][S2-010] 迁移不能把既有用户命名降级成自动候选；
    # 非用户命名但已有展示名的 legacy Place 才作为 LEGACY automatic candidate。
    op.execute(
        places.update()
        .where(places.c.is_user_named == sa.true())
        .values(user_name=places.c.name)
    )
    op.execute(
        places.update()
        .where(
            sa.and_(
                places.c.is_user_named == sa.false(),
                places.c.name != "未命名地点",
            )
        )
        .values(
            automatic_name=places.c.name,
            automatic_name_source="LEGACY",
        )
    )

    op.create_table(
        "place_name_corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("place_id", sa.Uuid(), nullable=False),
        sa.Column("client_uuid", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_user_name", sa.String(length=200), nullable=True),
        sa.Column("new_user_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["place_id"], ["places.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "place_id",
            "revision",
            name="uq_place_name_corrections_place_revision",
        ),
    )
    op.create_index(
        "ix_place_name_corrections_place_id",
        "place_name_corrections",
        ["place_id"],
        unique=False,
    )
    op.create_index(
        "ix_place_name_corrections_user_id",
        "place_name_corrections",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_place_name_corrections_user_created",
        "place_name_corrections",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_place_name_corrections_user_created",
        table_name="place_name_corrections",
    )
    op.drop_index(
        "ix_place_name_corrections_user_id",
        table_name="place_name_corrections",
    )
    op.drop_index(
        "ix_place_name_corrections_place_id",
        table_name="place_name_corrections",
    )
    op.drop_table("place_name_corrections")

    with op.batch_alter_table("places") as batch_op:
        batch_op.drop_column("name_updated_at")
        batch_op.drop_column("name_revision")
        batch_op.drop_column("user_name")
        batch_op.drop_column("automatic_name_source")
        batch_op.drop_column("automatic_name")
