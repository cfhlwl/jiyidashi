"""Real PostgreSQL composition gate for V2-010 Annual Electronic Memoir."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from app.annual_summary_models import AnnualSummaryResult, AnnualSummaryStatus
from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventKind
from app.life_event_schemas import LifeEventPatch
from app.media_models import MediaAsset, MediaEvidenceLink, MediaKind, MediaStatus
from app.models import Memory, MemorySource, MemoryType, SourceType, User
from app.services.entitlement_service import create_legacy_full_entitlement
from app.services.annual_memoir_service import (
    build_annual_memoir,
    list_annual_memoir_photos,
)
from app.services.life_event_service import patch_life_event

AS_OF = datetime(2026, 9, 28, 12, tzinfo=UTC)


def _owner(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label, timezone="UTC"))
        db.flush()
        create_legacy_full_entitlement(db, user_id=user_id)
        db.commit()
    return user_id


def _photo(user_id: UUID, occurred_at: datetime) -> tuple[UUID, UUID]:
    memory_id = uuid4()
    source_id = uuid4()
    media_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Memory(
                id=memory_id,
                user_id=user_id,
                memory_type=MemoryType.PHOTO,
                content="private",
                occurred_at=occurred_at,
                source_type=SourceType.USER_PHOTO,
                confidence=1.0,
                is_confirmed=True,
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
                user_id=user_id,
                client_upload_id=uuid4(),
                kind=MediaKind.IMAGE,
                status=MediaStatus.READY,
                upload_object_key=f"staging/{media_id}",
                object_key=f"final/{media_id}",
                content_type="image/jpeg",
                size_bytes=100,
            )
        )
        db.commit()
        db.add(
            MediaEvidenceLink(
                media_id=media_id,
                memory_source_id=source_id,
            )
        )
        db.commit()
    return memory_id, media_id


def _event(user_id: UUID, occurred_at: datetime, title: str) -> UUID:
    event_id = uuid4()
    with SessionLocal() as db:
        db.add(
            LifeEvent(
                id=event_id,
                user_id=user_id,
                event_kind=LifeEventKind.WORK,
                title=title,
                started_at=occurred_at,
            )
        )
        db.commit()
    return event_id


def _empty_summary() -> AnnualSummaryResult:
    return AnnualSummaryResult(
        status=AnnualSummaryStatus.NO_SUMMARIZABLE_EVIDENCE,
        target_year="2025",
        timezone="UTC",
        summary=None,
        citations=(),
        incomplete_code=None,
        provider_error_code=None,
        ai_provenance=None,
    )


async def _fake_summary(db, **kwargs):
    del db, kwargs
    return _empty_summary()


async def _memoir(user_id: UUID):
    with (
        patch(
            "app.services.annual_memoir_service.summarize_year",
            side_effect=_fake_summary,
        ),
        SessionLocal() as db,
    ):
        return await build_annual_memoir(
            db,
            user_id=user_id,
            target_year="2025",
            ai_gateway=object(),
            reference_utc=AS_OF,
        )


async def _owner_isolation_and_current_mutations() -> None:
    owner_a = _owner("memoir-pg-a")
    owner_b = _owner("memoir-pg-b")
    a_memory, a_media = _photo(
        owner_a,
        datetime(2025, 2, 1, tzinfo=UTC),
    )
    b_memory, b_media = _photo(
        owner_b,
        datetime(2025, 2, 2, tzinfo=UTC),
    )
    a_event = _event(
        owner_a,
        datetime(2025, 3, 1, tzinfo=UTC),
        "A event",
    )
    b_event = _event(
        owner_b,
        datetime(2025, 3, 2, tzinfo=UTC),
        "B private event",
    )

    first = await _memoir(owner_a)
    assert {item.media_id for item in first.photo_items} == {a_media}
    assert b_media not in {item.media_id for item in first.photo_items}
    assert b_memory not in {item.memory_id for item in first.photo_items}
    assert {item.life_event_id for item in first.timeline_items} == {a_event}
    assert b_event not in {item.life_event_id for item in first.timeline_items}
    assert "B private event" not in str(first.model_dump())

    with SessionLocal() as db:
        memory = db.get(Memory, a_memory)
        assert memory is not None
        memory.is_deleted = True
        db.commit()
    after_delete = await _memoir(owner_a)
    assert after_delete.photo_items == []

    with SessionLocal() as db:
        memory = db.get(Memory, a_memory)
        media = db.get(MediaAsset, a_media)
        assert memory is not None and media is not None
        memory.is_deleted = False
        media.status = MediaStatus.PENDING
        db.commit()
    after_pending = await _memoir(owner_a)
    assert after_pending.photo_items == []

    with SessionLocal() as db:
        media = db.get(MediaAsset, a_media)
        assert media is not None
        media.status = MediaStatus.READY
        db.commit()
        patch_life_event(
            db,
            user_id=owner_a,
            life_event_id=a_event,
            payload=LifeEventPatch(
                expected_revision=0,
                started_at=datetime(2025, 8, 1, tzinfo=UTC),
            ),
        )
    after_event_patch = await _memoir(owner_a)
    assert after_event_patch.timeline_items[0].occurred_at == datetime(
        2025,
        8,
        1,
        tzinfo=UTC,
    )


def _photo_pagination() -> None:
    owner = _owner("memoir-pg-pagination")
    for index in range(6):
        _photo(
            owner,
            datetime(2025, 5, 1, tzinfo=UTC) + timedelta(days=index),
        )

    with SessionLocal() as db:
        first = list_annual_memoir_photos(
            db,
            user_id=owner,
            target_year="2025",
            limit=3,
            reference_utc=AS_OF,
        )
        assert first.next_cursor is not None
        second = list_annual_memoir_photos(
            db,
            user_id=owner,
            target_year="2025",
            limit=3,
            cursor_value=first.next_cursor,
            reference_utc=AS_OF,
        )

    rows = [(item.memory_id, item.media_id) for item in first.items + second.items]
    assert len(rows) == 6
    assert len(set(rows)) == 6
    assert second.next_cursor is None


async def main() -> None:
    await _owner_isolation_and_current_mutations()
    _photo_pagination()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
