"""Real PostgreSQL gate for S3-016 Monthly Summary Foundation."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import Memory, MemorySource, Place, SourceType, User, Visit
from app.monthly_summary_models import MonthlySummaryStatus
from app.services.ai_gateway import (
    AIGateway,
    AIInferenceRequest,
    AIProviderResult,
    DeterministicAIProvider,
)
from app.services.monthly_summary_service import summarize_month

DATABASE_URL = os.environ["DATABASE_URL"]
TARGET_MONTH = "2026-09"


def _settings() -> Settings:
    return Settings(
        app_env="test",
        database_url=DATABASE_URL,
        ai_provider="disabled",
        ai_model="test-model",
        ai_max_output_tokens=2048,
    )


def _seed_user(label: str, *, timezone: str = "UTC") -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                nickname=f"monthly-pg-{label}",
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
    add_source: bool = True,
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
        if add_source:
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


def _seed_cross_month_visit(user_id: UUID) -> UUID:
    visit_id = uuid4()
    with SessionLocal() as db:
        place = Place(
            id=uuid4(),
            user_id=user_id,
            name="跨月书店",
            cluster_key=uuid4().hex[:16],
            latitude=42.0,
            longitude=119.0,
        )
        db.add(place)
        db.flush()
        arrived = datetime(2026, 8, 31, 23, 50, tzinfo=UTC)
        left = datetime(2026, 9, 1, 0, 20, tzinfo=UTC)
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
                derivation_key=f"monthly-pg-{uuid4()}",
                source_point_count=3,
                source_started_at=arrived,
                source_ended_at=left,
                source_fingerprint="c" * 64,
                algorithm_version="visit-seq-v1",
                finalized_at=left + timedelta(minutes=10),
            )
        )
        db.commit()
    return visit_id


def _seed_memory_cap(user_id: UUID) -> None:
    base = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    with SessionLocal() as db:
        for index in range(257):
            memory_id = uuid4()
            content = f"monthly cap fact {index}"
            db.add(
                Memory(
                    id=memory_id,
                    user_id=user_id,
                    content=content,
                    occurred_at=base + timedelta(minutes=index),
                    source_type=SourceType.USER_TEXT,
                    confidence=1.0,
                    is_confirmed=True,
                )
            )
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


def _count(model) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _assert_no_caller_transaction(caller) -> None:
    if caller.in_transaction():
        raise AssertionError("Monthly Summary provider I/O held caller DB transaction")


class _AssertingProvider(DeterministicAIProvider):
    def __init__(self, assertion: Callable[[], None]):
        super().__init__(
            output_text=(
                '{"summary":"九月去过跨月书店并完成月度工作",'
                '"citations":["M1","M2"]}'
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
            output_text='{"summary":"只引用第一条","citations":["M1"]}',
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
            output_text='{"summary":"旧完整月快照","citations":["M1"]}',
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
            output_text='{"summary":"旧快照","citations":["M1"]}',
        )
        self._assertion = assertion
        self._user_id = user_id

    async def infer(self, request: AIInferenceRequest) -> AIProviderResult:
        self._assertion()
        _seed_memory(
            user_id=self._user_id,
            content="provider I/O 期间新增的月事实",
            occurred_at=datetime(2026, 9, 20, 1, 0, tzinfo=UTC),
        )
        return await super().infer(request)


def _assert_complete_month_transaction_gap_and_overlap_visit() -> None:
    owner = _seed_user("complete")
    visit_id = _seed_cross_month_visit(owner)
    memory_id = _seed_memory(
        user_id=owner,
        content="九月完成月度工作",
        occurred_at=datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
    )
    before_memories = _count(Memory)
    before_sources = _count(MemorySource)
    before_visits = _count(Visit)

    with SessionLocal() as caller:
        provider = _AssertingProvider(
            lambda: _assert_no_caller_transaction(caller)
        )
        result = asyncio.run(
            summarize_month(
                caller,
                user_id=owner,
                target_month=TARGET_MONTH,
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert result.status == MonthlySummaryStatus.MONTHLY_SUMMARY_READY
    assert result.target_month == TARGET_MONTH
    assert result.timezone == "UTC"
    assert any(item.visit_id == visit_id for item in result.citations)
    assert any(item.memory_id == memory_id for item in result.citations)
    assert len(provider.requests) == 1
    prompt = provider.requests[0].input_text
    assert "跨月书店" in prompt
    assert "九月完成月度工作" in prompt
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
        content="first monthly fact",
        occurred_at=datetime(2026, 9, 8, 1, 0, tzinfo=UTC),
    )
    second_id = _seed_memory(
        user_id=owner,
        content="second monthly fact",
        occurred_at=datetime(2026, 9, 9, 1, 0, tzinfo=UTC),
    )

    with SessionLocal() as caller:
        provider = _DeletingProvider(
            lambda: _assert_no_caller_transaction(caller),
            memory_id=second_id,
        )
        result = asyncio.run(
            summarize_month(
                caller,
                user_id=owner,
                target_month=TARGET_MONTH,
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert len(provider.requests) == 1
    prompt = provider.requests[0].input_text
    assert '"slot":"M1"' in prompt
    assert '"slot":"M2"' in prompt
    assert "first monthly fact" in prompt
    assert "second monthly fact" in prompt
    assert first_id != second_id
    assert result.status == MonthlySummaryStatus.DATA_CHANGED_DURING_GENERATION
    assert result.summary is None
    assert result.citations == ()

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_excluded_memory_evidence_promotion_invalidates_snapshot() -> None:
    owner = _seed_user("authority-race")
    visible_id = _seed_memory(
        user_id=owner,
        content="visible monthly fact",
        occurred_at=datetime(2026, 9, 8, 1, 0, tzinfo=UTC),
    )
    excluded_text = "excluded monthly fact gains evidence"
    excluded_id = _seed_memory(
        user_id=owner,
        content=excluded_text,
        occurred_at=datetime(2026, 9, 9, 1, 0, tzinfo=UTC),
        add_source=False,
    )

    with SessionLocal() as caller:
        provider = _AddingEvidenceProvider(
            lambda: _assert_no_caller_transaction(caller),
            memory_id=excluded_id,
            raw_text=excluded_text,
        )
        result = asyncio.run(
            summarize_month(
                caller,
                user_id=owner,
                target_month=TARGET_MONTH,
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert len(provider.requests) == 1
    prompt = provider.requests[0].input_text
    assert '"slot":"M1"' in prompt
    assert '"slot":"M2"' not in prompt
    assert "visible monthly fact" in prompt
    assert excluded_text not in prompt
    assert visible_id != excluded_id
    assert result.status == MonthlySummaryStatus.DATA_CHANGED_DURING_GENERATION
    assert result.summary is None
    assert result.citations == ()

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_new_month_fact_invalidates_inventory() -> None:
    owner = _seed_user("insert-race")
    _seed_memory(
        user_id=owner,
        content="生成前的月事实",
        occurred_at=datetime(2026, 9, 8, 1, 0, tzinfo=UTC),
    )

    with SessionLocal() as caller:
        provider = _InsertingProvider(
            lambda: _assert_no_caller_transaction(caller),
            user_id=owner,
        )
        result = asyncio.run(
            summarize_month(
                caller,
                user_id=owner,
                target_month=TARGET_MONTH,
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert result.status == MonthlySummaryStatus.DATA_CHANGED_DURING_GENERATION
    assert result.summary is None
    assert result.citations == ()
    assert len(provider.requests) == 1

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def _assert_month_cap_blocks_provider() -> None:
    owner = _seed_user("cap")
    _seed_memory_cap(owner)

    provider = DeterministicAIProvider(
        output_text='{"summary":"不应生成","citations":["M1"]}',
    )
    with SessionLocal() as db:
        result = asyncio.run(
            summarize_month(
                db,
                user_id=owner,
                target_month=TARGET_MONTH,
                ai_gateway=AIGateway(_settings(), provider),
            )
        )

    assert result.status == MonthlySummaryStatus.SUMMARY_INCOMPLETE
    assert result.incomplete_code == "MONTH_MEMORY_SCAN_LIMIT_REACHED"
    assert provider.requests == []

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, owner))
        cleanup.commit()


def main() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("S3-016 integration gate requires PostgreSQL")

    _assert_complete_month_transaction_gap_and_overlap_visit()
    _assert_uncited_visible_slot_drift_fails_closed()
    _assert_excluded_memory_evidence_promotion_invalidates_snapshot()
    _assert_new_month_fact_invalidates_inventory()
    _assert_month_cap_blocks_provider()
    print("PostgreSQL Monthly Summary invariants PASS")


if __name__ == "__main__":
    main()
