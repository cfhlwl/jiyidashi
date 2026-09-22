"""Real PostgreSQL gate for S3-015 Daily Summary Foundation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.daily_summary_models import DailySummaryStatus
from app.models import Memory, MemorySource, Place, SourceType, User, Visit
from app.services.ai_gateway import (
    AIGateway,
    AIInferenceRequest,
    AIProviderResult,
    DeterministicAIProvider,
)
from app.services.daily_summary_service import summarize_today

DATABASE_URL = os.environ["DATABASE_URL"]
REFERENCE = datetime(2026, 9, 22, 1, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=DATABASE_URL,
        ai_provider="disabled",
        ai_model="test-model",
        ai_max_output_tokens=2048,
    )


def _seed_user(label: str, *, timezone: str = "Asia/Shanghai") -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                nickname=f"daily-pg-{label}",
                timezone=timezone,
            )
        )
        db.commit()
    return user_id


def _seed_memory(
    *,
    user_id: UUID,
    content: str,
    occurred_at: datetime,
) -> UUID:
    memory_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                content=content,
                occurred_at=occurred_at,
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
                is_confirmed=True,
            )
        )
        db.commit()
        db.add(
            MemorySource(
                id=uuid4(),
                memory_id=memory_id,
                source_type=SourceType.USER_TEXT,
                raw_text=content,
                confidence=1.0,
            )
        )
        db.commit()
    return memory_id


def _seed_memory_without_source(
    *,
    user_id: UUID,
    content: str,
    occurred_at: datetime,
) -> UUID:
    memory_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                content=content,
                occurred_at=occurred_at,
                source_type=SourceType.USER_TEXT,
                confidence=1.0,
                is_confirmed=True,
            )
        )
        db.commit()
    return memory_id


def _seed_cross_midnight_visit(user_id: UUID) -> UUID:
    visit_id = uuid4()
    with SessionLocal() as db:
        place = Place(
            id=uuid4(),
            user_id=user_id,
            name="夜间书店",
            cluster_key=uuid4().hex[:16],
            latitude=42.0,
            longitude=119.0,
        )
        db.add(place)
        db.flush()
        arrived = datetime(2026, 9, 21, 15, 50, tzinfo=UTC)
        left = datetime(2026, 9, 21, 16, 20, tzinfo=UTC)
        db.add(
            Visit(
                id=visit_id,
                user_id=user_id,
                place_id=place.id,
                arrived_at=arrived,
                left_at=left,
                duration_seconds=1800,
                confidence=0.85,
                source="LOCATION_CLUSTER",
                derivation_key=f"daily-pg-visit-{uuid4()}",
                source_point_count=3,
                source_started_at=arrived,
                source_ended_at=left,
                source_fingerprint="b" * 64,
                algorithm_version="visit-seq-v1",
                finalized_at=left + timedelta(minutes=10),
            )
        )
        db.commit()
    return visit_id


def _count(model) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _assert_no_caller_transaction(caller) -> None:
    if caller.in_transaction():
        raise AssertionError("Daily Summary provider I/O held caller DB transaction")


class _AssertingProvider(DeterministicAIProvider):
    def __init__(self, assertion: Callable[[], None]):
        super().__init__(
            output_text=(
                '{"summary":"今天去过夜间书店并完成日报",'
                '"citations":["D1","D2"]}'
            )
        )
        self._assertion = assertion

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self._assertion()
        return await super().infer(request)


class _DeletingProvider(DeterministicAIProvider):
    def __init__(
        self,
        assertion: Callable[[], None],
        *,
        memory_id: UUID,
    ):
        super().__init__(
            output_text='{"summary":"只引用第一条","citations":["D1"]}',
        )
        self._assertion = assertion
        self._memory_id = memory_id

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self._assertion()
        with SessionLocal() as db:
            memory = db.get(Memory, self._memory_id)
            assert memory is not None
            memory.is_deleted = True
            db.commit()
        return await super().infer(request)


class _AddingEvidenceProvider(DeterministicAIProvider):
    def __init__(
        self,
        assertion: Callable[[], None],
        *,
        memory_id: UUID,
        raw_text: str,
    ):
        super().__init__(
            output_text='{"summary":"旧完整快照","citations":["D1"]}',
        )
        self._assertion = assertion
        self._memory_id = memory_id
        self._raw_text = raw_text

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self._assertion()
        with SessionLocal() as db:
            db.add(
                MemorySource(
                    id=uuid4(),
                    memory_id=self._memory_id,
                    source_type=SourceType.USER_TEXT,
                    raw_text=self._raw_text,
                    confidence=1.0,
                )
            )
            db.commit()
        return await super().infer(request)


class _InsertingProvider(DeterministicAIProvider):
    def __init__(
        self,
        assertion: Callable[[], None],
        *,
        user_id: UUID,
    ):
        super().__init__(
            output_text='{"summary":"旧快照","citations":["D1"]}',
        )
        self._assertion = assertion
        self._user_id = user_id

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self._assertion()
        _seed_memory(
            user_id=self._user_id,
            content="provider I/O 期间新增的当天事实",
            occurred_at=datetime(2026, 9, 22, 0, 30, tzinfo=UTC),
        )
        return await super().infer(request)


def _assert_complete_snapshot_transaction_gap_and_overlap_visit() -> None:
    owner = _seed_user("complete")
    memory_id = _seed_memory(
        user_id=owner,
        content="今天完成日报",
        occurred_at=datetime(2026, 9, 21, 17, 0, tzinfo=UTC),
    )
    visit_id = _seed_cross_midnight_visit(owner)
    before_memories = _count(Memory)
    before_sources = _count(MemorySource)
    before_visits = _count(Visit)

    with SessionLocal() as caller:
        provider = _AssertingProvider(
            lambda: _assert_no_caller_transaction(caller)
        )
        result = asyncio.run(
            summarize_today(
                caller,
                user_id=owner,
                ai_gateway=AIGateway(_settings(), provider),
                reference_utc=REFERENCE,
            )
        )

    assert result.status == DailySummaryStatus.DAILY_SUMMARY_READY
    assert result.timezone == "Asia/Shanghai"
    assert result.day.isoformat() == "2026-09-22"
    assert {item.memory_id for item in result.citations} >= {memory_id, None}
    assert any(item.visit_id == visit_id for item in result.citations)
    assert len(provider.requests) == 1
    prompt = provider.requests[0].input_text
    assert "夜间书店" in prompt
    assert "今天完成日报" in prompt
    assert str(owner) not in prompt
    assert str(memory_id) not in prompt
    assert str(visit_id) not in prompt
    assert _count(Memory) == before_memories
    assert _count(MemorySource) == before_sources
    assert _count(Visit) == before_visits

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_uncited_visible_slot_drift_fails_closed() -> None:
    owner = _seed_user("uncited-race")
    first_id = _seed_memory(
        user_id=owner,
        content="first visible fact",
        occurred_at=datetime(2026, 9, 21, 17, 0, tzinfo=UTC),
    )
    second_id = _seed_memory(
        user_id=owner,
        content="second visible fact",
        occurred_at=datetime(2026, 9, 21, 18, 0, tzinfo=UTC),
    )

    with SessionLocal() as caller:
        provider = _DeletingProvider(
            lambda: _assert_no_caller_transaction(caller),
            memory_id=second_id,
        )
        result = asyncio.run(
            summarize_today(
                caller,
                user_id=owner,
                ai_gateway=AIGateway(_settings(), provider),
                reference_utc=REFERENCE,
            )
        )

    assert len(provider.requests) == 1
    prompt = provider.requests[0].input_text
    assert '"slot":"D1"' in prompt
    assert '"slot":"D2"' in prompt
    assert "first visible fact" in prompt
    assert "second visible fact" in prompt
    assert first_id != second_id
    assert result.status == DailySummaryStatus.DATA_CHANGED_DURING_GENERATION
    assert result.summary is None
    assert result.citations == ()

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_excluded_memory_evidence_promotion_invalidates_snapshot() -> None:
    owner = _seed_user("excluded-authority-race")
    visible_id = _seed_memory(
        user_id=owner,
        content="visible trusted fact",
        occurred_at=datetime(2026, 9, 21, 17, 0, tzinfo=UTC),
    )
    excluded_text = "excluded fact gains evidence during provider I/O"
    excluded_id = _seed_memory_without_source(
        user_id=owner,
        content=excluded_text,
        occurred_at=datetime(2026, 9, 21, 18, 0, tzinfo=UTC),
    )

    with SessionLocal() as caller:
        provider = _AddingEvidenceProvider(
            lambda: _assert_no_caller_transaction(caller),
            memory_id=excluded_id,
            raw_text=excluded_text,
        )
        result = asyncio.run(
            summarize_today(
                caller,
                user_id=owner,
                ai_gateway=AIGateway(_settings(), provider),
                reference_utc=REFERENCE,
            )
        )

    assert len(provider.requests) == 1
    prompt = provider.requests[0].input_text
    assert '"slot":"D1"' in prompt
    assert '"slot":"D2"' not in prompt
    assert "visible trusted fact" in prompt
    assert excluded_text not in prompt
    assert visible_id != excluded_id
    assert result.status == DailySummaryStatus.DATA_CHANGED_DURING_GENERATION
    assert result.summary is None
    assert result.citations == ()

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_new_day_fact_during_provider_io_invalidates_snapshot() -> None:
    owner = _seed_user("insert-race")
    _seed_memory(
        user_id=owner,
        content="生成开始前的当天事实",
        occurred_at=datetime(2026, 9, 21, 17, 0, tzinfo=UTC),
    )

    with SessionLocal() as caller:
        provider = _InsertingProvider(
            lambda: _assert_no_caller_transaction(caller),
            user_id=owner,
        )
        result = asyncio.run(
            summarize_today(
                caller,
                user_id=owner,
                ai_gateway=AIGateway(_settings(), provider),
                reference_utc=REFERENCE,
            )
        )

    assert result.status == DailySummaryStatus.DATA_CHANGED_DURING_GENERATION
    assert result.summary is None
    assert result.citations == ()
    assert len(provider.requests) == 1

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_day_cap_blocks_provider() -> None:
    owner = _seed_user("cap")
    base = datetime(2026, 9, 21, 16, 0, tzinfo=UTC)
    for index in range(65):
        _seed_memory(
            user_id=owner,
            content=f"cap memory {index}",
            occurred_at=base + timedelta(minutes=index),
        )

    provider = DeterministicAIProvider(
        output_text='{"summary":"不应生成","citations":["D1"]}',
    )
    with SessionLocal() as db:
        result = asyncio.run(
            summarize_today(
                db,
                user_id=owner,
                ai_gateway=AIGateway(_settings(), provider),
                reference_utc=REFERENCE,
            )
        )

    assert result.status == DailySummaryStatus.SUMMARY_INCOMPLETE
    assert result.incomplete_code == "DAY_MEMORY_SCAN_LIMIT_REACHED"
    assert provider.requests == []

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def main() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("S3-015 integration gate requires PostgreSQL")

    _assert_complete_snapshot_transaction_gap_and_overlap_visit()
    _assert_uncited_visible_slot_drift_fails_closed()
    _assert_excluded_memory_evidence_promotion_invalidates_snapshot()
    _assert_new_day_fact_during_provider_io_invalidates_snapshot()
    _assert_day_cap_blocks_provider()
    print("PostgreSQL Daily Summary invariants PASS")


if __name__ == "__main__":
    main()
