from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.models import Place, User, Visit
from app.services.date_query_parser import (
    DateParseStatus,
    parse_date_expression,
)
from app.services.time_service import user_day_bounds_utc


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


def _freeze_local_day(monkeypatch, day: date) -> None:
    monkeypatch.setattr(
        "app.services.date_query_parser.local_today",
        lambda _db, _user_id, _reference=None: day,
    )
    monkeypatch.setattr(
        "app.api.day_footprint.local_today",
        lambda _db, _user_id: day,
    )


def test_core002_date_parser_matrix():
    today = date(2026, 10, 1)

    assert parse_date_expression("今天去哪了", today=today).day == date(2026, 10, 1)
    assert parse_date_expression("昨天去了哪里", today=today).day == date(2026, 9, 30)
    assert parse_date_expression("前天发生了什么", today=today).day == date(2026, 9, 29)
    assert parse_date_expression("2026-09-25 的足迹", today=today).day == date(2026, 9, 25)
    assert parse_date_expression("2026年9月25日去哪了", today=today).day == date(2026, 9, 25)
    assert parse_date_expression("9月25日去了哪里", today=today).day == date(2026, 9, 25)
    assert parse_date_expression("我25号去哪了", today=today).day == date(2026, 9, 25)
    assert parse_date_expression(
        "我25号去哪了",
        today=date(2026, 10, 28),
    ).day == date(2026, 10, 25)

    assert parse_date_expression(
        "12月31日发生了什么",
        today=date(2026, 1, 3),
    ).day == date(2025, 12, 31)
    assert parse_date_expression(
        "2月29日发生了什么",
        today=date(2026, 3, 1),
    ).day == date(2024, 2, 29)

    assert parse_date_expression(
        "上周一去哪了",
        today=date(2026, 10, 1),
    ).day == date(2026, 9, 21)
    assert parse_date_expression(
        "本周一去哪了",
        today=date(2026, 10, 1),
    ).day == date(2026, 9, 28)
    this_sunday = parse_date_expression(
        "本周日去哪了",
        today=date(2026, 10, 1),
    )
    assert this_sunday.status == DateParseStatus.FUTURE
    assert this_sunday.day == date(2026, 10, 4)

    invalid = parse_date_expression("2026-02-30去哪了", today=today)
    assert invalid.status == DateParseStatus.INVALID
    future = parse_date_expression("2026-10-02去哪了", today=today)
    assert future.status == DateParseStatus.FUTURE
    assert parse_date_expression("哪天去过公司", today=today).status == DateParseStatus.NO_MATCH


async def test_core002_day_footprint_overlap_owner_order_and_typed_endpoint(
    client,
    monkeypatch,
):
    headers_a, user_a = await _new_user(client, "core002-day-a")
    _, user_b = await _new_user(client, "core002-day-b")
    _set_timezone(user_a, "Asia/Shanghai")
    _set_timezone(user_b, "Asia/Shanghai")
    _freeze_local_day(monkeypatch, date(2026, 10, 1))

    home = uuid4()
    office = uuid4()
    foreign = uuid4()
    cross_id = uuid4()
    office_id = uuid4()
    next_day_id = uuid4()

    with SessionLocal() as db:
        db.add_all(
            [
                Place(
                    id=home,
                    user_id=user_a,
                    name="家",
                    latitude=31.2304,
                    longitude=121.4737,
                    address="家庭地址",
                    category="HOME",
                ),
                Place(
                    id=office,
                    user_id=user_a,
                    name="公司",
                    latitude=31.2200,
                    longitude=121.4800,
                    address="办公地址",
                    category="WORK",
                ),
                Place(id=foreign, user_id=user_b, name="B 私密地点"),
            ]
        )
        db.flush()
        db.add_all(
            [
                # Local 9/24 23:30 -> 9/25 01:15: must overlap requested day.
                Visit(
                    id=cross_id,
                    user_id=user_a,
                    place_id=home,
                    arrived_at=datetime(2026, 9, 24, 15, 30, tzinfo=UTC),
                    left_at=datetime(2026, 9, 24, 17, 15, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 24, 17, 20, tzinfo=UTC),
                ),
                # Local 9/25 11:00 -> 12:00.
                Visit(
                    id=office_id,
                    user_id=user_a,
                    place_id=office,
                    arrived_at=datetime(2026, 9, 25, 3, 0, tzinfo=UTC),
                    left_at=datetime(2026, 9, 25, 4, 0, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 25, 4, 5, tzinfo=UTC),
                ),
                # Local 9/26 only: must not appear.
                Visit(
                    id=next_day_id,
                    user_id=user_a,
                    place_id=office,
                    arrived_at=datetime(2026, 9, 26, 3, 0, tzinfo=UTC),
                    left_at=datetime(2026, 9, 26, 4, 0, tzinfo=UTC),
                ),
                Visit(
                    user_id=user_b,
                    place_id=foreign,
                    arrived_at=datetime(2026, 9, 25, 1, 0, tzinfo=UTC),
                    left_at=datetime(2026, 9, 25, 2, 0, tzinfo=UTC),
                ),
            ]
        )
        db.commit()

    response = await client.get(
        "/v1/footprint/day?date=2026-09-25",
        headers=headers_a,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["day"] == "2026-09-25"
    assert body["timezone"] == "Asia/Shanghai"
    assert body["empty"] is False
    assert [item["id"] for item in body["visits"]] == [
        str(cross_id),
        str(office_id),
    ]
    assert body["visits"][0]["arrived_at_local"].startswith("2026-09-24T23:30:00")
    assert body["visits"][0]["left_at_local"].startswith("2026-09-25T01:15:00")
    assert body["visits"][1]["place_name"] == "公司"
    assert body["visits"][1]["place_category"] == "WORK"
    assert "B 私密地点" not in str(body)
    assert str(next_day_id) not in str(body)

    future = await client.get(
        "/v1/footprint/day?date=2026-10-02",
        headers=headers_a,
    )
    assert future.status_code == 422
    assert future.json()["detail"] == "FUTURE_FOOTPRINT_DATE"

    invalid = await client.get(
        "/v1/footprint/day?date=2026-02-30",
        headers=headers_a,
    )
    assert invalid.status_code == 422


async def test_core002_user_day_bounds_cover_dst_23_and_25_hours(client):
    _, user_id = await _new_user(client, "core002-dst")
    _set_timezone(user_id, "America/New_York")

    with SessionLocal() as db:
        spring_start, spring_end = user_day_bounds_utc(
            db,
            user_id,
            date(2026, 3, 8),
        )
        fall_start, fall_end = user_day_bounds_utc(
            db,
            user_id,
            date(2026, 11, 1),
        )

    assert spring_end - spring_start == timedelta(hours=23)
    assert fall_end - fall_start == timedelta(hours=25)


async def test_core002_date_footprint_query_uses_visit_authority_and_zero_ai(
    client,
    monkeypatch,
):
    headers, user_id = await _new_user(client, "core002-query")
    _set_timezone(user_id, "Asia/Shanghai")
    _freeze_local_day(monkeypatch, date(2026, 10, 1))

    provider_calls = 0

    def forbidden_gateway():
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("DATE_FOOTPRINT_QUERY must not call an AI provider")

    monkeypatch.setattr("app.services.ai_gateway.get_ai_gateway", forbidden_gateway)

    place_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Place(
                id=place_id,
                user_id=user_id,
                name="万达广场",
                category="SHOPPING",
            )
        )
        db.flush()
        db.add(
            Visit(
                user_id=user_id,
                place_id=place_id,
                arrived_at=datetime(2026, 9, 25, 10, 16, tzinfo=UTC),
                left_at=datetime(2026, 9, 25, 11, 5, tzinfo=UTC),
                finalized_at=datetime(2026, 9, 25, 11, 10, tzinfo=UTC),
            )
        )
        db.commit()

    # Deliberately conflicting text must never become whereabouts authority.
    memory = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "content": "我25号去了月球",
            "occurred_at": "2026-09-24T12:00:00Z",
        },
    )
    assert memory.status_code == 201

    routed = await client.post(
        "/v1/intent/route",
        headers=headers,
        json={"question": "我25号去哪了？"},
    )
    assert routed.status_code == 200
    assert routed.json() == {
        "intent": "DATE_FOOTPRINT_QUERY",
        "capability": "DATE_FOOTPRINT_QUERY",
        "reason": "MATCHED",
    }

    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "我25号去哪了？"},
    )
    assert query.status_code == 200
    body = query.json()
    assert body["intent"] == "DATE_FOOTPRINT_QUERY"
    assert body["can_answer"] is True
    assert body["day_footprint"]["day"] == "2026-09-25"
    assert [item["place_name"] for item in body["day_footprint"]["visits"]] == [
        "万达广场"
    ]
    assert "万达广场" in body["answer"]
    assert "月球" not in body["answer"]
    assert body["memory_ids"] == []
    assert provider_calls == 0


async def test_core002_broad_day_query_is_evidence_first_and_provider_optional(
    client,
    monkeypatch,
):
    headers, user_id = await _new_user(client, "core002-events")
    _set_timezone(user_id, "Asia/Shanghai")
    _freeze_local_day(monkeypatch, date(2026, 10, 1))

    provider_calls = 0

    def unavailable_gateway():
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("provider is optional for deterministic day evidence")

    monkeypatch.setattr("app.services.ai_gateway.get_ai_gateway", unavailable_gateway)

    created = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "content": "中午和老张确认了合同终稿",
            "occurred_at": "2026-09-25T04:10:00Z",
        },
    )
    assert created.status_code == 201

    query = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "25号发生了什么？"},
    )
    assert query.status_code == 200
    body = query.json()
    assert body["intent"] == "FIND_EVENT"
    assert body["can_answer"] is True
    assert "中午和老张确认了合同终稿" in body["answer"]
    assert body["memory_ids"] == [created.json()["id"]]
    assert len(body["evidence"]) == 1
    assert provider_calls == 0

    empty = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "23号发生了什么？"},
    )
    assert empty.status_code == 200
    empty_body = empty.json()
    assert empty_body["can_answer"] is False
    assert empty_body["reason"] == "NO_EVIDENCE"
    assert "没有找到可靠" in empty_body["answer"]
    assert provider_calls == 0


async def test_core002_invalid_and_future_date_queries_fail_closed(
    client,
    monkeypatch,
):
    headers, _ = await _new_user(client, "core002-invalid")
    _freeze_local_day(monkeypatch, date(2026, 10, 1))

    invalid = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "2026-02-30我去哪了？"},
    )
    assert invalid.status_code == 200
    assert invalid.json()["can_answer"] is False
    assert invalid.json()["reason"] == "INVALID_DATE"

    future = await client.post(
        "/v1/memory/query",
        headers=headers,
        json={"question": "2026-10-02我去哪了？"},
    )
    assert future.status_code == 200
    assert future.json()["can_answer"] is False
    assert future.json()["reason"] == "FUTURE_DATE"
