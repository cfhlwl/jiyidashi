"""PostgreSQL integration gate for S3-009 Memory embedding/index lifecycle."""

from __future__ import annotations

import asyncio
import os
from threading import Barrier, Thread
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    SessionLocal,
    UserDataAdmission,
    UserDataRequestStale,
)
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.embedding_gateway import (
    DeterministicEmbeddingProvider,
    EmbeddingGateway,
    EmbeddingProviderResult,
    EmbeddingRequest,
)
from app.embedding_models import MemoryEmbedding
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL
from app.models import Memory, User
from app.schemas import MemoryUpdate
from app.services.data_deletion_service import delete_all_user_data
from app.services.embedding_service import (
    EmbeddingServiceError,
    generate_or_refresh_memory_embedding,
)
from app.services.memory_edit_service import edit_memory
from app.services.memory_service import get_memory_for_user, soft_delete_memory

DATABASE_URL = os.environ["DATABASE_URL"]


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        del prefix
        return iter(())

    def delete_object(self, object_key: str) -> None:
        del object_key


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=DATABASE_URL,
        embedding_provider="disabled",
        embedding_model=MEMORY_EMBEDDING_MODEL,
        embedding_dimensions=MEMORY_EMBEDDING_DIMENSIONS,
        embedding_timeout_seconds=5.0,
    )


def _gateway(provider) -> EmbeddingGateway:
    return EmbeddingGateway(_settings(), provider)


def _seed_user_memory(*, title: str, content: str) -> tuple[UUID, UUID]:
    user_id = uuid4()
    memory_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"embedding-{user_id.hex[:8]}"))
        db.flush()
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                title=title,
                content=content,
            )
        )
        db.commit()
    return user_id, memory_id


def _embedding_count(memory_id: UUID) -> int:
    with SessionLocal() as db:
        return int(
            db.scalar(
                select(func.count())
                .select_from(MemoryEmbedding)
                .where(MemoryEmbedding.memory_id == memory_id)
            )
            or 0
        )


def _assert_schema_and_hnsw_index() -> None:
    with SessionLocal() as db:
        rendered = db.scalar(
            text(
                """
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                WHERE c.relname = 'memory_embeddings'
                  AND a.attname = 'embedding'
                  AND a.attnum > 0
                """
            )
        )
        assert rendered == f"vector({MEMORY_EMBEDDING_DIMENSIONS})"

        indexdef = db.scalar(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND indexname = 'ix_memory_embeddings_embedding_hnsw'
                """
            )
        )
        assert isinstance(indexdef, str)
        normalized = indexdef.lower()
        assert "using hnsw" in normalized
        assert "vector_cosine_ops" in normalized


def _assert_database_rejects_cross_owner_embedding_row() -> None:
    owner_id, memory_id = _seed_user_memory(
        title="数据库 owner 约束",
        content="Memory 属于 owner A",
    )
    other_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=other_id, nickname="embedding-db-other-owner"))
        db.commit()

    with SessionLocal() as db:
        db.add(
            MemoryEmbedding(
                memory_id=memory_id,
                user_id=other_id,
                memory_revision=0,
                content_fingerprint="f" * 64,
                provider="constraint-test",
                model=MEMORY_EMBEDDING_MODEL,
                dimensions=MEMORY_EMBEDDING_DIMENSIONS,
                embedding=[0.01] * MEMORY_EMBEDDING_DIMENSIONS,
            )
        )
        try:
            db.commit()
            raise AssertionError("cross-owner MemoryEmbedding row unexpectedly committed")
        except IntegrityError:
            db.rollback()

    assert _embedding_count(memory_id) == 0
    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner_id))
        cleanup.delete(cleanup.get(User, other_id))
        cleanup.commit()


def _assert_idempotent_owner_scoped_refresh() -> None:
    user_id, memory_id = _seed_user_memory(
        title="护照位置",
        content="护照放在书房抽屉",
    )
    provider = DeterministicEmbeddingProvider()

    with SessionLocal() as db:
        first = asyncio.run(
            generate_or_refresh_memory_embedding(
                db,
                user_id=user_id,
                memory_id=memory_id,
                gateway=_gateway(provider),
            )
        )
    assert first.refreshed is True
    assert len(provider.requests) == 1
    assert provider.requests[0].text == (
        "memory_type=NOTE\n"
        "title=护照位置\n"
        "content=护照放在书房抽屉"
    )

    with SessionLocal() as db:
        second = asyncio.run(
            generate_or_refresh_memory_embedding(
                db,
                user_id=user_id,
                memory_id=memory_id,
                gateway=_gateway(provider),
            )
        )
    assert second.refreshed is False
    assert len(provider.requests) == 1
    assert _embedding_count(memory_id) == 1

    other_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=other_id, nickname="embedding-cross-owner"))
        db.commit()
    with SessionLocal() as db:
        try:
            asyncio.run(
                generate_or_refresh_memory_embedding(
                    db,
                    user_id=other_id,
                    memory_id=memory_id,
                    gateway=_gateway(provider),
                )
            )
            raise AssertionError("cross-owner embedding generation unexpectedly succeeded")
        except EmbeddingServiceError as exc:
            assert exc.code == "MEMORY_NOT_FOUND"
            db.rollback()
    assert len(provider.requests) == 1

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.delete(cleanup.get(User, other_id))
        cleanup.commit()


class _BarrierProvider:
    def __init__(self, barrier: Barrier):
        self.barrier = barrier

    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        await asyncio.to_thread(self.barrier.wait, 10)
        return EmbeddingProviderResult(
            vector=[0.003] * request.dimensions,
            provider="barrier",
            model=request.model,
        )


def _assert_concurrent_refresh_converges() -> None:
    user_id, memory_id = _seed_user_memory(
        title="并发",
        content="两个 worker 只能留下一个当前向量",
    )
    barrier = Barrier(2)
    results = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with SessionLocal() as db:
                result = asyncio.run(
                    generate_or_refresh_memory_embedding(
                        db,
                        user_id=user_id,
                        memory_id=memory_id,
                        gateway=_gateway(_BarrierProvider(barrier)),
                    )
                )
                results.append(result)
        except BaseException as exc:  # noqa: BLE001 - thread reports assertion failures
            errors.append(exc)

    first = Thread(target=worker, name="embedding-refresh-1")
    second = Thread(target=worker, name="embedding-refresh-2")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive()
    assert not second.is_alive()
    if errors:
        raise errors[0]

    assert len(results) == 2
    assert sum(1 for result in results if result.refreshed) == 1
    assert _embedding_count(memory_id) == 1

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


class _MutatingProvider:
    def __init__(self, memory_id: UUID):
        self.memory_id = memory_id

    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        with SessionLocal() as db:
            memory = db.get(Memory, self.memory_id)
            assert memory is not None
            memory.content = "provider I/O 期间内容已经变化"
            memory.edit_revision += 1
            db.commit()
        return EmbeddingProviderResult(
            vector=[0.004] * request.dimensions,
            provider="mutating",
            model=request.model,
        )


def _assert_memory_change_blocks_stale_vector() -> None:
    user_id, memory_id = _seed_user_memory(
        title="竞态",
        content="旧正文",
    )
    with SessionLocal() as db:
        try:
            asyncio.run(
                generate_or_refresh_memory_embedding(
                    db,
                    user_id=user_id,
                    memory_id=memory_id,
                    gateway=_gateway(_MutatingProvider(memory_id)),
                )
            )
            raise AssertionError("stale embedding unexpectedly persisted")
        except EmbeddingServiceError as exc:
            assert exc.code == "MEMORY_CHANGED_DURING_EMBEDDING"
            db.rollback()
    assert _embedding_count(memory_id) == 0

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


def _assert_edit_and_soft_delete_invalidate() -> None:
    user_id, memory_id = _seed_user_memory(
        title="编辑失效",
        content="第一版",
    )
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        asyncio.run(
            generate_or_refresh_memory_embedding(
                db,
                user_id=user_id,
                memory_id=memory_id,
                gateway=_gateway(provider),
            )
        )
    assert _embedding_count(memory_id) == 1

    with SessionLocal() as db:
        edited = edit_memory(
            db,
            user_id=user_id,
            memory_id=memory_id,
            payload=MemoryUpdate(expected_revision=0, content="第二版"),
        )
        assert edited is not None
        db.commit()
    assert _embedding_count(memory_id) == 0

    with SessionLocal() as db:
        asyncio.run(
            generate_or_refresh_memory_embedding(
                db,
                user_id=user_id,
                memory_id=memory_id,
                gateway=_gateway(provider),
            )
        )
    assert _embedding_count(memory_id) == 1

    with SessionLocal() as db:
        memory = get_memory_for_user(db, user_id, memory_id, for_update=True)
        assert memory is not None
        soft_delete_memory(db, memory)
        db.commit()
    assert _embedding_count(memory_id) == 0

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


class _DeletionGenerationProvider:
    def __init__(self, user_id: UUID):
        self.user_id = user_id

    async def embed(self, request: EmbeddingRequest) -> EmbeddingProviderResult:
        with SessionLocal() as db:
            db.add(
                DataDeletionOperation(
                    user_id=self.user_id,
                    request_id=uuid4(),
                    status=DataDeletionStatus.COMPLETED,
                    deleted_counts={},
                )
            )
            db.commit()
        return EmbeddingProviderResult(
            vector=[0.005] * request.dimensions,
            provider="deletion-generation",
            model=request.model,
        )


def _assert_deletion_generation_blocks_stale_commit() -> None:
    user_id, memory_id = _seed_user_memory(
        title="删除代际",
        content="provider 返回前 deletion generation 改变",
    )
    db = SessionLocal()
    try:
        generation = int(
            db.scalar(
                select(func.count(DataDeletionOperation.id)).where(
                    DataDeletionOperation.user_id == user_id
                )
            )
            or 0
        )
        db.info[USER_DATA_ADMISSION_INFO_KEY] = UserDataAdmission(
            user_id=user_id,
            deletion_generation=generation,
        )
        try:
            asyncio.run(
                generate_or_refresh_memory_embedding(
                    db,
                    user_id=user_id,
                    memory_id=memory_id,
                    gateway=_gateway(_DeletionGenerationProvider(user_id)),
                )
            )
            raise AssertionError("stale pre-delete embedding commit unexpectedly succeeded")
        except UserDataRequestStale:
            db.rollback()
    finally:
        db.close()

    assert _embedding_count(memory_id) == 0
    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


def _assert_data_delete_clears_only_owner_embeddings() -> None:
    owner_id, owner_memory_id = _seed_user_memory(
        title="删除 owner",
        content="owner vector must disappear",
    )
    other_id, other_memory_id = _seed_user_memory(
        title="保留 other",
        content="other vector must survive",
    )
    provider = DeterministicEmbeddingProvider()
    for user_id, memory_id in (
        (owner_id, owner_memory_id),
        (other_id, other_memory_id),
    ):
        with SessionLocal() as db:
            asyncio.run(
                generate_or_refresh_memory_embedding(
                    db,
                    user_id=user_id,
                    memory_id=memory_id,
                    gateway=_gateway(provider),
                )
            )

    with SessionLocal() as db:
        result = delete_all_user_data(
            db,
            user_id=owner_id,
            request_id=uuid4(),
            storage=EmptyStorage(),
        )
        assert result.completed is True
        assert result.deleted_counts["memory_embeddings"] == 1

    assert _embedding_count(owner_memory_id) == 0
    assert _embedding_count(other_memory_id) == 1

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner_id))
        cleanup.delete(cleanup.get(User, other_id))
        cleanup.commit()


def main() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("Memory embedding integration requires PostgreSQL")

    _assert_schema_and_hnsw_index()
    _assert_database_rejects_cross_owner_embedding_row()
    _assert_idempotent_owner_scoped_refresh()
    _assert_concurrent_refresh_converges()
    _assert_memory_change_blocks_stale_vector()
    _assert_edit_and_soft_delete_invalidate()
    _assert_deletion_generation_blocks_stale_commit()
    _assert_data_delete_clears_only_owner_embeddings()

    print("PostgreSQL Memory embedding/index invariants PASS")


if __name__ == "__main__":
    main()
