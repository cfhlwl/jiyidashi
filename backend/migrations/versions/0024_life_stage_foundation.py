"""add V2 Life Stage foundation

Revision ID: 0024_life_stage_foundation
Revises: 0023_life_event_foundation
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_life_stage_foundation"
down_revision: str | None = "0023_life_event_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "life_stages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "stage_kind",
            sa.Enum(
                "WORK",
                "EDUCATION",
                "FAMILY",
                "RESIDENCE",
                "TRAVEL",
                "OTHER",
                name="lifestagekind",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("custom_label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_life_stages_id_user_id"),
    )
    op.create_index("ix_life_stages_user_id", "life_stages", ["user_id"])
    op.create_index(
        "ix_life_stages_user_started",
        "life_stages",
        ["user_id", "started_at"],
    )
    op.create_index(
        "ix_life_stages_user_kind",
        "life_stages",
        ["user_id", "stage_kind"],
    )

    op.create_table(
        "life_stage_event_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("life_stage_id", sa.Uuid(), nullable=False),
        sa.Column("life_event_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["life_stage_id", "user_id"],
            ["life_stages.id", "life_stages.user_id"],
            name="fk_life_stage_event_links_stage_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["life_event_id", "user_id"],
            ["life_events.id", "life_events.user_id"],
            name="fk_life_stage_event_links_event_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "life_stage_id",
            "life_event_id",
            name="uq_life_stage_event_links_stage_event",
        ),
    )
    op.create_index(
        "ix_life_stage_event_links_user_id",
        "life_stage_event_links",
        ["user_id"],
    )
    op.create_index(
        "ix_life_stage_event_links_life_stage_id",
        "life_stage_event_links",
        ["life_stage_id"],
    )
    op.create_index(
        "ix_life_stage_event_links_life_event_id",
        "life_stage_event_links",
        ["life_event_id"],
    )
    op.create_index(
        "ix_life_stage_event_links_user_stage",
        "life_stage_event_links",
        ["user_id", "life_stage_id"],
    )
    op.create_index(
        "ix_life_stage_event_links_user_event",
        "life_stage_event_links",
        ["user_id", "life_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_life_stage_event_links_user_event",
        table_name="life_stage_event_links",
    )
    op.drop_index(
        "ix_life_stage_event_links_user_stage",
        table_name="life_stage_event_links",
    )
    op.drop_index(
        "ix_life_stage_event_links_life_event_id",
        table_name="life_stage_event_links",
    )
    op.drop_index(
        "ix_life_stage_event_links_life_stage_id",
        table_name="life_stage_event_links",
    )
    op.drop_index(
        "ix_life_stage_event_links_user_id",
        table_name="life_stage_event_links",
    )
    op.drop_table("life_stage_event_links")

    op.drop_index("ix_life_stages_user_kind", table_name="life_stages")
    op.drop_index("ix_life_stages_user_started", table_name="life_stages")
    op.drop_index("ix_life_stages_user_id", table_name="life_stages")
    op.drop_table("life_stages")
