"""Real PostgreSQL/pgvector gate for S3-010 Structured First Retrieval."""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.embedding_gateway import DeterministicEmbeddingProvider, EmbeddingGateway
from app.embedding_models import MemoryEmbedding
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL
from app.models import (
    Memory,
    MemorySource,
    MemoryType,
    ObjectItem,
    SourceType,
    User,
)
from app.retrieval_models import (
    LLMFallbackStatus,
    RetrievalTier,
    StructuredResolutionStatus,
    VectorRetrievalStatus,
)
from app.services.embedding_service import (
    build_memory_embedding_text,
    memory_embedding_fingerprint,
)
from app.services.evidence_ranking_service import EvidenceRankClass
from app.services.structured_first_retrieval_service import retrieve_memories

DATABASE_URL = os.environ["DATABASE_URL"]


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=DATABASE_URL,
        embedding_provider="disabled",
        embedding_model=MEMORY_EMBEDDING_MODEL,
        embedding_dimensions=MEMORY_EMBEDDING_DIMENSIONS,
    )


def _vector(first: float, second: float = 0.0) -> list[float]:
    return [first, second] + [0.0] * (MEMORY_EMBEDDING_DIMENSIONS - 2)


def _seed_user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"s3-010-{label}"))
        db.commit()
    return user_id


def _seed_memory(
    *,
    user_id: UUID,
    content: str,
    vector: list[float],
    source_type: SourceType = SourceType.USER_TEXT,
    confirmed: bool = True,
    deleted: bool = False,
    memory_type: MemoryType = MemoryType.NOTE,
    fingerprint_override: str | None = None,
    revision_offset: int = 0,
) -> UUID:
    memory_id = uuid4()
    with SessionLocal() as db:
        memory = Memory(
            id=memory_id,
            user_id=user_id,
            content=content,
            source_type=source_type,
            confidence=0.99 if source_type == SourceType.AI_INFERENCE else 1.0,
            is_confirmed=confirmed,
            is_deleted=deleted,
            memory_type=memory_type,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)

        db.add(
            MemorySource(
                id=uuid4(),
                memory_id=memory.id,
                source_type=source_type,
                raw_text=content,
                confidence=0.99 if source_type == SourceType.AI_INFERENCE else 1.0,
            )
        )
        canonical = build_memory_embedding_text(memory)
        db.add(
            MemoryEmbedding(
                memory_id=memory.id,
                user_id=user_id,
                memory_revision=memory.edit_revision + revision_offset,
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


def _assert_vector_retrieval_and_trust_independence() -> None:
    owner = _seed_user("owner")
    foreign = _seed_user("foreign")

    ai_memory = _seed_memory(
        user_id=owner,
        content="AI-only candidate without lexical overlap",
        vector=_vector(1.0),
        source_type=SourceType.AI_INFERENCE,
        confirmed=False,
    )
    direct_memory = _seed_memory(
        user_id=owner,
        content="direct user evidence without lexical overlap",
        vector=_vector(0.8, 0.6),
    )
    _seed_memory(
        user_id=foreign,
        content="foreign nearest candidate",
        vector=_vector(1.0),
    )
    stale_fingerprint = _seed_memory(
        user_id=owner,
        content="stale fingerprint candidate",
        vector=_vector(1.0),
        fingerprint_override="f" * 64,
    )
    stale_revision = _seed_memory(
        user_id=owner,
        content="stale revision candidate",
        vector=_vector(1.0),
        revision_offset=1,
    )
    deleted = _seed_memory(
        user_id=owner,
        content="deleted candidate",
        vector=_vector(1.0),
        deleted=True,
    )
    object_location = _seed_memory(
        user_id=owner,
        content="object location backing memory",
        vector=_vector(1.0),
        memory_type=MemoryType.OBJECT_LOCATION,
    )

    provider = DeterministicEmbeddingProvider(vector=_vector(1.0))
    gateway = EmbeddingGateway(_settings(), provider)
    before_memories = _count(Memory)
    before_sources = _count(MemorySource)
    before_embeddings = _count(MemoryEmbedding)

    with SessionLocal() as db:
        result = asyncio.run(
            retrieve_memories(
                db,
                user_id=owner,
                question="semantic needle absent from persisted text",
                gateway=gateway,
                top_k=5,
            )
        )

    assert result.selected_tier == RetrievalTier.VECTOR
    assert result.vector_status == VectorRetrievalStatus.SUCCESS
    assert result.llm_fallback_status == LLMFallbackStatus.NOT_ATTEMPTED
    assert len(provider.requests) == 1
    assert provider.requests[0].model == MEMORY_EMBEDDING_MODEL
    assert provider.requests[0].dimensions == MEMORY_EMBEDDING_DIMENSIONS

    ids = [candidate.memory_id for candidate in result.candidates]
    assert ids[:2] == [ai_memory, direct_memory]
    assert stale_fingerprint not in ids
    assert stale_revision not in ids
    assert deleted not in ids
    assert object_location not in ids

    ai_candidate = result.candidates[0]
    direct_candidate = result.candidates[1]
    assert ai_candidate.evidence_rank_class == EvidenceRankClass.AI_INFERENCE
    assert ai_candidate.answer_eligible is False
    assert direct_candidate.evidence_rank_class == EvidenceRankClass.USER_DIRECT
    assert direct_candidate.answer_eligible is True
    assert ai_candidate.retrieval_score > direct_candidate.retrieval_score
    assert all(candidate.embedding_fingerprint_validated for candidate in result.candidates)

    # Retrieval is read-only even when vector similarity ranks AI-only data first.
    assert _count(Memory) == before_memories
    assert _count(MemorySource) == before_sources
    assert _count(MemoryEmbedding) == before_embeddings

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.delete(cleanup.get(User, foreign))
        cleanup.commit()


def _assert_structured_object_candidate_cap_is_postgres_bounded() -> None:
    owner = _seed_user("structured-cap")
    names = [f"生产对象{index:02d}" for index in range(33)]
    with SessionLocal() as db:
        db.add_all(
            [
                ObjectItem(
                    id=uuid4(),
                    user_id=owner,
                    name=name,
                    normalized_name=name,
                )
                for name in names
            ]
        )
        db.commit()

    provider = DeterministicEmbeddingProvider(vector=_vector(1.0))
    gateway = EmbeddingGateway(_settings(), provider)
    with SessionLocal() as db:
        result = asyncio.run(
            retrieve_memories(
                db,
                user_id=owner,
                question=f"我的{''.join(names)}在哪里？",
                gateway=gateway,
            )
        )

    assert result.selected_tier == RetrievalTier.STRUCTURED
    assert (
        result.structured_status
        == StructuredResolutionStatus.CANDIDATE_LIMIT_REACHED
    )
    assert result.candidates == ()
    assert result.vector_status == VectorRetrievalStatus.NOT_NEEDED
    assert provider.requests == []

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_stale_nearest_rows_do_not_hide_later_valid_vector() -> None:
    owner = _seed_user("stale-pagination")
    for index in range(16):
        _seed_memory(
            user_id=owner,
            content=f"stale pagination candidate {index}",
            vector=_vector(1.0),
            fingerprint_override="f" * 64,
        )
    valid = _seed_memory(
        user_id=owner,
        content="later valid pagination candidate",
        vector=_vector(0.98, 0.20),
    )
    provider = DeterministicEmbeddingProvider(vector=_vector(1.0))
    gateway = EmbeddingGateway(_settings(), provider)

    with SessionLocal() as db:
        result = asyncio.run(
            retrieve_memories(
                db,
                user_id=owner,
                question="nebula-qz",
                gateway=gateway,
                top_k=5,
            )
        )

    assert result.selected_tier == RetrievalTier.VECTOR
    assert result.vector_status == VectorRetrievalStatus.SUCCESS
    assert [candidate.memory_id for candidate in result.candidates] == [valid]

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_validation_scan_limit_is_explicit() -> None:
    owner = _seed_user("scan-limit")
    for index in range(33):
        _seed_memory(
            user_id=owner,
            content=f"scan limit stale candidate {index}",
            vector=_vector(1.0),
            fingerprint_override="e" * 64,
        )
    _seed_memory(
        user_id=owner,
        content="valid candidate beyond bounded scan",
        vector=_vector(0.98, 0.20),
    )
    provider = DeterministicEmbeddingProvider(vector=_vector(1.0))
    gateway = EmbeddingGateway(_settings(), provider)

    with SessionLocal() as db:
        result = asyncio.run(
            retrieve_memories(
                db,
                user_id=owner,
                question="quasar-zx",
                gateway=gateway,
                top_k=5,
            )
        )

    assert result.selected_tier == RetrievalTier.VECTOR
    assert result.candidates == ()
    assert (
        result.vector_status
        == VectorRetrievalStatus.VALIDATION_SCAN_LIMIT_REACHED
    )
    assert result.llm_fallback_status == LLMFallbackStatus.NOT_ATTEMPTED

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_provider_failure_is_typed_fail_closed() -> None:
    owner = _seed_user("provider-failure")
    _seed_memory(
        user_id=owner,
        content="candidate with no lexical query overlap",
        vector=_vector(1.0),
    )
    provider = DeterministicEmbeddingProvider(vector=[0.1])
    gateway = EmbeddingGateway(_settings(), provider)

    with SessionLocal() as db:
        result = asyncio.run(
            retrieve_memories(
                db,
                user_id=owner,
                question="totally unrelated semantic request",
                gateway=gateway,
            )
        )

    assert result.candidates == ()
    assert result.selected_tier is None
    assert result.vector_status == VectorRetrievalStatus.PROVIDER_FAILED
    assert result.vector_error_code == "EMBEDDING_VECTOR_DIMENSION_MISMATCH"
    assert result.llm_fallback_status == LLMFallbackStatus.NOT_ATTEMPTED

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def main() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("S3-010 integration gate requires PostgreSQL")

    _assert_vector_retrieval_and_trust_independence()
    _assert_structured_object_candidate_cap_is_postgres_bounded()
    _assert_stale_nearest_rows_do_not_hide_later_valid_vector()
    _assert_validation_scan_limit_is_explicit()
    _assert_provider_failure_is_typed_fail_closed()
    print("PostgreSQL Structured First retrieval invariants PASS")


if __name__ == "__main__":
    main()
