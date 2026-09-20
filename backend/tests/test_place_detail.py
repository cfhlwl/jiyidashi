from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.models import Place, Visit


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


async def test_place_detail_is_owner_scoped_and_pages_retained_visits(client):
    headers_a, user_a = await _new_user(client, "place-detail-a")
    headers_b, user_b = await _new_user(client, "place-detail-b")
    place_a = uuid4()
    place_b = uuid4()
    high = UUID("eeeeeeee-2222-4222-8222-eeeeeeeeeeee")
    low = UUID("cccccccc-2222-4222-8222-cccccccccccc")
    older = uuid4()
    tie = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)

    with SessionLocal() as db:
        db.add_all([
            Place(id=place_a,user_id=user_a,name="家",user_name="家",is_user_named=True,name_revision=2,visit_count=3,first_visited_at=datetime(2026,9,18,tzinfo=UTC),last_visited_at=tie),
            Place(id=place_b,user_id=user_b,name="B 私密地点",visit_count=0),
        ])
        db.flush()
        db.add_all([
            Visit(id=high,user_id=user_a,place_id=place_a,arrived_at=tie,finalized_at=tie,source="GPS",confidence=0.9),
            Visit(id=low,user_id=user_a,place_id=place_a,arrived_at=tie,source="GPS",confidence=0.8),
            Visit(id=older,user_id=user_a,place_id=place_a,arrived_at=datetime(2026,9,19,8,0,tzinfo=UTC),source="GPS",confidence=0.7),
        ])
        db.commit()

    first = await client.get(f"/v1/location/places/{place_a}",headers=headers_a,params={"limit":2})
    assert first.status_code == 200
    body=first.json()
    assert body["place"]["name"]=="家"
    assert body["place"]["name_source"]=="USER"
    assert [item["id"] for item in body["visits"]]==[str(high),str(low)]
    assert body["visits"][0]["visit_finalized"] is True
    assert body["visits"][1]["visit_finalized"] is False
    assert body["next_cursor"]

    second = await client.get(
        f"/v1/location/places/{place_a}",
        headers=headers_a,
        params={"limit": 2, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert [item["id"] for item in second_body["visits"]] == [str(older)]
    assert second_body["next_cursor"] is None

    foreign=await client.get(f"/v1/location/places/{place_a}",headers=headers_b)
    assert foreign.status_code==404
    assert foreign.json()["detail"]=="PLACE_NOT_FOUND"

    unknown=await client.get(f"/v1/location/places/{uuid4()}",headers=headers_a)
    assert unknown.status_code==404
    assert unknown.json()["detail"]=="PLACE_NOT_FOUND"


async def test_place_detail_empty_and_malformed_cursor(client):
    headers,user_id=await _new_user(client,"place-detail-empty")
    place_id=uuid4()
    with SessionLocal() as db:
        db.add(Place(id=place_id,user_id=user_id,name="未命名地点"))
        db.commit()

    empty=await client.get(f"/v1/location/places/{place_id}",headers=headers)
    assert empty.status_code==200
    assert empty.json()["visits"]==[]
    assert empty.json()["next_cursor"] is None

    for cursor in ("not-a-cursor", "W10", "bnVsbA", "MQ"):
        response = await client.get(
            f"/v1/location/places/{place_id}",
            headers=headers,
            params={"cursor": cursor},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "PLACE_DETAIL_CURSOR_INVALID"
