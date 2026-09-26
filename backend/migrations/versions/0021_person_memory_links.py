"""add V2 Person Memory Links

Revision ID: 0021_person_memory_links
Revises: 0020_person_foundation
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_person_memory_links"
down_revision: str | None = "0020_person_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "person_memory_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relation_kind",
            sa.Enum("RELATED", "MET", name="personmemoryrelationkind", native_enum=False),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_memory_links_person_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id", "user_id"],
            ["memories.id", "memories.user_id"],
            name="fk_person_memory_links_memory_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id",
            "memory_id",
            name="uq_person_memory_links_person_memory",
        ),
    )
    op.create_index(
        "ix_person_memory_links_user_id",
        "person_memory_links",
        ["user_id"],
    )
    op.create_index(
        "ix_person_memory_links_person_id",
        "person_memory_links",
        ["person_id"],
    )
    op.create_index(
        "ix_person_memory_links_memory_id",
        "person_memory_links",
        ["memory_id"],
    )
    op.create_index(
        "ix_person_memory_links_user_person",
        "person_memory_links",
        ["user_id", "person_id"],
    )
    op.create_index(
        "ix_person_memory_links_user_relation",
        "person_memory_links",
        ["user_id", "relation_kind"],
    )
    op.create_index(
        "ix_person_memory_links_user_memory",
        "person_memory_links",
        ["user_id", "memory_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_person_memory_links_user_memory", table_name="person_memory_links")
    op.drop_index("ix_person_memory_links_user_relation", table_name="person_memory_links")
    op.drop_index("ix_person_memory_links_user_person", table_name="person_memory_links")
    op.drop_index("ix_person_memory_links_memory_id", table_name="person_memory_links")
    op.drop_index("ix_person_memory_links_person_id", table_name="person_memory_links")
    op.drop_index("ix_person_memory_links_user_id", table_name="person_memory_links")
    op.drop_table("person_memory_links")
