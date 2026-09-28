from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.db import SessionLocal
from app.life_event_models import LifeEvent, LifeEventKind
from app.life_history_models import LifeHistoryItemKind
from app.life_stage_models import LifeStage, LifeStageKind
from app.models import User
from app.services.life_history_service import (
    LifeHistoryError,
    list_life_history_timeline,
)


REFERENCE = datetime(2026, 9, 28, 12, tzinfo=UTC)


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _set_timezone(user_id: UUID, timezone_name: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.timezone = timezone_name
        db.commit()


def _add_event(
    user_id: UUID,
    *,
    started_at: datetime,
    ended_at: datetime | None = None,
    event_id: UUID | None = None,
    title: str = "Event",
) -> UUID:
    event_id = event_id or uuid4()
    with SessionLocal() as db:
        db.add(
            LifeEvent(
                id=event_id,
                user_id=user_id,
                event_kind=LifeEventKind.WORK,
                title=title,
                started_at=started_at,
                ended_at=ended_at,
            )
        )
        db.commit()
    return event_id


def _add_stage(
    user_id: UUID,
    *,
    started_at: datetime,
    ended_at: datetime | None = None,
    stage_id: UUID | None = None,
    title: str = "Stage",
) -> UUID:
    stage_id = stage_id or uuid4()
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
    return stage_id


def _read(
    user_id: UUID,
    *,
    start_year: int,
    end_year: int,
    limit: int = 50,
    cursor: str | None = None,
    reference: datetime = REFERENCE,
):
    with SessionLocal() as db:
        return list_life_history_timeline(
            db,
            user_id=user_id,
            start_year=start_year,
            end_year=end_year,
            limit=limit,
            cursor_value=cursor,
            reference_utc=reference,
        )


def _opaque(payload) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


async def test_exact_kinds_projection_and_explicit_boundary_semantics(client):
    _, user_id = await _new_user(client, "life-history-contract")
    _set_timezone(user_id, "UTC")
    event_id = _add_event(
        user_id,
        started_at=datetime(2024, 6, 10, tzinfo=UTC),
        ended_at=datetime(2024, 6, 12, tzinfo=UTC),
        title="Explicit event",
    )
    ended_stage_id = _add_stage(
        user_id,
        started_at=datetime(2023, 9, 1, tzinfo=UTC),
        ended_at=datetime(2025, 6, 30, tzinfo=UTC),
        title="Explicit stage",
    )
    open_stage_id = _add_stage(
        user_id,
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        ended_at=None,
        title="Open stage",
    )

    result = _read(user_id, start_year=2024, end_year=2025)
    assert [item.kind for item in result.items] == [
        LifeHistoryItemKind.LIFE_STAGE_ENDED,
        LifeHistoryItemKind.LIFE_STAGE_STARTED,
        LifeHistoryItemKind.LIFE_EVENT,
    ]

    ended = result.items[0]
    assert ended.life_stage_id == ended_stage_id
    assert ended.life_event_id is None
    assert ended.event_kind is None
    assert ended.event_ended_at is None
    assert ended.place_id is None

    opened = result.items[1]
    assert opened.life_stage_id == open_stage_id
    assert opened.kind == LifeHistoryItemKind.LIFE_STAGE_STARTED

    event = result.items[2]
    assert event.life_event_id == event_id
    assert event.event_ended_at == datetime(2024, 6, 12, tzinfo=UTC)
    assert event.life_stage_id is None
    assert event.stage_kind is None

    assert {item.kind.value for item in result.items} == {
        "LIFE_EVENT",
        "LIFE_STAGE_STARTED",
        "LIFE_STAGE_ENDED",
    }
    payload = result.model_dump(mode="json")
    assert set(payload) == {
        "timezone",
        "start_year",
        "end_year",
        "as_of",
        "items",
        "next_cursor",
    }
    assert set(payload["items"][0]) == {
        "kind",
        "occurred_at",
        "title",
        "custom_label",
        "life_event_id",
        "event_kind",
        "event_ended_at",
        "place_id",
        "life_stage_id",
        "stage_kind",
    }


async def test_event_membership_is_started_at_only_and_stage_boundaries_are_independent(client):
    _, user_id = await _new_user(client, "life-history-boundaries")
    _set_timezone(user_id, "UTC")
    before_event = _add_event(
        user_id,
        started_at=datetime(2023, 12, 31, tzinfo=UTC),
        ended_at=datetime(2024, 1, 3, tzinfo=UTC),
        title="Started before range",
    )
    stage_end_only = _add_stage(
        user_id,
        started_at=datetime(2023, 1, 1, tzinfo=UTC),
        ended_at=datetime(2024, 3, 1, tzinfo=UTC),
        title="End only",
    )
    stage_start_only = _add_stage(
        user_id,
        started_at=datetime(2024, 8, 1, tzinfo=UTC),
        ended_at=datetime(2025, 1, 1, tzinfo=UTC),
        title="Start only",
    )
    open_stage = _add_stage(
        user_id,
        started_at=datetime(2024, 9, 1, tzinfo=UTC),
        ended_at=None,
        title="No inferred end",
    )

    result = _read(user_id, start_year=2024, end_year=2024)
    ids = {(item.kind, item.life_event_id, item.life_stage_id) for item in result.items}
    assert all(event_id != before_event for _, event_id, _ in ids)
    assert (
        LifeHistoryItemKind.LIFE_STAGE_ENDED,
        None,
        stage_end_only,
    ) in ids
    assert (
        LifeHistoryItemKind.LIFE_STAGE_STARTED,
        None,
        stage_start_only,
    ) in ids
    assert (
        LifeHistoryItemKind.LIFE_STAGE_STARTED,
        None,
        open_stage,
    ) in ids
    assert (
        LifeHistoryItemKind.LIFE_STAGE_ENDED,
        None,
        open_stage,
    ) not in ids
    assert sum(item.life_stage_id == stage_end_only for item in result.items) == 1
    assert sum(item.life_stage_id == stage_start_only for item in result.items) == 1


async def test_global_same_timestamp_kind_rank_uuid_order_and_cursor(client):
    _, user_id = await _new_user(client, "life-history-order")
    _set_timezone(user_id, "UTC")
    timestamp = datetime(2025, 5, 5, tzinfo=UTC)
    low_event = UUID("11111111-1111-4111-8111-111111111111")
    high_event = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    stage_id = UUID("88888888-8888-4888-8888-888888888888")

    _add_event(user_id, started_at=timestamp, event_id=low_event, title="low")
    _add_event(user_id, started_at=timestamp, event_id=high_event, title="high")
    _add_stage(
        user_id,
        started_at=timestamp,
        ended_at=timestamp,
        stage_id=stage_id,
        title="same-stage",
    )

    first = _read(user_id, start_year=2025, end_year=2025, limit=2)
    assert [(item.kind, item.life_event_id) for item in first.items] == [
        (LifeHistoryItemKind.LIFE_EVENT, high_event),
        (LifeHistoryItemKind.LIFE_EVENT, low_event),
    ]
    assert first.next_cursor is not None

    second = _read(
        user_id,
        start_year=2025,
        end_year=2025,
        limit=2,
        cursor=first.next_cursor,
    )
    assert [(item.kind, item.life_stage_id) for item in second.items] == [
        (LifeHistoryItemKind.LIFE_STAGE_ENDED, stage_id),
        (LifeHistoryItemKind.LIFE_STAGE_STARTED, stage_id),
    ]
    assert second.next_cursor is None

    all_keys = [
        (item.kind.value, item.life_event_id, item.life_stage_id)
        for item in first.items + second.items
    ]
    assert len(all_keys) == len(set(all_keys))

    full = _read(user_id, start_year=2025, end_year=2025, limit=100)
    assert len(full.items) == 4
    one = _read(user_id, start_year=2025, end_year=2025, limit=1)
    assert len(one.items) == 1
    assert one.next_cursor is not None


async def test_owner_isolation_and_api_contract(client):
    headers_a, user_a = await _new_user(client, "life-history-owner-a")
    _, user_b = await _new_user(client, "life-history-owner-b")
    _set_timezone(user_a, "UTC")
    _set_timezone(user_b, "UTC")
    own_id = _add_event(
        user_a,
        started_at=datetime(2025, 1, 1, tzinfo=UTC),
        title="own",
    )
    other_id = _add_event(
        user_b,
        started_at=datetime(2025, 2, 1, tzinfo=UTC),
        title="private-other",
    )

    response = await client.get(
        "/v1/life-history/timeline",
        headers=headers_a,
        params={"start_year": 2025, "end_year": 2025, "limit": 100},
    )
    assert response.status_code == 200
    body = response.json()
    ids = {item["life_event_id"] for item in body["items"]}
    assert str(own_id) in ids
    assert str(other_id) not in ids
    assert "private-other" not in str(body)


async def test_user_local_year_boundaries_utc_non_utc_and_dst_zone(client):
    _, utc_user = await _new_user(client, "life-history-utc-boundary")
    _set_timezone(utc_user, "UTC")
    before = _add_event(
        utc_user,
        started_at=datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC),
    )
    at = _add_event(
        utc_user,
        started_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    utc_items = _read(utc_user, start_year=2024, end_year=2024).items
    assert {item.life_event_id for item in utc_items} == {at}
    assert before not in {item.life_event_id for item in utc_items}

    _, sh_user = await _new_user(client, "life-history-shanghai-boundary")
    _set_timezone(sh_user, "Asia/Shanghai")
    sh_before = _add_event(
        sh_user,
        started_at=datetime(2023, 12, 31, 15, 59, 59, tzinfo=UTC),
    )
    sh_at = _add_event(
        sh_user,
        started_at=datetime(2023, 12, 31, 16, 0, tzinfo=UTC),
    )
    sh_items = _read(sh_user, start_year=2024, end_year=2024).items
    assert {item.life_event_id for item in sh_items} == {sh_at}
    assert sh_before not in {item.life_event_id for item in sh_items}

    _, la_user = await _new_user(client, "life-history-la-boundary")
    _set_timezone(la_user, "America/Los_Angeles")
    la_before = _add_event(
        la_user,
        started_at=datetime(2024, 1, 1, 7, 59, 59, tzinfo=UTC),
    )
    la_at = _add_event(
        la_user,
        started_at=datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
    )
    la_items = _read(la_user, start_year=2024, end_year=2024).items
    assert {item.life_event_id for item in la_items} == {la_at}
    assert la_before not in {item.life_event_id for item in la_items}


async def test_invalid_legacy_timezone_falls_back_to_utc(client):
    _, user_id = await _new_user(client, "life-history-invalid-timezone")
    _set_timezone(user_id, "Legacy/Invalid-Zone")
    event_id = _add_event(
        user_id,
        started_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    result = _read(user_id, start_year=2024, end_year=2024)
    assert result.timezone == "UTC"
    assert [item.life_event_id for item in result.items] == [event_id]


async def test_current_year_future_fact_is_excluded_by_server_as_of(client):
    _, user_id = await _new_user(client, "life-history-as-of")
    _set_timezone(user_id, "UTC")
    past = _add_event(
        user_id,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        title="past",
    )
    future = _add_event(
        user_id,
        started_at=datetime(2026, 12, 1, tzinfo=UTC),
        title="future",
    )
    result = _read(user_id, start_year=2026, end_year=2026)
    assert {item.life_event_id for item in result.items} == {past}
    assert future not in {item.life_event_id for item in result.items}
    assert result.as_of == REFERENCE


async def test_year_validation_and_cursor_validation(client):
    _, user_id = await _new_user(client, "life-history-validation")
    _set_timezone(user_id, "UTC")

    cases = [
        ((2025, 2024), "LIFE_HISTORY_YEAR_RANGE_INVALID"),
        ((2015, 2025), "LIFE_HISTORY_YEAR_SPAN_TOO_LARGE"),
        ((2026, 2027), "LIFE_HISTORY_FUTURE_YEAR_NOT_ALLOWED"),
    ]
    for (start_year, end_year), code in cases:
        with pytest.raises(LifeHistoryError) as exc:
            _read(user_id, start_year=start_year, end_year=end_year)
        assert exc.value.code == code

    cursor_cases = [
        "not-a-cursor",
        _opaque({"v": 2, "t": REFERENCE.isoformat(), "k": "LIFE_EVENT", "id": str(uuid4())}),
        _opaque({"v": 1, "t": REFERENCE.isoformat(), "k": "UNKNOWN", "id": str(uuid4())}),
        _opaque({"v": 1, "t": "2025-01-01T00:00:00", "k": "LIFE_EVENT", "id": str(uuid4())}),
        _opaque({"v": 1, "t": REFERENCE.isoformat(), "k": "LIFE_EVENT", "id": "bad-uuid"}),
    ]
    for cursor in cursor_cases:
        with pytest.raises(LifeHistoryError) as exc:
            _read(user_id, start_year=2025, end_year=2025, cursor=cursor)
        assert exc.value.code == "LIFE_HISTORY_CURSOR_INVALID"


async def test_api_query_validation(client):
    headers, _ = await _new_user(client, "life-history-api-validation")
    for params in (
        {"start_year": 0, "end_year": 2025},
        {"start_year": 2025, "end_year": 9999},
        {"start_year": 2025, "end_year": 2025, "limit": 0},
        {"start_year": 2025, "end_year": 2025, "limit": 101},
    ):
        response = await client.get(
            "/v1/life-history/timeline",
            headers=headers,
            params=params,
        )
        assert response.status_code == 422

    future = await client.get(
        "/v1/life-history/timeline",
        headers=headers,
        params={"start_year": 2027, "end_year": 2027},
    )
    assert future.status_code == 422
    assert future.json()["detail"] == "LIFE_HISTORY_FUTURE_YEAR_NOT_ALLOWED"


def test_scope_lock_no_memory_visit_summary_ai_graph_or_persistence():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app/services/life_history_service.py").read_text()
    for forbidden in [
        "Memory",
        "Visit",
        "LocationPoint",
        "Summary",
        "AIGateway",
        "EmbeddingGateway",
        "answer_from_memory_rag",
        "retrieve_memories",
        "long_term_reasoning_service",
        "PersonRelationship",
        "Family",
        "LifeEventMemoryLink",
        "LifeStageEventLink",
        ".add(",
        ".commit(",
        ".delete(",
    ]:
        assert forbidden not in source

    assert "LifeEvent.started_at" in source
    assert "LifeStage.started_at" in source
    assert "LifeStage.ended_at" in source
    assert list((root / "migrations/versions").glob("0025*")) == []
