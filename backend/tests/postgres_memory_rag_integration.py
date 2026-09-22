"""Real PostgreSQL/pgvector gate for S3-011 Memory RAG Foundation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.embedding_gateway import DeterministicEmbeddingProvider, EmbeddingGateway
from app.embedding_models import MemoryEmbedding
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL
from app.models import Memory, MemorySource, SourceType, User
from app.rag_models import MemoryRAGStatus
from app.services.ai_gateway import (
    AIGateway,
    AIInferenceRequest,
    AIProviderResult,
    DeterministicAIProvider,
)
from app.services.embedding_service import (
    build_memory_embedding_text,
    memory_embedding_fingerprint,
)
from app.services.memory_rag_service import answer_from_memory_rag

DATABASE_URL = os.environ["DATABASE_URL"]


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=DATABASE_URL,
        ai_provider="disabled",
        ai_model="test-model",
        ai_max_output_tokens=2048,
        embedding_provider="disabled",
        embedding_model=MEMORY_EMBEDDING_MODEL,
        embedding_dimensions=MEMORY_EMBEDDING_DIMENSIONS,
    )


def _vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second] + [0.0] * (MEMORY_EMBEDDING_DIMENSIONS - 2)


def _seed_user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"rag-pg-{label}"))
        db.commit()
    return user_id


def _seed_memory(
    *,
    user_id: UUID,
    content: str,
    vector: list[float] | None = None,
    fingerprint_override: str | None = None,
    source_confidence: float = 1.0,
) -> UUID:
    memory_id = uuid4()
    with SessionLocal() as db:
        memory = Memory(
            id=memory_id,
            user_id=user_id,
            content=content,
            source_type=SourceType.USER_TEXT,
            confidence=1.0,
            is_confirmed=True,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)

        db.add(
            MemorySource(
                id=uuid4(),
                memory_id=memory.id,
                source_type=SourceType.USER_TEXT,
                raw_text=content,
                confidence=source_confidence,
            )
        )
        if vector is not None:
            canonical = build_memory_embedding_text(memory)
            db.add(
                MemoryEmbedding(
                    memory_id=memory.id,
                    user_id=user_id,
                    memory_revision=memory.edit_revision,
                    content_fingerprint=(
                        fingerprint_override
                        if fingerprint_override is not None
                        else memory_embedding_fingerprint(canonical)
                    ),
                    provider="fixture",
                    model=MEMORY_EMBEDDING_MODEL,
                    dimensions=MEMORY_EMBEDDING_DIMENSIONS,
                    embedding=vector,
                )
            )
        db.commit()
    return memory_id


def _count(model) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _assert_no_caller_transaction(caller) -> None:
    if caller.in_transaction():
        raise AssertionError("RAG provider I/O held caller DB transaction")


class _TransactionAssertingProvider(DeterministicAIProvider):
    def __init__(self, assert_gap: Callable[[], None]):
        super().__init__(
            output_text='{"answer":"保险柜","citations":["E1"]}',
        )
        self._assert_gap = assert_gap

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self._assert_gap()
        return await super().infer(request)


class _DeletingProvider(DeterministicAIProvider):
    def __init__(
        self,
        assert_gap: Callable[[], None],
        *,
        memory_id: UUID,
    ):
        super().__init__(
            output_text='{"answer":"旧位置","citations":["E1"]}',
        )
        self._assert_gap = assert_gap
        self._memory_id = memory_id

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self._assert_gap()
        with SessionLocal() as db:
            memory = db.get(Memory, self._memory_id)
            assert memory is not None
            memory.is_deleted = True
            db.commit()
        return await super().infer(request)


def _assert_answer_generation_has_transaction_gap_and_is_read_only() -> None:
    owner = _seed_user("gap")
    memory_id = _seed_memory(
        user_id=owner,
        content="年度预算原件放在保险柜",
    )
    before_memories = _count(Memory)
    before_sources = _count(MemorySource)
    before_embeddings = _count(MemoryEmbedding)

    with SessionLocal() as caller:
        provider = _TransactionAssertingProvider(
            lambda: _assert_no_caller_transaction(caller)
        )
        result = asyncio.run(
            answer_from_memory_rag(
                caller,
                user_id=owner,
                question="年度预算原件在哪里？",
                retrieval_gateway=EmbeddingGateway(
                    _settings(),
                    DeterministicEmbeddingProvider(),
                ),
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert result.status == MemoryRAGStatus.ANSWERED
    assert result.citations[0].memory_id == memory_id
    assert len(provider.requests) == 1
    assert _count(Memory) == before_memories
    assert _count(MemorySource) == before_sources
    assert _count(MemoryEmbedding) == before_embeddings

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_post_provider_delete_fails_closed_without_long_transaction() -> None:
    owner = _seed_user("delete-race")
    memory_id = _seed_memory(
        user_id=owner,
        content="合同原件放在三号文件柜",
    )

    with SessionLocal() as caller:
        provider = _DeletingProvider(
            lambda: _assert_no_caller_transaction(caller),
            memory_id=memory_id,
        )
        result = asyncio.run(
            answer_from_memory_rag(
                caller,
                user_id=owner,
                question="合同原件在哪里？",
                retrieval_gateway=EmbeddingGateway(
                    _settings(),
                    DeterministicEmbeddingProvider(),
                ),
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert result.status == MemoryRAGStatus.EVIDENCE_CHANGED_DURING_GENERATION
    assert result.answer is None
    assert result.citations == ()

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_uncited_prompt_slot_change_fails_closed() -> None:
    owner = _seed_user("uncited-slot-race")
    first_id = _seed_memory(
        user_id=owner,
        content="sharedanchor first stable evidence",
        source_confidence=1.0,
    )
    second_id = _seed_memory(
        user_id=owner,
        content="sharedanchor second evidence becomes stale",
        source_confidence=0.9,
    )

    with SessionLocal() as caller:
        provider = _DeletingProvider(
            lambda: _assert_no_caller_transaction(caller),
            memory_id=second_id,
        )
        result = asyncio.run(
            answer_from_memory_rag(
                caller,
                user_id=owner,
                question="sharedanchor",
                retrieval_gateway=EmbeddingGateway(
                    _settings(),
                    DeterministicEmbeddingProvider(),
                ),
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert '"slot":"E1"' in request.input_text
    assert '"slot":"E2"' in request.input_text
    assert "first stable evidence" in request.input_text
    assert "second evidence becomes stale" in request.input_text
    assert result.status == MemoryRAGStatus.EVIDENCE_CHANGED_DURING_GENERATION
    assert result.answer is None
    assert result.citations == ()
    assert first_id != second_id

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_vector_validation_limit_blocks_answer_provider() -> None:
    owner = _seed_user("vector-incomplete")
    for index in range(33):
        _seed_memory(
            user_id=owner,
            content=f"stale semantic record {index}",
            vector=_vector(1.0),
            fingerprint_override="f" * 64,
        )
    _seed_memory(
        user_id=owner,
        content="valid record beyond bounded validation scan",
        vector=_vector(0.98, 0.20),
    )

    answer_provider = DeterministicAIProvider(
        output_text='{"answer":"不应生成","citations":["E1"]}',
    )
    retrieval_provider = DeterministicEmbeddingProvider(vector=_vector(1.0))
    with SessionLocal() as db:
        result = asyncio.run(
            answer_from_memory_rag(
                db,
                user_id=owner,
                question="quasar-rag-zx",
                retrieval_gateway=EmbeddingGateway(
                    _settings(),
                    retrieval_provider,
                ),
                ai_gateway=AIGateway(_settings(), answer_provider),
                top_k=5,
            )
        )

    assert result.status == MemoryRAGStatus.RETRIEVAL_INCOMPLETE
    assert result.retrieval_incomplete_code == "VECTOR_VALIDATION_SCAN_LIMIT_REACHED"
    assert answer_provider.requests == []
    assert len(retrieval_provider.requests) == 1

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def main() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("S3-011 integration gate requires PostgreSQL")

    _assert_answer_generation_has_transaction_gap_and_is_read_only()
    _assert_post_provider_delete_fails_closed_without_long_transaction()
    _assert_uncited_prompt_slot_change_fails_closed()
    _assert_vector_validation_limit_blocks_answer_provider()
    print("PostgreSQL Memory RAG invariants PASS")


if __name__ == "__main__":
    main()
