from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Memory, Place, User, Visit


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _seed_timeline_owner(user_id: UUID) -> dict[str, UUID]:
    place_id = uuid4()
    finalized_visit_id = uuid4()
    mutable_visit_id = uuid4()
    memory_id = uuid4()
    deleted_memory_id = uuid4()
    tie_memory_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    tie_visit_id = UUID("11111111-1111-4111-8111-111111111111")

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.timezone = "Asia/Shanghai"
        db.add(
            Place(
                id=place_id,
                user_id=user_id,
                name="家",
                user_name="家",
                is_user_named=True,
                name_revision=1,
            )
        )
        db.add_all(
            [
                Memory(
                    id=memory_id,
                    user_id=user_id,
                    content="十一点的记忆",
                    occurred_at=datetime(2026, 9, 20, 11, 0, tzinfo=UTC),
                    place_id=place_id,
                ),
                Memory(
                    id=tie_memory_id,
                    user_id=user_id,
                    content="十点同刻记忆",
                    occurred_at=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
                ),
                Memory(
                    id=deleted_memory_id,
                    user_id=user_id,
                    content="已删除，不应进入时间轴",
                    occurred_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
                    is_deleted=True,
                ),
                Visit(
                    id=tie_visit_id,
                    user_id=user_id,
                    place_id=place_id,
                    arrived_at=datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
                    left_at=datetime(2026, 9, 20, 10, 30, tzinfo=UTC),
                    duration_seconds=1800,
                    finalized_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
                ),
                Visit(
                    id=mutable_visit_id,
                    user_id=user_id,
                    place_id=place_id,
                    arrived_at=datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
                    left_at=datetime(2026, 9, 20, 9, 15, tzinfo=UTC),
                    duration_seconds=900,
                ),
            ]
        )
        db.commit()

    return {
        "place": place_id,
        "finalized_visit": tie_visit_id,
        "mutable_visit": mutable_visit_id,
        "memory": memory_id,
        "tie_memory": tie_memory_id,
        "deleted_memory": deleted_memory_id,
    }


async def test_timeline_unifies_memory_and_visit_with_stable_cursor(client):
    headers, user_id = await _new_user(client, "timeline-mixed")
    ids = _seed_timeline_owner(user_id)

    first = await client.get("/v1/timeline?limit=2", headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["timezone"] == "Asia/Shanghai"
    assert first_body["day"] is None
    assert [item["kind"] for item in first_body["items"]] == ["MEMORY", "MEMORY"]
    assert first_body["items"][0]["id"] == str(ids["memory"])
    # 同一 timestamp 的固定 tie-break：MEMORY 在 VISIT 前。
    assert first_body["items"][1]["id"] == str(ids["tie_memory"])
    assert first_body["next_cursor"]

    second = await client.get(
        "/v1/timeline",
        headers=headers,
        params={"limit": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert [item["kind"] for item in second_body["items"]] == ["VISIT", "VISIT"]
    assert second_body["items"][0]["id"] == str(ids["finalized_visit"])
    assert second_body["items"][0]["place_name"] == "家"
    assert second_body["items"][0]["visit_finalized"] is True
    assert second_body["items"][1]["id"] == str(ids["mutable_visit"])
    assert second_body["items"][1]["visit_finalized"] is False
    assert second_body["next_cursor"] is None

    all_ids = {
        item["id"]
        for item in first_body["items"] + second_body["items"]
    }
    assert str(ids["deleted_memory"]) not in all_ids
    assert len(all_ids) == 4


async def test_timeline_day_uses_user_timezone_boundaries_and_owner_isolation(client):
    headers_a, user_a = await _new_user(client, "timeline-day-a")
    _, user_b = await _new_user(client, "timeline-day-b")
    place_a = uuid4()
    place_b = uuid4()

    with SessionLocal() as db:
        a = db.get(User, user_a)
        b = db.get(User, user_b)
        assert a is not None and b is not None
        a.timezone = "Asia/Shanghai"
        b.timezone = "Asia/Shanghai"
        db.add_all(
            [
                Place(id=place_a, user_id=user_a, name="A 地点"),
                Place(id=place_b, user_id=user_b, name="B 私密地点"),
            ]
        )
        db.flush()
        db.add_all(
            [
                # 2026-09-20 Asia/Shanghai = [09-19 16:00Z, 09-20 16:00Z).
                Memory(
                    user_id=user_a,
                    content="前一天最后一分钟",
                    occurred_at=datetime(2026, 9, 19, 15, 59, tzinfo=UTC),
                ),
                Visit(
                    user_id=user_a,
                    place_id=place_a,
                    arrived_at=datetime(2026, 9, 19, 16, 0, tzinfo=UTC),
                ),
                Memory(
                    user_id=user_a,
                    content="当天最后一分钟",
                    occurred_at=datetime(2026, 9, 20, 15, 59, tzinfo=UTC),
                ),
                Visit(
                    user_id=user_a,
                    place_id=place_a,
                    arrived_at=datetime(2026, 9, 20, 16, 0, tzinfo=UTC),
                ),
                Memory(
                    user_id=user_b,
                    content="B 私密记忆",
                    occurred_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
                ),
                Visit(
                    user_id=user_b,
                    place_id=place_b,
                    arrived_at=datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
                ),
            ]
        )
        db.commit()

    response = await client.get(
        "/v1/timeline",
        headers=headers_a,
        params={"day": "2026-09-20", "limit": 20},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Asia/Shanghai"
    assert body["day"] == "2026-09-20"
    assert len(body["items"]) == 2
    assert {item["kind"] for item in body["items"]} == {"MEMORY", "VISIT"}
    encoded = str(body)
    assert "前一天最后一分钟" not in encoded
    assert "B 私密记忆" not in encoded
    assert "B 私密地点" not in encoded


async def test_timeline_rejects_invalid_cursor(client):
    headers, _ = await _new_user(client, "timeline-bad-cursor")
    response = await client.get(
        "/v1/timeline",
        headers=headers,
        params={"cursor": "not-a-valid-cursor"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "TIMELINE_CURSOR_INVALID"
