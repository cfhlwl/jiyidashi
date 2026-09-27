"""add V2 Life Event foundation

Revision ID: 0023_life_event_foundation
Revises: 0022_person_relationship_graph
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_life_event_foundation"
down_revision: str | None = "0022_person_relationship_graph"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "life_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_kind",
            sa.Enum(
                "TRAVEL",
                "MEDICAL",
                "GATHERING",
                "WORK",
                "EDUCATION",
                "FAMILY",
                "OTHER",
                name="lifeeventkind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("custom_label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("place_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["place_id", "user_id"],
            ["places.id", "places.user_id"],
            name="fk_life_events_place_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_life_events_id_user_id"),
    )
    op.create_index("ix_life_events_user_id", "life_events", ["user_id"])
    op.create_index(
        "ix_life_events_user_started",
        "life_events",
        ["user_id", "started_at"],
    )
    op.create_index(
        "ix_life_events_user_kind",
        "life_events",
        ["user_id", "event_kind"],
    )

    op.create_table(
        "life_event_memory_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("life_event_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["life_event_id", "user_id"],
            ["life_events.id", "life_events.user_id"],
            name="fk_life_event_memory_links_event_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id", "user_id"],
            ["memories.id", "memories.user_id"],
            name="fk_life_event_memory_links_memory_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "life_event_id",
            "memory_id",
            name="uq_life_event_memory_links_event_memory",
        ),
    )
    op.create_index(
        "ix_life_event_memory_links_user_id",
        "life_event_memory_links",
        ["user_id"],
    )
    op.create_index(
        "ix_life_event_memory_links_life_event_id",
        "life_event_memory_links",
        ["life_event_id"],
    )
    op.create_index(
        "ix_life_event_memory_links_memory_id",
        "life_event_memory_links",
        ["memory_id"],
    )
    op.create_index(
        "ix_life_event_memory_links_user_event",
        "life_event_memory_links",
        ["user_id", "life_event_id"],
    )
    op.create_index(
        "ix_life_event_memory_links_user_memory",
        "life_event_memory_links",
        ["user_id", "memory_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_life_event_memory_links_user_memory",
        table_name="life_event_memory_links",
    )
    op.drop_index(
        "ix_life_event_memory_links_user_event",
        table_name="life_event_memory_links",
    )
    op.drop_index(
        "ix_life_event_memory_links_memory_id",
        table_name="life_event_memory_links",
    )
    op.drop_index(
        "ix_life_event_memory_links_life_event_id",
        table_name="life_event_memory_links",
    )
    op.drop_index(
        "ix_life_event_memory_links_user_id",
        table_name="life_event_memory_links",
    )
    op.drop_table("life_event_memory_links")

    op.drop_index("ix_life_events_user_kind", table_name="life_events")
    op.drop_index("ix_life_events_user_started", table_name="life_events")
    op.drop_index("ix_life_events_user_id", table_name="life_events")
    op.drop_table("life_events")
