from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.annual_memoir_models import AnnualMemoirStatus
from app.annual_summary_models import (
    AnnualSummaryCitation,
    AnnualSummaryResult,
    AnnualSummarySlotKind,
    AnnualSummaryStatus,
)
from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventKind
from app.media_models import MediaAsset, MediaEvidenceLink, MediaKind, MediaStatus
from app.models import Memory, MemorySource, MemoryType, SourceType, User
from app.services.annual_memoir_service import (
    AnnualMemoirError,
    build_annual_memoir,
    list_annual_memoir_photos,
)
from app.services.answer_trust_service import AnswerTrustState

REFERENCE = datetime(2026, 9, 28, 12, tzinfo=UTC)


def _owner(label: str, *, timezone: str = "UTC") -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label, timezone=timezone))
        db.commit()
    return user_id


def _photo(
    user_id: UUID,
    *,
    occurred_at: datetime,
    title: str | None = None,
    deleted: bool = False,
    status: MediaStatus = MediaStatus.READY,
    kind: MediaKind = MediaKind.IMAGE,
    linked: bool = True,
    media_owner: UUID | None = None,
) -> tuple[UUID, UUID]:
    memory_id = uuid4()
    source_id = uuid4()
    media_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                memory_type=MemoryType.PHOTO,
                title=title,
                content="private photo memory content",
                occurred_at=occurred_at,
                source_type=SourceType.USER_PHOTO,
                confidence=1.0,
                is_confirmed=True,
                is_deleted=deleted,
            )
        )
        db.commit()
        db.add(
            MemorySource(
                id=source_id,
                memory_id=memory_id,
                source_type=SourceType.USER_PHOTO,
                confidence=1.0,
            )
        )
        db.add(
            MediaAsset(
                id=media_id,
                user_id=media_owner or user_id,
                client_upload_id=uuid4(),
                kind=kind,
                status=status,
                upload_object_key=f"private/staging/{media_id}",
                object_key=f"private/final/{media_id}",
                content_type="image/jpeg" if kind == MediaKind.IMAGE else "audio/mpeg",
                size_bytes=100,
                storage_etag="private-etag",
            )
        )
        db.commit()
        if linked:
            db.add(
                MediaEvidenceLink(
                    media_id=media_id,
                    memory_source_id=source_id,
                )
            )
            db.commit()
    return memory_id, media_id


def _event(user_id: UUID, *, started_at: datetime, title: str = "Event") -> UUID:
    event_id = uuid4()
    with SessionLocal() as db:
        db.add(
            LifeEvent(
                id=event_id,
                user_id=user_id,
                event_kind=LifeEventKind.WORK,
                title=title,
                started_at=started_at,
            )
        )
        db.commit()
    return event_id


def _summary(
    status: AnnualSummaryStatus,
    *,
    target_year: str = "2025",
    timezone: str = "UTC",
    summary: str | None = None,
    memory_id: UUID | None = None,
) -> AnnualSummaryResult:
    citations = ()
    if memory_id is not None:
        citations = (
            AnnualSummaryCitation(
                slot="Y1",
                kind=AnnualSummarySlotKind.MEMORY,
                memory_id=memory_id,
                memory_source_id=uuid4(),
                visit_id=None,
                trust_state=AnswerTrustState.CONFIRMED,
            ),
        )
    return AnnualSummaryResult(
        status=status,
        target_year=target_year,
        timezone=timezone,
        summary=summary,
        citations=citations,
        incomplete_code=None,
        provider_error_code=None,
        ai_provenance=None,
    )


def _patch_summary(monkeypatch, result: AnnualSummaryResult):
    calls = []

    async def fake_summary(db, **kwargs):
        del db
        calls.append(kwargs)
        return result

    monkeypatch.setattr(
        "app.services.annual_memoir_service.summarize_year",
        fake_summary,
    )
    return calls


@pytest.mark.asyncio
async def test_ready_memoir_reuses_narrative_timeline_and_verified_photo(monkeypatch):
    owner = _owner("memoir-ready")
    photo_memory_id, photo_media_id = _photo(
        owner,
        occurred_at=datetime(2025, 5, 2, tzinfo=UTC),
        title="Spring photo",
    )
    event_id = _event(
        owner,
        started_at=datetime(2025, 6, 3, tzinfo=UTC),
        title="Structured event",
    )
    result = _summary(
        AnnualSummaryStatus.ANNUAL_SUMMARY_READY,
        summary="Exact S3-017 narrative",
        memory_id=photo_memory_id,
    )
    calls = _patch_summary(monkeypatch, result)

    with SessionLocal() as db:
        memoir = await build_annual_memoir(
            db,
            user_id=owner,
            target_year="2025",
            ai_gateway=object(),
            reference_utc=REFERENCE,
        )

    assert memoir.status == AnnualMemoirStatus.MEMOIR_READY
    assert memoir.narrative == "Exact S3-017 narrative"
    assert memoir.narrative_status == AnnualSummaryStatus.ANNUAL_SUMMARY_READY
    assert memoir.narrative_citations[0].memory_id == photo_memory_id
    assert "memory_source_id" not in memoir.narrative_citations[0].model_dump()
    assert memoir.timeline_items[0].life_event_id == event_id
    assert memoir.photo_items[0].memory_id == photo_memory_id
    assert memoir.photo_items[0].media_id == photo_media_id
    assert calls[0]["target_year"] == "2025"
    assert calls[0]["reference_utc"] == REFERENCE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "narrative_status",
    [
        AnnualSummaryStatus.PROVIDER_FAILED,
        AnnualSummaryStatus.SUMMARY_INCOMPLETE,
        AnnualSummaryStatus.MALFORMED_PROVIDER_OUTPUT,
        AnnualSummaryStatus.INVALID_CITATION,
        AnnualSummaryStatus.DATA_CHANGED_DURING_GENERATION,
    ],
)
async def test_narrative_failure_degrades_to_partial_without_hiding_sections(
    monkeypatch,
    narrative_status,
):
    owner = _owner(f"memoir-partial-{narrative_status.value}")
    _, media_id = _photo(
        owner,
        occurred_at=datetime(2025, 4, 1, tzinfo=UTC),
    )
    event_id = _event(owner, started_at=datetime(2025, 7, 1, tzinfo=UTC))
    _patch_summary(monkeypatch, _summary(narrative_status))

    with SessionLocal() as db:
        memoir = await build_annual_memoir(
            db,
            user_id=owner,
            target_year="2025",
            ai_gateway=object(),
            reference_utc=REFERENCE,
        )

    assert memoir.status == AnnualMemoirStatus.MEMOIR_PARTIAL
    assert memoir.narrative_status == narrative_status
    assert memoir.narrative is None
    assert memoir.timeline_items[0].life_event_id == event_id
    assert memoir.photo_items[0].media_id == media_id


@pytest.mark.asyncio
async def test_empty_year_is_typed_empty(monkeypatch):
    owner = _owner("memoir-empty")
    _patch_summary(
        monkeypatch,
        _summary(AnnualSummaryStatus.NO_SUMMARIZABLE_EVIDENCE),
    )
    with SessionLocal() as db:
        memoir = await build_annual_memoir(
            db,
            user_id=owner,
            target_year="2025",
            ai_gateway=object(),
            reference_utc=REFERENCE,
        )
    assert memoir.status == AnnualMemoirStatus.MEMOIR_EMPTY
    assert memoir.narrative is None
    assert memoir.timeline_items == []
    assert memoir.photo_items == []


@pytest.mark.asyncio
async def test_closed_year_boundary_rejects_current_and_future(monkeypatch):
    owner = _owner("memoir-closed-year")
    _patch_summary(
        monkeypatch,
        _summary(AnnualSummaryStatus.NO_SUMMARIZABLE_EVIDENCE),
    )
    with SessionLocal() as db:
        for year in ("2026", "2027"):
            with pytest.raises(AnnualMemoirError) as exc:
                await build_annual_memoir(
                    db,
                    user_id=owner,
                    target_year=year,
                    ai_gateway=object(),
                    reference_utc=REFERENCE,
                )
            assert exc.value.code == "ANNUAL_MEMOIR_YEAR_NOT_CLOSED"


def test_photo_gallery_requires_complete_verified_owner_chain():
    owner = _owner("memoir-photo-authority")
    other = _owner("memoir-photo-other")
    eligible_memory, eligible_media = _photo(
        owner,
        occurred_at=datetime(2025, 1, 2, tzinfo=UTC),
        title="eligible",
    )
    deleted_memory, _ = _photo(
        owner,
        occurred_at=datetime(2025, 1, 3, tzinfo=UTC),
        deleted=True,
    )
    pending_memory, _ = _photo(
        owner,
        occurred_at=datetime(2025, 1, 4, tzinfo=UTC),
        status=MediaStatus.PENDING,
    )
    audio_memory, _ = _photo(
        owner,
        occurred_at=datetime(2025, 1, 5, tzinfo=UTC),
        kind=MediaKind.AUDIO,
    )
    unlinked_memory, _ = _photo(
        owner,
        occurred_at=datetime(2025, 1, 6, tzinfo=UTC),
        linked=False,
    )
    cross_owner_memory, _ = _photo(
        owner,
        occurred_at=datetime(2025, 1, 7, tzinfo=UTC),
        media_owner=other,
    )

    with SessionLocal() as db:
        page = list_annual_memoir_photos(
            db,
            user_id=owner,
            target_year="2025",
            reference_utc=REFERENCE,
        )

    assert [(item.memory_id, item.media_id) for item in page.items] == [
        (eligible_memory, eligible_media)
    ]
    excluded = {
        deleted_memory,
        pending_memory,
        audio_memory,
        unlinked_memory,
        cross_owner_memory,
    }
    assert not excluded.intersection({item.memory_id for item in page.items})
    payload = page.model_dump(mode="json")
    text = str(payload)
    for forbidden in (
        "private photo memory content",
        "object_key",
        "upload_object_key",
        "storage_etag",
        "download",
        "http",
    ):
        assert forbidden not in text


def test_photo_preview_24_plus_1_and_cursor_has_no_replay():
    owner = _owner("memoir-photo-page")
    expected = []
    for index in range(25):
        memory_id, media_id = _photo(
            owner,
            occurred_at=datetime(2025, 1, 1 + index, tzinfo=UTC),
            title=f"photo-{index}",
        )
        expected.append((memory_id, media_id))

    with SessionLocal() as db:
        first = list_annual_memoir_photos(
            db,
            user_id=owner,
            target_year="2025",
            reference_utc=REFERENCE,
        )
        assert len(first.items) == 24
        assert first.next_cursor is not None
        second = list_annual_memoir_photos(
            db,
            user_id=owner,
            target_year="2025",
            cursor_value=first.next_cursor,
            reference_utc=REFERENCE,
        )

    assert len(second.items) == 1
    all_rows = [(item.memory_id, item.media_id) for item in first.items + second.items]
    assert len(all_rows) == 25
    assert len(set(all_rows)) == 25
    assert set(all_rows) == set(expected)


@pytest.mark.parametrize(
    ("timezone", "inside", "outside"),
    [
        (
            "UTC",
            datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
            datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC),
        ),
        (
            "Asia/Shanghai",
            datetime(2024, 12, 31, 16, 0, tzinfo=UTC),
            datetime(2024, 12, 31, 15, 59, 59, tzinfo=UTC),
        ),
        (
            "America/Los_Angeles",
            datetime(2025, 1, 1, 8, 0, tzinfo=UTC),
            datetime(2025, 1, 1, 7, 59, 59, tzinfo=UTC),
        ),
    ],
)
def test_photo_year_membership_uses_user_local_boundary(timezone, inside, outside):
    owner = _owner(f"memoir-boundary-{timezone}", timezone=timezone)
    inside_memory, _ = _photo(owner, occurred_at=inside)
    outside_memory, _ = _photo(owner, occurred_at=outside)
    with SessionLocal() as db:
        page = list_annual_memoir_photos(
            db,
            user_id=owner,
            target_year="2025",
            reference_utc=REFERENCE,
        )
    ids = {item.memory_id for item in page.items}
    assert inside_memory in ids
    assert outside_memory not in ids


def test_photo_cursor_rejects_malformed_wrong_version_naive_and_bad_uuid():
    owner = _owner("memoir-photo-cursor")
    values = [
        "not-a-cursor",
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "v": 2,
                    "t": REFERENCE.isoformat(),
                    "m": str(uuid4()),
                    "i": str(uuid4()),
                }
            ).encode()
        ).decode().rstrip("="),
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "v": 1,
                    "t": "2025-01-01T00:00:00",
                    "m": str(uuid4()),
                    "i": str(uuid4()),
                }
            ).encode()
        ).decode().rstrip("="),
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "v": 1,
                    "t": REFERENCE.isoformat(),
                    "m": "bad",
                    "i": str(uuid4()),
                }
            ).encode()
        ).decode().rstrip("="),
    ]
    with SessionLocal() as db:
        for cursor in values:
            with pytest.raises(AnnualMemoirError) as exc:
                list_annual_memoir_photos(
                    db,
                    user_id=owner,
                    target_year="2025",
                    cursor_value=cursor,
                    reference_utc=REFERENCE,
                )
            assert exc.value.code == "ANNUAL_MEMOIR_PHOTO_CURSOR_INVALID"


async def test_api_rejects_non_strict_current_and_future_year(client):
    token = await client.post("/v1/auth/dev-token", json={"nickname": "memoir-api-year"})
    assert token.status_code == 200
    headers = {"Authorization": f"Bearer {token.json()['access_token']}"}

    invalid = await client.post(
        "/v1/memoirs/annual",
        headers=headers,
        json={"target_year": "25"},
    )
    assert invalid.status_code == 422

    current = await client.post(
        "/v1/memoirs/annual",
        headers=headers,
        json={"target_year": "2026"},
    )
    assert current.status_code == 422
    assert current.json()["detail"] == "ANNUAL_MEMOIR_YEAR_NOT_CLOSED"


def test_scope_lock_reuses_canonical_services_without_new_ai_or_persistence():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app/services/annual_memoir_service.py").read_text()
    assert "summarize_year(" in source
    assert "list_life_history_timeline(" in source
    for forbidden in [
        "AIInferenceRequest",
        "system_instruction",
        "infer_image",
        "OCR",
        "Vision",
        "face",
        "Embedding",
        "retrieve_memories",
        "answer_from_memory_rag",
        ".add(",
        ".commit(",
        ".delete(",
    ]:
        assert forbidden not in source
    assert list((root / "migrations/versions").glob("0025*")) == []
