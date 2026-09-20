from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.models import Place, User, Visit


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _freeze_today(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.today_footprint_service.local_today",
        lambda _db, _user_id: date(2026, 9, 20),
    )


async def test_today_footprint_cross_midnight_overlap_owner_and_state(
    client,
    monkeypatch,
):
    headers_a, user_a = await _new_user(client, "today-overlap-a")
    _, user_b = await _new_user(client, "today-overlap-b")
    _freeze_today(monkeypatch)

    cross_finished_id = uuid4()
    cross_open_id = uuid4()
    yesterday_only_id = uuid4()
    today_to_tomorrow_id = uuid4()
    owner_b_cross_id = uuid4()
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
                Place(id=place_a, user_id=user_a, name="家"),
                Place(id=place_b, user_id=user_b, name="B 私密地点"),
            ]
        )
        db.flush()
        db.add_all(
            [
                # 1. 昨天 23:50 -> 今天 00:20：与今天重叠，必须出现。
                Visit(
                    id=cross_finished_id,
                    user_id=user_a,
                    place_id=place_a,
                    arrived_at=datetime(2026, 9, 19, 15, 50, tzinfo=UTC),
                    left_at=datetime(2026, 9, 19, 16, 20, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 19, 16, 30, tzinfo=UTC),
                ),
                # 2. 昨天 22:00 -> open：持续覆盖今天，必须出现且 mutable。
                Visit(
                    id=cross_open_id,
                    user_id=user_a,
                    place_id=place_a,
                    arrived_at=datetime(2026, 9, 19, 14, 0, tzinfo=UTC),
                    left_at=None,
                    finalized_at=None,
                ),
                # 3. 昨天 20:00 -> 23:59：今天开始前已结束，不得出现。
                Visit(
                    id=yesterday_only_id,
                    user_id=user_a,
                    place_id=place_a,
                    arrived_at=datetime(2026, 9, 19, 12, 0, tzinfo=UTC),
                    left_at=datetime(2026, 9, 19, 15, 59, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 19, 15, 59, tzinfo=UTC),
                ),
                # 4. 今天 23:30 -> 明天 00:30：今天内到达，必须出现。
                Visit(
                    id=today_to_tomorrow_id,
                    user_id=user_a,
                    place_id=place_a,
                    arrived_at=datetime(2026, 9, 20, 15, 30, tzinfo=UTC),
                    left_at=datetime(2026, 9, 20, 16, 30, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 20, 16, 40, tzinfo=UTC),
                ),
                # 5. owner B 的跨午夜 Visit 永远不可见给 A。
                Visit(
                    id=owner_b_cross_id,
                    user_id=user_b,
                    place_id=place_b,
                    arrived_at=datetime(2026, 9, 19, 15, 30, tzinfo=UTC),
                    left_at=datetime(2026, 9, 19, 17, 0, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 19, 17, 10, tzinfo=UTC),
                ),
            ]
        )
        db.commit()

    response = await client.get("/v1/today/footprint", headers=headers_a)
    assert response.status_code == 200
    body = response.json()
    by_id = {item["id"]: item for item in body["visits"]}

    assert body["timezone"] == "Asia/Shanghai"
    assert body["day"] == "2026-09-20"
    assert str(cross_finished_id) in by_id
    assert str(cross_open_id) in by_id
    assert str(yesterday_only_id) not in by_id
    assert str(today_to_tomorrow_id) in by_id
    assert str(owner_b_cross_id) not in by_id
    assert "B 私密地点" not in str(body)

    # 产品选择：保留真实 Visit 边界，不把跨午夜到达时间伪裁成今天 00:00。
    assert by_id[str(cross_finished_id)]["arrived_at_local"].startswith(
        "2026-09-19T23:50:00"
    )
    assert by_id[str(cross_finished_id)]["left_at_local"].startswith(
        "2026-09-20T00:20:00"
    )
    assert by_id[str(cross_finished_id)]["visit_finalized"] is True
    assert by_id[str(cross_open_id)]["left_at"] is None
    assert by_id[str(cross_open_id)]["visit_finalized"] is False


async def test_today_footprint_ordering_tie_break_and_current_place_name_unchanged(
    client,
    monkeypatch,
):
    headers, user_id = await _new_user(client, "today-order")
    _freeze_today(monkeypatch)

    place_id = uuid4()
    earlier_cross_id = UUID("90000000-0000-4000-8000-000000000001")
    tie_low = UUID("90000000-0000-4000-8000-000000000002")
    tie_high = UUID("90000000-0000-4000-8000-000000000003")

    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.timezone = "Asia/Shanghai"
        db.add(
            Place(
                id=place_id,
                user_id=user_id,
                name="家",
                automatic_name="住所",
                user_name="家",
                name_revision=2,
            )
        )
        db.flush()
        db.add_all(
            [
                Visit(
                    id=earlier_cross_id,
                    user_id=user_id,
                    place_id=place_id,
                    arrived_at=datetime(2026, 9, 19, 15, 50, tzinfo=UTC),
                    left_at=datetime(2026, 9, 19, 16, 20, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 19, 16, 30, tzinfo=UTC),
                    source="LOCATION_CLUSTER",
                ),
                Visit(
                    id=tie_high,
                    user_id=user_id,
                    place_id=place_id,
                    arrived_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
                ),
                Visit(
                    id=tie_low,
                    user_id=user_id,
                    place_id=place_id,
                    arrived_at=datetime(2026, 9, 20, 8, 0, tzinfo=UTC),
                    left_at=datetime(2026, 9, 20, 8, 30, tzinfo=UTC),
                    finalized_at=datetime(2026, 9, 20, 9, 0, tzinfo=UTC),
                ),
            ]
        )
        db.commit()

    response = await client.get("/v1/today/footprint", headers=headers)
    assert response.status_code == 200
    visits = response.json()["visits"]

    assert [item["id"] for item in visits] == [
        str(earlier_cross_id),
        str(tie_low),
        str(tie_high),
    ]
    assert all(item["place_name"] == "家" for item in visits)
    assert visits[0]["visit_source"] == "LOCATION_CLUSTER"
    assert visits[0]["visit_finalized"] is True
    assert visits[2]["visit_finalized"] is False
