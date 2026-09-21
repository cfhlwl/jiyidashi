from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.config import Settings
from app.core.db import SessionLocal
from app.embedding_gateway import DeterministicEmbeddingProvider, EmbeddingGateway
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL
from app.main import app
from app.models import (
    Memory,
    MemorySource,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    SourceType,
    User,
)
from app.retrieval_models import (
    LLMFallbackStatus,
    RetrievalTier,
    StructuredResolutionStatus,
    VectorRetrievalStatus,
)
from app.services.evidence_ranking_service import EvidenceRankClass
from app.services.structured_first_retrieval_service import (
    RetrievalError,
    retrieve_memories,
)


def _gateway(provider: DeterministicEmbeddingProvider) -> EmbeddingGateway:
    settings = Settings(
        app_env="test",
        embedding_provider="disabled",
        embedding_model=MEMORY_EMBEDDING_MODEL,
        embedding_dimensions=MEMORY_EMBEDDING_DIMENSIONS,
    )
    return EmbeddingGateway(settings, provider)


def _owner(db, label: str) -> UUID:
    user = User(id=uuid4(), nickname=f"retrieval-{label}")
    db.add(user)
    db.commit()
    return user.id


def _memory(
    db,
    user_id: UUID,
    *,
    content: str,
    title: str | None = None,
    memory_type: MemoryType = MemoryType.NOTE,
    confirmed: bool = True,
    source_type: SourceType = SourceType.USER_TEXT,
    confidence: float = 1.0,
    occurred_at: datetime | None = None,
) -> Memory:
    memory = Memory(
        id=uuid4(),
        user_id=user_id,
        title=title,
        content=content,
        memory_type=memory_type,
        is_confirmed=confirmed,
        source_type=source_type,
        confidence=confidence,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def _source(
    db,
    memory: Memory,
    *,
    source_type: SourceType = SourceType.USER_TEXT,
    confidence: float = 1.0,
) -> MemorySource:
    source = MemorySource(
        id=uuid4(),
        memory_id=memory.id,
        source_type=source_type,
        raw_text=memory.content,
        confidence=confidence,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@pytest.mark.asyncio
async def test_structured_current_object_precedes_keyword_and_vector():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "structured-current")
        item = ObjectItem(
            id=uuid4(),
            user_id=owner,
            name="护照",
            normalized_name="护照",
        )
        db.add(item)
        db.commit()

        memory = _memory(
            db,
            owner,
            title="护照",
            content="护照放在书房抽屉",
            memory_type=MemoryType.OBJECT_LOCATION,
        )
        source = _source(db, memory)
        location = ObjectLocation(
            id=uuid4(),
            object_id=item.id,
            user_id=owner,
            memory_id=memory.id,
            location_text="书房抽屉",
            recorded_at=datetime.now(UTC),
            status=ObjectLocationStatus.CURRENT,
        )
        db.add(location)
        db.commit()

        result = await retrieve_memories(
            db,
            user_id=owner,
            question="我的护照在哪里？",
            gateway=_gateway(provider),
        )

        assert result.selected_tier == RetrievalTier.STRUCTURED
        assert result.structured_status == StructuredResolutionStatus.RESOLVED
        assert result.vector_status == VectorRetrievalStatus.NOT_NEEDED
        assert len(result.candidates) == 1
        candidate = result.candidates[0]
        assert candidate.memory_id == memory.id
        assert candidate.structured_ref_type == "OBJECT_LOCATION"
        assert candidate.structured_ref_id == location.id
        assert candidate.evidence_rank_class == EvidenceRankClass.USER_DIRECT
        assert candidate.best_memory_source_id == source.id
        assert candidate.answer_eligible is True
        assert provider.requests == []


@pytest.mark.asyncio
async def test_resolved_object_without_current_is_terminal_miss():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "structured-miss")
        item = ObjectItem(
            id=uuid4(),
            user_id=owner,
            name="钥匙",
            normalized_name="钥匙",
        )
        db.add(item)
        db.commit()

        # This ordinary Memory would match lower keyword tiers, but a recognized
        # structured Object with no CURRENT location must stop retrieval here.
        memory = _memory(
            db,
            owner,
            content="钥匙以前可能放在门口柜子",
        )
        _source(db, memory)

        result = await retrieve_memories(
            db,
            user_id=owner,
            question="钥匙现在在哪里？",
            gateway=_gateway(provider),
        )

        assert result.selected_tier == RetrievalTier.STRUCTURED
        assert result.structured_status == StructuredResolutionStatus.TERMINAL_MISS
        assert result.candidates == ()
        assert result.metrics.keyword_candidates == 0
        assert result.vector_status == VectorRetrievalStatus.NOT_NEEDED
        assert provider.requests == []


@pytest.mark.asyncio
async def test_structured_object_candidate_scan_is_bounded_and_fail_closed():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "structured-cap")
        names = [f"物品{index:02d}" for index in range(33)]
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

        result = await retrieve_memories(
            db,
            user_id=owner,
            question=f"我的{''.join(names)}在哪里？",
            gateway=_gateway(provider),
        )

        assert result.selected_tier == RetrievalTier.STRUCTURED
        assert (
            result.structured_status
            == StructuredResolutionStatus.CANDIDATE_LIMIT_REACHED
        )
        assert result.candidates == ()
        assert result.vector_status == VectorRetrievalStatus.NOT_NEEDED
        assert provider.requests == []


@pytest.mark.asyncio
async def test_keyword_is_deterministic_and_does_not_promote_ai_only_memory():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "keyword")
        now = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
        direct = _memory(
            db,
            owner,
            content="老张周五来取合同",
            occurred_at=now,
        )
        direct_source = _source(db, direct)
        ai = _memory(
            db,
            owner,
            content="老张合同可能与下周会议有关",
            confirmed=False,
            source_type=SourceType.AI_INFERENCE,
            confidence=0.99,
            occurred_at=now + timedelta(hours=1),
        )
        ai_source = _source(
            db,
            ai,
            source_type=SourceType.AI_INFERENCE,
            confidence=0.99,
        )

        result = await retrieve_memories(
            db,
            user_id=owner,
            question="老张合同",
            gateway=_gateway(provider),
        )

        assert result.selected_tier == RetrievalTier.KEYWORD
        assert result.vector_status == VectorRetrievalStatus.NOT_NEEDED
        assert provider.requests == []
        by_id = {candidate.memory_id: candidate for candidate in result.candidates}
        assert by_id[direct.id].evidence_rank_class == EvidenceRankClass.USER_DIRECT
        assert by_id[direct.id].best_memory_source_id == direct_source.id
        assert by_id[direct.id].answer_eligible is True
        assert by_id[ai.id].evidence_rank_class == EvidenceRankClass.AI_INFERENCE
        assert by_id[ai.id].best_memory_source_id == ai_source.id
        assert by_id[ai.id].answer_eligible is False


@pytest.mark.asyncio
async def test_keyword_score_is_applied_before_bounded_limit():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "keyword-global-score")
        base = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)
        for index in range(45):
            memory = _memory(
                db,
                owner,
                content=f"alpha filler {index}",
                occurred_at=base + timedelta(minutes=index),
            )
            _source(db, memory)

        strongest = _memory(
            db,
            owner,
            content="alpha beta exact strongest match",
            occurred_at=base - timedelta(days=1),
        )
        _source(db, strongest)

        result = await retrieve_memories(
            db,
            user_id=owner,
            question="alpha beta",
            gateway=_gateway(provider),
            top_k=1,
        )

        assert result.selected_tier == RetrievalTier.KEYWORD
        assert [candidate.memory_id for candidate in result.candidates] == [strongest.id]
        assert result.candidates[0].retrieval_score == 2.0
        assert provider.requests == []


@pytest.mark.asyncio
async def test_retrieval_does_not_autoflush_caller_pending_or_dirty_state():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "no-autoflush")
        committed = _memory(db, owner, content="已提交的合同记录")
        _source(db, committed)

        dirty_owner = db.get(User, owner)
        assert dirty_owner is not None
        pending = Memory(
            id=uuid4(),
            user_id=owner,
            content="尚未提交的合同记录",
        )
        dirty_owner.nickname = "must-remain-dirty"
        db.add(pending)

        before_new = set(db.new)
        before_dirty = set(db.dirty)

        result = await retrieve_memories(
            db,
            user_id=owner,
            question="合同记录",
            gateway=_gateway(provider),
        )

        assert [candidate.memory_id for candidate in result.candidates] == [committed.id]
        assert set(db.new) == before_new
        assert set(db.dirty) == before_dirty
        assert pending in db.new
        assert dirty_owner in db.dirty


@pytest.mark.asyncio
async def test_sqlite_vector_fallback_is_typed_and_provider_is_not_called():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "sqlite-vector")

        result = await retrieve_memories(
            db,
            user_id=owner,
            question="不存在的语义检索词",
            gateway=_gateway(provider),
        )

        assert result.candidates == ()
        assert result.selected_tier is None
        assert result.vector_status == VectorRetrievalStatus.DATABASE_UNSUPPORTED
        assert result.llm_fallback_status == LLMFallbackStatus.NOT_ATTEMPTED
        assert provider.requests == []


@pytest.mark.asyncio
async def test_top_k_is_bounded_and_invalid_values_fail_closed():
    provider = DeterministicEmbeddingProvider()
    with SessionLocal() as db:
        owner = _owner(db, "top-k")
        for index in range(12):
            memory = _memory(db, owner, content=f"合同记录 {index}")
            _source(db, memory)

        result = await retrieve_memories(
            db,
            user_id=owner,
            question="合同记录",
            gateway=_gateway(provider),
            top_k=3,
        )
        assert len(result.candidates) == 3
        assert [candidate.rank_within_tier for candidate in result.candidates] == [1, 2, 3]

        with pytest.raises(RetrievalError) as caught:
            await retrieve_memories(
                db,
                user_id=owner,
                question="合同",
                gateway=_gateway(provider),
                top_k=11,
            )
        assert caught.value.code == "RETRIEVAL_TOP_K_INVALID"


def test_s3_010_adds_no_public_retrieval_or_rag_api():
    paths = {
        path
        for route in app.routes
        if isinstance((path := getattr(route, "path", None)), str)
    }
    assert all("retrieval" not in path for path in paths)
    assert all("rag" not in path for path in paths)
