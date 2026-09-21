"""add S3-009 Memory embedding derived index

Revision ID: 0013_memory_embedding
Revises: 0012_pgvector_foundation
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

# Historical migration contract: never import mutable application policy/helpers here.
EMBEDDING_DIMENSIONS = 1536

revision: str = "0013_memory_embedding"
down_revision: str | None = "0012_pgvector_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
    dialect = _dialect_name()
    if dialect == "sqlite":
        # SQLite remains a non-vector unit/development path. S3-009 persistence is
        # PostgreSQL-only rather than silently storing fake vectors in JSON/TEXT.
        return
    if dialect != "postgresql":
        raise RuntimeError(f"PGVECTOR_DATABASE_UNSUPPORTED: {dialect}")

    # [人工注释][S3-009] PostgreSQL 的复合 FK 要求被引用列组合本身唯一。
    # id 虽已是 PK，这个显式复合约束用于冻结 owner-binding 数据库契约。
    op.create_unique_constraint(
        "uq_memories_id_user_id",
        "memories",
        ["id", "user_id"],
    )

    op.create_table(
        "memory_embeddings",
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_revision", sa.Integer(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("provider_request_id", sa.String(length=160), nullable=True),
        sa.Column(
            "embedding",
            VECTOR(EMBEDDING_DIMENSIONS),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"dimensions = {EMBEDDING_DIMENSIONS}",
            name="ck_memory_embeddings_dimensions",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id", "user_id"],
            ["memories.id", "memories.user_id"],
            name="fk_memory_embeddings_memory_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("memory_id"),
    )
    op.create_index(
        "ix_memory_embeddings_user_id",
        "memory_embeddings",
        ["user_id"],
        unique=False,
    )
    # HNSW is a derived retrieval accelerator only. S3-009 creates no search endpoint,
    # and later retrieval must still resolve candidates through authoritative Memory/Evidence.
    op.create_index(
        "ix_memory_embeddings_embedding_hnsw",
        "memory_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    dialect = _dialect_name()
    if dialect == "sqlite":
        return
    if dialect != "postgresql":
        raise RuntimeError(f"PGVECTOR_DATABASE_UNSUPPORTED: {dialect}")

    op.drop_index(
        "ix_memory_embeddings_embedding_hnsw",
        table_name="memory_embeddings",
    )
    op.drop_index("ix_memory_embeddings_user_id", table_name="memory_embeddings")
    op.drop_table("memory_embeddings")
    op.drop_constraint(
        "uq_memories_id_user_id",
        "memories",
        type_="unique",
    )
    # The shared vector extension belongs to S3-008 and is intentionally retained.
