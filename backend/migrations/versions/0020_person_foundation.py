"""add V2 Person foundation

Revision ID: 0020_person_foundation
Revises: 0019_elder_mode_foundation
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_person_foundation"
down_revision: str | None = "0019_elder_mode_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("relationship_label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_persons_id_user_id"),
    )
    op.create_index("ix_persons_user_id", "persons", ["user_id"])
    op.create_index(
        "ix_persons_user_display_name",
        "persons",
        ["user_id", "display_name"],
    )

    op.create_table(
        "person_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("normalized_alias", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id", "user_id"],
            ["persons.id", "persons.user_id"],
            name="fk_person_aliases_person_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "person_id", "normalized_alias", name="uq_person_aliases_person_normalized"
        ),
    )
    op.create_index("ix_person_aliases_user_id", "person_aliases", ["user_id"])
    op.create_index("ix_person_aliases_person_id", "person_aliases", ["person_id"])
    op.create_index(
        "ix_person_aliases_user_alias",
        "person_aliases",
        ["user_id", "normalized_alias"],
    )


def downgrade() -> None:
    op.drop_index("ix_person_aliases_user_alias", table_name="person_aliases")
    op.drop_index("ix_person_aliases_person_id", table_name="person_aliases")
    op.drop_index("ix_person_aliases_user_id", table_name="person_aliases")
    op.drop_table("person_aliases")
    op.drop_index("ix_persons_user_display_name", table_name="persons")
    op.drop_index("ix_persons_user_id", table_name="persons")
    op.drop_table("persons")
