"""Real PostgreSQL projection/pagination gate for V2-009 cross-year life history."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventKind
from app.life_event_schemas import LifeEventPatch
from app.life_history_models import LifeHistoryItemKind
from app.life_stage_models import LifeStage, LifeStageKind
from app.life_stage_schemas import LifeStagePatch
from app.models import User
from app.services.life_event_service import delete_life_event, patch_life_event
from app.services.life_history_service import list_life_history_timeline
from app.services.life_stage_service import delete_life_stage, patch_life_stage

AS_OF = datetime(2026, 9, 28, 12, tzinfo=UTC)


def _seed_user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=label, timezone="UTC"))
        db.commit()
    return user_id


def _event(user_id: UUID, *, event_id: UUID, started_at: datetime, title: str) -> None:
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


def _stage(
    user_id: UUID,
    *,
    stage_id: UUID,
    started_at: datetime,
    ended_at: datetime | None,
    title: str,
) -> None:
    with SessionLocal() as db:
        db.add(
            LifeStage(
                id=stage_id,
                user_id=user_id,
                stage_kind=LifeStageKind.EDUCATION,
                title=title,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        db.commit()


def _page(user_id: UUID, *, limit: int = 100, cursor: str | None = None):
    with SessionLocal() as db:
        return list_life_history_timeline(
            db,
            user_id=user_id,
            start_year=2024,
            end_year=2026,
            limit=limit,
            cursor_value=cursor,
            reference_utc=AS_OF,
        )


def _cleanup(user_id: UUID) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
            db.commit()


def _same_timestamp_order_and_pagination() -> None:
    user_id = _seed_user("life-history-pg-order")
    other_id = _seed_user("life-history-pg-other")
    timestamp = datetime(2025, 6, 1, tzinfo=UTC)
    high_event = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    low_event = UUID("11111111-1111-4111-8111-111111111111")
    stage_id = UUID("88888888-8888-4888-8888-888888888888")
    other_event = uuid4()
    try:
        _event(user_id, event_id=high_event, started_at=timestamp, title="high")
        _event(user_id, event_id=low_event, started_at=timestamp, title="low")
        _stage(
            user_id,
            stage_id=stage_id,
            started_at=timestamp,
            ended_at=timestamp,
            title="stage",
        )
        _event(other_id, event_id=other_event, started_at=timestamp, title="other-private")

        first = _page(user_id, limit=2)
        assert [(item.kind, item.life_event_id) for item in first.items] == [
            (LifeHistoryItemKind.LIFE_EVENT, high_event),
            (LifeHistoryItemKind.LIFE_EVENT, low_event),
        ]
        assert first.next_cursor is not None

        second = _page(user_id, limit=2, cursor=first.next_cursor)
        assert [(item.kind, item.life_stage_id) for item in second.items] == [
            (LifeHistoryItemKind.LIFE_STAGE_ENDED, stage_id),
            (LifeHistoryItemKind.LIFE_STAGE_STARTED, stage_id),
        ]
        assert second.next_cursor is None

        keys = [
            (item.kind, item.life_event_id, item.life_stage_id)
            for item in first.items + second.items
        ]
        assert len(keys) == len(set(keys))
        assert all(item.life_event_id != other_event for item in first.items + second.items)
        assert "other-private" not in str(first.model_dump()) + str(second.model_dump())
    finally:
        _cleanup(user_id)
        _cleanup(other_id)


def _event_patch_delete_updates_current_projection() -> None:
    user_id = _seed_user("life-history-pg-event-current")
    event_id = uuid4()
    try:
        _event(
            user_id,
            event_id=event_id,
            started_at=datetime(2024, 3, 1, tzinfo=UTC),
            title="move-me",
        )
        before = _page(user_id)
        assert before.items[0].occurred_at == datetime(2024, 3, 1, tzinfo=UTC)

        with SessionLocal() as db:
            patch_life_event(
                db,
                user_id=user_id,
                life_event_id=event_id,
                payload=LifeEventPatch(
                    expected_revision=0,
                    started_at=datetime(2025, 4, 1, tzinfo=UTC),
                ),
            )
        after = _page(user_id)
        assert after.items[0].life_event_id == event_id
        assert after.items[0].occurred_at == datetime(2025, 4, 1, tzinfo=UTC)

        with SessionLocal() as db:
            delete_life_event(db, user_id=user_id, life_event_id=event_id)
        deleted = _page(user_id)
        assert all(item.life_event_id != event_id for item in deleted.items)
    finally:
        _cleanup(user_id)


def _stage_end_add_remove_and_delete_updates_projection() -> None:
    user_id = _seed_user("life-history-pg-stage-current")
    stage_id = uuid4()
    try:
        _stage(
            user_id,
            stage_id=stage_id,
            started_at=datetime(2024, 2, 1, tzinfo=UTC),
            ended_at=None,
            title="stage-current",
        )
        initial = _page(user_id)
        assert [item.kind for item in initial.items] == [
            LifeHistoryItemKind.LIFE_STAGE_STARTED
        ]

        with SessionLocal() as db:
            patch_life_stage(
                db,
                user_id=user_id,
                life_stage_id=stage_id,
                payload=LifeStagePatch(
                    expected_revision=0,
                    ended_at=datetime(2025, 2, 1, tzinfo=UTC),
                ),
            )
        ended = _page(user_id)
        assert [item.kind for item in ended.items] == [
            LifeHistoryItemKind.LIFE_STAGE_ENDED,
            LifeHistoryItemKind.LIFE_STAGE_STARTED,
        ]

        with SessionLocal() as db:
            patch_life_stage(
                db,
                user_id=user_id,
                life_stage_id=stage_id,
                payload=LifeStagePatch(
                    expected_revision=1,
                    ended_at=None,
                ),
            )
        reopened = _page(user_id)
        assert [item.kind for item in reopened.items] == [
            LifeHistoryItemKind.LIFE_STAGE_STARTED
        ]

        with SessionLocal() as db:
            delete_life_stage(db, user_id=user_id, life_stage_id=stage_id)
        deleted = _page(user_id)
        assert all(item.life_stage_id != stage_id for item in deleted.items)
    finally:
        _cleanup(user_id)


def main() -> None:
    _same_timestamp_order_and_pagination()
    _event_patch_delete_updates_current_projection()
    _stage_end_add_remove_and_delete_updates_projection()


if __name__ == "__main__":
    main()
