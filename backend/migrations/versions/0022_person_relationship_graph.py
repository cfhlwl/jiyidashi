"""add V2 Person Relationship Graph

Revision ID: 0022_person_relationship_graph
Revises: 0021_person_memory_links
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_person_relationship_graph"
down_revision: str | None = "0021_person_memory_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("person_low_id", sa.Uuid(), nullable=False),
        sa.Column("person_high_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relationship_kind",
            sa.Enum(
                "FAMILY",
                "FRIEND",
                "COLLEAGUE",
                "CLASSMATE",
                "OTHER",
                name="personrelationshipkind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("custom_label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "person_low_id <> person_high_id",
            name="ck_person_relationships_no_self_edge",
        ),
        sa.CheckConstraint(
            "person_low_id < person_high_id",
            name="ck_person_relationships_canonical_order",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_low_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_relationships_low_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_high_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_relationships_high_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "person_low_id",
            "person_high_id",
            name="uq_person_relationships_owner_pair",
        ),
    )
    op.create_index(
        "ix_person_relationships_user_id",
        "person_relationships",
        ["user_id"],
    )
    op.create_index(
        "ix_person_relationships_person_low_id",
        "person_relationships",
        ["person_low_id"],
    )
    op.create_index(
        "ix_person_relationships_person_high_id",
        "person_relationships",
        ["person_high_id"],
    )
    op.create_index(
        "ix_person_relationships_user_low",
        "person_relationships",
        ["user_id", "person_low_id"],
    )
    op.create_index(
        "ix_person_relationships_user_high",
        "person_relationships",
        ["user_id", "person_high_id"],
    )
    op.create_index(
        "ix_person_relationships_user_kind",
        "person_relationships",
        ["user_id", "relationship_kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_person_relationships_user_kind", table_name="person_relationships")
    op.drop_index("ix_person_relationships_user_high", table_name="person_relationships")
    op.drop_index("ix_person_relationships_user_low", table_name="person_relationships")
    op.drop_index(
        "ix_person_relationships_person_high_id",
        table_name="person_relationships",
    )
    op.drop_index(
        "ix_person_relationships_person_low_id",
        table_name="person_relationships",
    )
    op.drop_index("ix_person_relationships_user_id", table_name="person_relationships")
    op.drop_table("person_relationships")
