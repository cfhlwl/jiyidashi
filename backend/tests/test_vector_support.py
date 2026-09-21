from __future__ import annotations

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql

from app.core.db import Base
from app.embedding_models import MemoryEmbedding
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS
from app.vector_support import inspect_vector_capability, vector_type


def test_vector_type_seam_has_no_embedding_dimension_policy():
    assert isinstance(vector_type(), VECTOR)
    assert str(vector_type().compile(dialect=postgresql.dialect())) == "VECTOR"
    assert str(vector_type(1536).compile(dialect=postgresql.dialect())) == "VECTOR(1536)"


def test_vector_type_rejects_invalid_dimensions():
    for dimensions in (0, -1, True, 1.5):
        try:
            vector_type(dimensions)  # type: ignore[arg-type]
        except ValueError as exc:
            assert str(exc) == "VECTOR_DIMENSIONS_INVALID"
        else:
            raise AssertionError(f"invalid dimension accepted: {dimensions!r}")


def test_sqlite_non_vector_path_remains_available():
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection:
            capability = inspect_vector_capability(connection)
    finally:
        engine.dispose()

    assert capability.available is False
    assert capability.extension_version is None


def test_s3_009_owns_exactly_one_reviewed_memory_vector_column():
    vector_columns = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, VECTOR)
    ]
    assert vector_columns == ["memory_embeddings.embedding"]
    assert MemoryEmbedding.__table__.c.embedding.type.dim == MEMORY_EMBEDDING_DIMENSIONS
