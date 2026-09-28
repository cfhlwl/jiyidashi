from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from inspect import signature
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.db import SessionLocal
from app.life_memoir_models import LifeMemoirChapterStatus
from app.life_stage_models import LifeStage, LifeStageKind
from app.long_term_reasoning_models import (
    LongTermEvidenceKind,
    LongTermReasoningCitation,
    LongTermReasoningResult,
    LongTermReasoningStatus,
)
from app.models import User
from app.services.answer_trust_service import AnswerTrustState
from app.services.life_memoir_service import (
    LIFE_MEMOIR_QUESTION,
    LifeMemoirError,
    build_life_memoir_chapter,
    list_life_memoir_stages,
)
from app.services.long_term_reasoning_service import LongTermReasoningError


def _owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label))
        db.commit()
    return user_id


def _stage(
    user_id: UUID,
    *,
    stage_id: UUID | None = None,
    kind: LifeStageKind = LifeStageKind.WORK,
    title: str = "Stage",
    custom_label: str | None = None,
    note: str | None = "private note",
    started_at: datetime,
    ended_at: datetime | None = None,
) -> UUID:
    stage_id = stage_id or uuid4()
    with SessionLocal() as db:
        db.add(
            LifeStage(
                id=stage_id,
                user_id=user_id,
                stage_kind=kind,
                title=title,
                custom_label=custom_label,
                note=note,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        db.commit()
    return stage_id


def _page(user_id: UUID, *, limit: int = 50, cursor: str | None = None):
    with SessionLocal() as db:
        return list_life_memoir_stages(
            db,
            user_id=user_id,
            limit=limit,
            cursor_value=cursor,
        )


def _cursor(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_stage_index_owner_isolation_projection_and_open_overlap_semantics():
    owner = _owner("life-memoir-index-owner")
    other = _owner("life-memoir-index-other")
    start = datetime(2024, 1, 1, tzinfo=UTC)
    work = _stage(
        owner,
        kind=LifeStageKind.WORK,
        title="Same title",
        started_at=start,
        ended_at=None,
    )
    family = _stage(
        owner,
        kind=LifeStageKind.FAMILY,
        title="Same title",
        started_at=start + timedelta(days=30),
        ended_at=None,
    )
    _stage(
        other,
        title="Private other",
        started_at=start + timedelta(days=10),
    )

    page = _page(owner, limit=100)
    assert [item.life_stage_id for item in page.items] == [work, family]
    assert all(item.ended_at is None for item in page.items)

    payload = page.model_dump(mode="json")
    assert set(payload) == {"items", "next_cursor"}
    assert set(payload["items"][0]) == {
        "life_stage_id",
        "stage_kind",
        "title",
        "custom_label",
        "started_at",
        "ended_at",
    }
    rendered = str(payload)
    for forbidden in (
        "private note",
        "Private other",
        "user_id",
        "revision",
        "created_at",
        "updated_at",
        "is_active",
    ):
        assert forbidden not in rendered


def test_stage_index_started_at_asc_uuid_tie_break_and_cursor_no_replay():
    owner = _owner("life-memoir-index-order")
    timestamp = datetime(2025, 1, 1, tzinfo=UTC)
    low = UUID("11111111-1111-4111-8111-111111111111")
    high = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    later = uuid4()
    _stage(owner, stage_id=high, started_at=timestamp)
    _stage(owner, stage_id=low, started_at=timestamp)
    _stage(owner, stage_id=later, started_at=timestamp + timedelta(days=1))

    first = _page(owner, limit=1)
    assert [item.life_stage_id for item in first.items] == [low]
    assert first.next_cursor is not None

    second = _page(owner, limit=1, cursor=first.next_cursor)
    assert [item.life_stage_id for item in second.items] == [high]
    assert second.next_cursor is not None

    third = _page(owner, limit=100, cursor=second.next_cursor)
    assert [item.life_stage_id for item in third.items] == [later]
    assert third.next_cursor is None

    rows = first.items + second.items + third.items
    assert len({item.life_stage_id for item in rows}) == 3


def test_stage_index_limit_100_and_limit_plus_one_cursor():
    owner = _owner("life-memoir-index-limit")
    base = datetime(2020, 1, 1, tzinfo=UTC)
    for index in range(101):
        _stage(owner, started_at=base + timedelta(days=index))

    page = _page(owner, limit=100)
    assert len(page.items) == 100
    assert page.next_cursor is not None
    final = _page(owner, limit=100, cursor=page.next_cursor)
    assert len(final.items) == 1
    assert final.next_cursor is None


@pytest.mark.parametrize(
    "value",
    [
        "not-a-cursor",
        _cursor(
            {
                "v": 2,
                "t": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
                "id": str(uuid4()),
            }
        ),
        _cursor(
            {
                "v": 1,
                "t": "2025-01-01T00:00:00",
                "id": str(uuid4()),
            }
        ),
        _cursor(
            {
                "v": 1,
                "t": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
                "id": "bad-uuid",
            }
        ),
    ],
)
def test_stage_index_cursor_validation(value):
    owner = _owner("life-memoir-bad-cursor")
    with pytest.raises(LifeMemoirError) as exc:
        _page(owner, cursor=value)
    assert exc.value.code == "LIFE_MEMOIR_STAGE_CURSOR_INVALID"


def _reason_result(
    status: LongTermReasoningStatus,
    *,
    answer: str | None = None,
    citations: tuple[LongTermReasoningCitation, ...] = (),
) -> LongTermReasoningResult:
    return LongTermReasoningResult(
        status=status,
        answer=answer,
        citations=citations,
        provider_error_code=None,
        ai_provenance=None,
    )


@pytest.mark.asyncio
async def test_chapter_calls_canonical_reasoning_once_with_fixed_question(monkeypatch):
    owner = _owner("life-memoir-chapter-call")
    stage_id = uuid4()
    calls = []
    citation = LongTermReasoningCitation(
        slot="E3",
        kind=LongTermEvidenceKind.MEMORY,
        life_stage_id=stage_id,
        life_event_id=uuid4(),
        memory_id=uuid4(),
        memory_source_id=uuid4(),
        memory_trust_state=AnswerTrustState.CONFIRMED,
    )

    async def fake_reason(db, **kwargs):
        del db
        calls.append(kwargs)
        return _reason_result(
            LongTermReasoningStatus.ANSWERED,
            answer="exact canonical answer",
            citations=(citation,),
        )

    monkeypatch.setattr(
        "app.services.life_memoir_service.reason_about_life_stage",
        fake_reason,
    )

    with SessionLocal() as db:
        chapter = await build_life_memoir_chapter(
            db,
            user_id=owner,
            life_stage_id=stage_id,
            ai_gateway=object(),
        )

    assert len(calls) == 1
    assert calls[0]["user_id"] == owner
    assert calls[0]["life_stage_id"] == stage_id
    assert calls[0]["question"] == LIFE_MEMOIR_QUESTION
    assert chapter.status == LifeMemoirChapterStatus.CHAPTER_READY
    assert chapter.reasoning_status == LongTermReasoningStatus.ANSWERED
    assert chapter.narrative == "exact canonical answer"
    assert chapter.citations[0].model_dump() == {
        "slot": citation.slot,
        "kind": citation.kind,
        "life_stage_id": citation.life_stage_id,
        "life_event_id": citation.life_event_id,
        "memory_id": citation.memory_id,
        "memory_source_id": citation.memory_source_id,
        "memory_trust_state": citation.memory_trust_state,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reasoning_status", "chapter_status"),
    [
        (
            LongTermReasoningStatus.NO_ANSWERABLE_EVIDENCE,
            LifeMemoirChapterStatus.CHAPTER_EMPTY,
        ),
        (
            LongTermReasoningStatus.EVIDENCE_INCOMPLETE,
            LifeMemoirChapterStatus.CHAPTER_PARTIAL,
        ),
        (
            LongTermReasoningStatus.PROVIDER_FAILED,
            LifeMemoirChapterStatus.CHAPTER_PARTIAL,
        ),
        (
            LongTermReasoningStatus.MALFORMED_PROVIDER_OUTPUT,
            LifeMemoirChapterStatus.CHAPTER_PARTIAL,
        ),
        (
            LongTermReasoningStatus.INVALID_CITATION,
            LifeMemoirChapterStatus.CHAPTER_PARTIAL,
        ),
        (
            LongTermReasoningStatus.EVIDENCE_CHANGED_DURING_GENERATION,
            LifeMemoirChapterStatus.CHAPTER_PARTIAL,
        ),
    ],
)
async def test_chapter_status_mapping_has_no_fallback_prose(
    monkeypatch,
    reasoning_status,
    chapter_status,
):
    owner = _owner(f"life-memoir-{reasoning_status.value}")
    stage_id = uuid4()

    async def fake_reason(db, **kwargs):
        del db, kwargs
        return _reason_result(reasoning_status)

    monkeypatch.setattr(
        "app.services.life_memoir_service.reason_about_life_stage",
        fake_reason,
    )
    with SessionLocal() as db:
        chapter = await build_life_memoir_chapter(
            db,
            user_id=owner,
            life_stage_id=stage_id,
            ai_gateway=object(),
        )

    assert chapter.status == chapter_status
    assert chapter.reasoning_status == reasoning_status
    assert chapter.narrative is None
    assert chapter.citations == []


@pytest.mark.asyncio
async def test_life_stage_not_found_is_preserved(monkeypatch):
    owner = _owner("life-memoir-not-found")
    stage_id = uuid4()

    async def fake_reason(db, **kwargs):
        del db, kwargs
        raise LongTermReasoningError("LIFE_STAGE_NOT_FOUND", 404)

    monkeypatch.setattr(
        "app.services.life_memoir_service.reason_about_life_stage",
        fake_reason,
    )
    with SessionLocal() as db:
        with pytest.raises(LongTermReasoningError) as exc:
            await build_life_memoir_chapter(
                db,
                user_id=owner,
                life_stage_id=stage_id,
                ai_gateway=object(),
            )
    assert exc.value.code == "LIFE_STAGE_NOT_FOUND"
    assert exc.value.status_code == 404


def test_api_has_no_client_question_parameter_and_scope_lock():
    from app.api.life_memoir import build_life_memoir_chapter_route

    assert "payload" not in signature(build_life_memoir_chapter_route).parameters
    assert "question" not in signature(build_life_memoir_chapter_route).parameters

    root = Path(__file__).resolve().parents[1]
    source = (root / "app/services/life_memoir_service.py").read_text()
    assert "reason_about_life_stage(" in source
    assert "LIFE_MEMOIR_QUESTION" in source
    for forbidden in (
        "AIInferenceRequest",
        "system_instruction",
        "LifeEventMemoryLink",
        "resolve_memory_answer_trust",
        "EmbeddingGateway",
        "retrieve_memories",
        "answer_from_memory_rag",
        "PersonRelationship",
        "build_annual_memoir",
        "summarize_year",
        "list_annual_memoir_photos",
        "Vision",
        "OCR",
        ".add(",
        ".commit(",
        ".delete(",
    ):
        assert forbidden not in source
    assert list((root / "migrations/versions").glob("0025*")) == []
