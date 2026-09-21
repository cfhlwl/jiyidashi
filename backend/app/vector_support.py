"""PostgreSQL pgvector capability seam for later Stage 3 storage models.

S3-008 exposes only infrastructure. No model in this revision owns a VECTOR column and
no embedding generation, nearest-neighbor retrieval, or RAG behavior belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import text
from sqlalchemy.engine import Connection

PGVECTOR_EXTENSION_NAME = "vector"


class VectorCapabilityError(RuntimeError):
    """The configured database cannot provide the required PostgreSQL vector capability."""


@dataclass(frozen=True)
class VectorCapability:
    available: bool
    extension_version: str | None


def vector_type(dimensions: int | None = None) -> VECTOR:
    """Return the SQLAlchemy pgvector type without choosing an embedding policy."""

    # [人工注释][S3-008] Foundation 只提供类型 seam，不定义默认 embedding 维度；
    # 具体模型/维度/供应商策略属于 S3-009，必须由后续 migration 显式拥有。
    if dimensions is not None and (
        isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0
    ):
        raise ValueError("VECTOR_DIMENSIONS_INVALID")
    return VECTOR(dimensions)


def inspect_vector_capability(connection: Connection) -> VectorCapability:
    """Inspect vector support without making SQLite depend on PostgreSQL extensions."""

    dialect = connection.dialect.name
    if dialect == "sqlite":
        return VectorCapability(available=False, extension_version=None)
    if dialect != "postgresql":
        raise VectorCapabilityError(f"PGVECTOR_DATABASE_UNSUPPORTED: {dialect}")

    version = connection.execute(
        text(
            "SELECT extversion FROM pg_extension "
            "WHERE extname = :extension_name"
        ),
        {"extension_name": PGVECTOR_EXTENSION_NAME},
    ).scalar_one_or_none()
    if version is None:
        # [人工注释][S3-008] 生产 PostgreSQL 若 migration 未能启用 extension 必须明确失败，
        # 不能静默退化成文本/JSON 假向量，否则后续 S3-009 会产生不可验证的数据路径。
        raise VectorCapabilityError("PGVECTOR_EXTENSION_UNAVAILABLE")
    return VectorCapability(available=True, extension_version=str(version))
