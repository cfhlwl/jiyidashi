from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import Memory, MemorySource, SourceType, User
from app.services.evidence_ranking_service import (
    EvidenceRankClass,
    EvidenceRankingError,
    rank_class_for_source_type,
    rank_evidence_sources,
)
from app.services.query_service import query_memory


def _owner(db, label: str) -> UUID:
    user = User(nickname=f"evidence-rank-{label}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


def _memory(
    db,
    user_id: UUID,
    *,
    content: str,
    confirmed: bool = True,
    deleted: bool = False,
    source_type: SourceType = SourceType.USER_TEXT,
) -> Memory:
    memory = Memory(
        user_id=user_id,
        content=content,
        source_type=source_type,
        confidence=1.0 if source_type != SourceType.AI_INFERENCE else 0.5,
        is_confirmed=confirmed,
        is_deleted=deleted,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def _source(
    db,
    memory: Memory,
    source_type: SourceType,
    confidence: float,
    created_at: datetime,
    *,
    source_id: UUID | None = None,
) -> MemorySource:
    source = MemorySource(
        id=source_id or uuid4(),
        memory_id=memory.id,
        source_type=source_type,
        raw_text=f"{source_type.value}:{confidence}",
        confidence=confidence,
        created_at=created_at,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@pytest.mark.parametrize(
    ("source_type", "expected"),
    [
        (SourceType.USER_TEXT, EvidenceRankClass.USER_DIRECT),
        (SourceType.USER_VOICE, EvidenceRankClass.USER_DIRECT),
        (SourceType.USER_PHOTO, EvidenceRankClass.USER_DIRECT),
        (SourceType.GPS, EvidenceRankClass.SENSOR_DIRECT),
        (SourceType.PHOTO_EXIF, EvidenceRankClass.SENSOR_DIRECT),
        (SourceType.SYSTEM_PLACE, EvidenceRankClass.SYSTEM_DERIVED),
        (SourceType.AI_INFERENCE, EvidenceRankClass.AI_INFERENCE),
    ],
)
def test_exact_source_type_mapping(source_type, expected):
    assert rank_class_for_source_type(source_type) == expected


def test_unsupported_source_type_fails_closed():
    with pytest.raises(EvidenceRankingError) as exc_info:
        rank_class_for_source_type("FUTURE_PROVIDER_SCORE")  # type: ignore[arg-type]
    assert exc_info.value.code == "EVIDENCE_SOURCE_TYPE_UNSUPPORTED"


def test_ai_high_confidence_never_outranks_user_direct_low_confidence():
    with SessionLocal() as db:
        owner = _owner(db, "trust-boundary")
        user_memory = _memory(db, owner, content="用户直接记录")
        ai_memory = _memory(
            db,
            owner,
            content="AI 推断",
            confirmed=False,
            source_type=SourceType.AI_INFERENCE,
        )
        now = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)
        direct = _source(db, user_memory, SourceType.USER_TEXT, 0.50, now)
        inference = _source(
            db,
            ai_memory,
            SourceType.AI_INFERENCE,
            0.99,
            now + timedelta(days=1),
        )

        ranked = rank_evidence_sources(db, user_id=owner)

        assert [item.memory_source_id for item in ranked] == [direct.id, inference.id]
        assert [item.rank_class for item in ranked] == [
            EvidenceRankClass.USER_DIRECT,
            EvidenceRankClass.AI_INFERENCE,
        ]


def test_sensor_direct_always_outranks_system_derived():
    with SessionLocal() as db:
        owner = _owner(db, "sensor-system")
        memory = _memory(db, owner, content="位置证据")
        now = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)
        system = _source(db, memory, SourceType.SYSTEM_PLACE, 1.0, now + timedelta(days=2))
        gps = _source(db, memory, SourceType.GPS, 0.40, now)
        exif = _source(db, memory, SourceType.PHOTO_EXIF, 0.30, now - timedelta(days=1))

        ranked = rank_evidence_sources(db, user_id=owner)

        assert [item.memory_source_id for item in ranked] == [gps.id, exif.id, system.id]


def test_same_class_confidence_then_recency_then_uuid_are_deterministic():
    with SessionLocal() as db:
        owner = _owner(db, "tie-breaks")
        memory = _memory(db, owner, content="同类证据")
        base_time = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)
        high_old = _source(db, memory, SourceType.USER_TEXT, 0.90, base_time)
        high_new_uuid_late = _source(
            db,
            memory,
            SourceType.USER_VOICE,
            0.90,
            base_time + timedelta(hours=1),
            source_id=UUID("00000000-0000-0000-0000-000000000002"),
        )
        high_new_uuid_early = _source(
            db,
            memory,
            SourceType.USER_PHOTO,
            0.90,
            base_time + timedelta(hours=1),
            source_id=UUID("00000000-0000-0000-0000-000000000001"),
        )
        low_new = _source(
            db,
            memory,
            SourceType.USER_TEXT,
            0.80,
            base_time + timedelta(days=2),
        )

        first = rank_evidence_sources(db, user_id=owner)
        second = rank_evidence_sources(db, user_id=owner)

        assert first == second
        assert [item.memory_source_id for item in first] == [
            high_new_uuid_early.id,
            high_new_uuid_late.id,
            high_old.id,
            low_new.id,
        ]


def test_owner_scope_and_deleted_memory_exclusion():
    with SessionLocal() as db:
        owner_a = _owner(db, "owner-a")
        owner_b = _owner(db, "owner-b")
        active = _memory(db, owner_a, content="owner-a-active")
        deleted = _memory(db, owner_a, content="owner-a-deleted", deleted=True)
        foreign = _memory(db, owner_b, content="owner-b")
        now = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)

        active_source = _source(db, active, SourceType.USER_TEXT, 0.8, now)
        _source(db, deleted, SourceType.USER_TEXT, 1.0, now + timedelta(days=2))
        _source(db, foreign, SourceType.USER_TEXT, 1.0, now + timedelta(days=3))

        ranked = rank_evidence_sources(db, user_id=owner_a)

        assert [item.memory_source_id for item in ranked] == [active_source.id]
        assert {item.memory_id for item in ranked} == {active.id}


def test_memory_id_filter_cannot_escape_owner_scope():
    with SessionLocal() as db:
        owner_a = _owner(db, "candidate-owner-a")
        owner_b = _owner(db, "candidate-owner-b")
        a_memory = _memory(db, owner_a, content="A")
        b_memory = _memory(db, owner_b, content="B")
        now = datetime(2026, 9, 21, 7, 0, tzinfo=UTC)
        a_source = _source(db, a_memory, SourceType.GPS, 0.7, now)
        _source(db, b_memory, SourceType.USER_TEXT, 1.0, now)

        ranked = rank_evidence_sources(
            db,
            user_id=owner_a,
            memory_ids=[a_memory.id, b_memory.id],
        )

        assert [item.memory_source_id for item in ranked] == [a_source.id]


def test_ranking_is_read_only_and_persists_no_score():
    with SessionLocal() as db:
        owner = _owner(db, "read-only")
        memory = _memory(db, owner, content="只读排序")
        _source(
            db,
            memory,
            SourceType.SYSTEM_PLACE,
            0.75,
            datetime(2026, 9, 21, 7, 0, tzinfo=UTC),
        )
        before_memories = db.scalar(select(func.count(Memory.id)))
        before_sources = db.scalar(select(func.count(MemorySource.id)))

        ranked = rank_evidence_sources(db, user_id=owner)

        assert len(ranked) == 1
        assert not db.new
        assert not db.dirty
        assert not db.deleted
        assert db.scalar(select(func.count(Memory.id))) == before_memories
        assert db.scalar(select(func.count(MemorySource.id))) == before_sources


def test_ranking_does_not_autoflush_pending_or_dirty_session_state():
    with SessionLocal() as db:
        owner = _owner(db, "no-autoflush")
        memory = _memory(db, owner, content="已提交证据")
        committed = _source(
            db,
            memory,
            SourceType.USER_TEXT,
            0.70,
            datetime(2026, 9, 21, 7, 0, tzinfo=UTC),
        )

        # Load the object that will become dirty before introducing pending state;
        # otherwise this setup query itself would legitimately trigger Session autoflush.
        dirty_owner = db.get(User, owner)
        assert dirty_owner is not None

        pending = MemorySource(
            id=uuid4(),
            memory_id=memory.id,
            source_type=SourceType.AI_INFERENCE,
            raw_text="尚未提交的 Evidence",
            confidence=0.99,
            created_at=datetime(2026, 9, 21, 8, 0, tzinfo=UTC),
        )
        dirty_owner.nickname = "ranking-must-not-flush-me"
        db.add(pending)

        before_new = set(db.new)
        before_dirty = set(db.dirty)

        # From this point until assertions, ranking is the only ORM query executed.
        ranked = rank_evidence_sources(db, user_id=owner)

        # Pending Evidence cannot become part of the persisted ranking set merely because
        # ranking executed a SELECT, and unrelated dirty state must remain unflushed.
        assert [item.memory_source_id for item in ranked] == [committed.id]
        assert pending in db.new
        assert dirty_owner in db.dirty
        assert set(db.new) == before_new
        assert set(db.dirty) == before_dirty


def test_direct_evidence_rank_does_not_promote_unconfirmed_ai_memory():
    with SessionLocal() as db:
        owner = _owner(db, "no-trust-promotion")
        memory = _memory(
            db,
            owner,
            content="银行卡可能在书房抽屉",
            confirmed=False,
            source_type=SourceType.AI_INFERENCE,
        )
        source = _source(
            db,
            memory,
            SourceType.USER_TEXT,
            1.0,
            datetime(2026, 9, 21, 7, 0, tzinfo=UTC),
        )

        ranked = rank_evidence_sources(db, user_id=owner)
        response = query_memory(db, owner, "银行卡抽屉")

        assert ranked[0].memory_source_id == source.id
        assert ranked[0].rank_class == EvidenceRankClass.USER_DIRECT
        assert response.can_answer is False
        assert response.reason == "NO_EVIDENCE"


def test_no_public_evidence_ranking_route():
    from app.main import app

    paths = {
        path
        for route in app.routes
        if (path := getattr(route, "path", None)) is not None
    }
    assert not any("evidence/rank" in path or "evidence-ranking" in path for path in paths)
