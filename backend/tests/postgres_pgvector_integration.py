"""PostgreSQL integration gate for the S3-008 pgvector Foundation."""

from __future__ import annotations

import os
import subprocess
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import Memory, MemorySource, SourceType, User
from app.vector_support import inspect_vector_capability

DATABASE_URL = os.environ["DATABASE_URL"]


def _database_url() -> str:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("pgvector integration check requires a PostgreSQL DATABASE_URL")
    return DATABASE_URL


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def _schema_signature(engine) -> tuple[tuple[object, ...], ...]:
    with engine.connect() as connection:
        return tuple(
            tuple(row)
            for row in connection.execute(
                text(
                    """
                    SELECT table_name, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name NOT IN ('alembic_version', 'memory_embeddings')
                    ORDER BY table_name, ordinal_position
                    """
                )
            )
        )


def _assert_vector_ready(engine) -> str:
    with engine.connect() as connection:
        capability = inspect_vector_capability(connection)
        assert capability.available is True
        assert capability.extension_version
        rendered = connection.execute(text("SELECT '[1,2,3]'::vector::text")).scalar_one()
        assert rendered == "[1,2,3]"
        return capability.extension_version


def main() -> None:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    user_id = uuid4()
    memory_id = uuid4()

    # The preceding clean PostgreSQL migration baseline must have enabled vector already.
    extension_version = _assert_vector_ready(engine)
    schema_at_head = _schema_signature(engine)

    with Session(engine) as db:
        db.add(User(id=user_id, nickname="pgvector-migration-sentinel"))
        db.commit()
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                content="S3-008 must not rewrite existing Memory rows",
                source_type=SourceType.USER_TEXT,
                is_confirmed=True,
            )
        )
        db.commit()
        db.add(
            MemorySource(
                memory_id=memory_id,
                source_type=SourceType.USER_TEXT,
                raw_text="pgvector migration sentinel evidence",
                confidence=1.0,
            )
        )
        db.commit()

    try:
        # [人工注释][S3-008] downgrade 只回退本应用的 revision ownership；
        # database-level vector extension 必须保留，避免误删同库其他 schema 的共享能力。
        _alembic("downgrade", "0011_place_naming")
        assert _schema_signature(engine) == schema_at_head
        assert _assert_vector_ready(engine) == extension_version

        with Session(engine) as db:
            memory = db.get(Memory, memory_id)
            assert memory is not None
            assert memory.content == "S3-008 must not rewrite existing Memory rows"
            source_count = db.scalar(
                text("SELECT count(*) FROM memory_sources WHERE memory_id = :memory_id"),
                {"memory_id": memory_id},
            )
            assert source_count == 1

        # Re-upgrade must be safe with the retained extension (CREATE EXTENSION IF NOT EXISTS).
        _alembic("upgrade", "head")
        assert _schema_signature(engine) == schema_at_head
        assert _assert_vector_ready(engine) == extension_version

        with Session(engine) as db:
            memory = db.get(Memory, memory_id)
            assert memory is not None
            assert memory.content == "S3-008 must not rewrite existing Memory rows"
    finally:
        # Always return the shared CI database to migration head before later gates execute.
        _alembic("upgrade", "head")
        with Session(engine) as db:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
                db.commit()
        engine.dispose()

    print(f"PostgreSQL pgvector foundation PASS (extension {extension_version})")


if __name__ == "__main__":
    main()
