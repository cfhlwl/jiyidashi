from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.idempotency_models import ClientMutation
from app.models import Place, PlaceNameCorrection, User, Visit
from app.services.place_naming_service import (
    PLACE_NAME_CORRECTION_OPERATION,
    PlaceNamingError,
    apply_automatic_place_label_candidate,
)


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _visit_points(prefix: str) -> list[dict]:
    started = datetime.now(UTC) - timedelta(minutes=20)
    return [
        {
            "client_uuid": f"{prefix}-{index}",
            "latitude": 31.23040 + index * 0.00003,
            "longitude": 121.47370 + index * 0.00003,
            "recorded_at": (started + timedelta(minutes=index * 5)).isoformat(),
        }
        for index in range(3)
    ]


async def _derive_place(client, headers: dict[str, str], prefix: str) -> tuple[UUID, dict]:
    response = await client.post(
        "/v1/location/batch",
        headers=headers,
        json={"points": _visit_points(prefix)},
    )
    assert response.status_code == 200
    places = (await client.get("/v1/location/places", headers=headers)).json()
    assert len(places) == 1
    return UUID(places[0]["id"]), places[0]


@pytest.mark.asyncio
async def test_place_user_correction_wins_over_automatic_and_clear_falls_back(client):
    headers, user_id = await _new_user(client, "place-precedence")
    place_id, initial = await _derive_place(client, headers, "precedence")
    assert initial["name"] == "未命名地点"
    assert initial["name_source"] == "UNNAMED"
    assert initial["name_revision"] == 0

    before_visit = (await client.get("/v1/location/visits", headers=headers)).json()[0]

    with SessionLocal() as db:
        place = apply_automatic_place_label_candidate(
            db,
            user_id=user_id,
            place_id=place_id,
            label="附近咖啡店",
            source="POI_TEST",
        )
        assert place.name == "附近咖啡店"
        db.commit()

    automatic = (await client.get("/v1/location/places", headers=headers)).json()[0]
    assert automatic["name"] == "附近咖啡店"
    assert automatic["automatic_name"] == "附近咖啡店"
    assert automatic["automatic_name_source"] == "POI_TEST"
    assert automatic["user_name"] is None
    assert automatic["name_source"] == "AUTOMATIC"
    assert automatic["name_revision"] == 1

    first_uuid = uuid4()
    corrected = await client.put(
        f"/v1/location/places/{place_id}/name",
        headers=headers,
        json={"client_uuid": str(first_uuid), "name": "家"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["name"] == "家"
    assert corrected.json()["user_name"] == "家"
    assert corrected.json()["name_source"] == "USER"
    assert corrected.json()["name_revision"] == 2

    with SessionLocal() as db:
        place = apply_automatic_place_label_candidate(
            db,
            user_id=user_id,
            place_id=place_id,
            label="新的自动候选",
            source="ADDRESS_TEST",
        )
        # [人工注释][S2-009][S2-010] automatic candidate 可以更新，但显示层不能覆盖用户纠正。
        assert place.automatic_name == "新的自动候选"
        assert place.name == "家"
        db.commit()

    after_candidate = (await client.get("/v1/location/places", headers=headers)).json()[0]
    assert after_candidate["name"] == "家"
    assert after_candidate["automatic_name"] == "新的自动候选"
    assert after_candidate["name_source"] == "USER"
    assert after_candidate["name_revision"] == 3

    cleared = await client.put(
        f"/v1/location/places/{place_id}/name",
        headers=headers,
        json={"client_uuid": str(uuid4()), "name": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["name"] == "新的自动候选"
    assert cleared.json()["user_name"] is None
    assert cleared.json()["name_source"] == "AUTOMATIC"
    assert cleared.json()["name_revision"] == 4

    after_visit = (await client.get("/v1/location/visits", headers=headers)).json()[0]
    assert after_visit["id"] == before_visit["id"]
    assert after_visit["place_id"] == before_visit["place_id"]
    assert after_visit["source_fingerprint"] == before_visit["source_fingerprint"]
    assert after_visit["derivation_key"] if "derivation_key" in after_visit else True

    with SessionLocal() as db:
        corrections = list(
            db.scalars(
                select(PlaceNameCorrection)
                .where(PlaceNameCorrection.user_id == user_id)
                .order_by(PlaceNameCorrection.revision)
            )
        )
        assert [(row.previous_user_name, row.new_user_name) for row in corrections] == [
            (None, "家"),
            ("家", None),
        ]
        assert [row.revision for row in corrections] == [2, 4]


@pytest.mark.asyncio
async def test_place_correction_is_owner_scoped_idempotent_and_conflict_safe(client):
    headers_a, user_a = await _new_user(client, "place-owner-a")
    headers_b, _ = await _new_user(client, "place-owner-b")
    place_id, _ = await _derive_place(client, headers_a, "owner-a")
    client_uuid = uuid4()

    foreign = await client.put(
        f"/v1/location/places/{place_id}/name",
        headers=headers_b,
        json={"client_uuid": str(uuid4()), "name": "不应成功"},
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "PLACE_NOT_FOUND"

    first = await client.put(
        f"/v1/location/places/{place_id}/name",
        headers=headers_a,
        json={"client_uuid": str(client_uuid), "name": "  家  "},
    )
    assert first.status_code == 200
    assert first.json()["name"] == "家"
    assert first.json()["name_revision"] == 1

    replay = await client.put(
        f"/v1/location/places/{place_id}/name",
        headers=headers_a,
        json={"client_uuid": str(client_uuid), "name": "家"},
    )
    assert replay.status_code == 200
    assert replay.json()["name"] == "家"
    assert replay.json()["name_revision"] == 1

    conflict = await client.put(
        f"/v1/location/places/{place_id}/name",
        headers=headers_a,
        json={"client_uuid": str(client_uuid), "name": "办公室"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "PLACE_NAME_CORRECTION_CONFLICT"

    same_value_new_key = await client.put(
        f"/v1/location/places/{place_id}/name",
        headers=headers_a,
        json={"client_uuid": str(uuid4()), "name": "家"},
    )
    assert same_value_new_key.status_code == 200
    assert same_value_new_key.json()["name_revision"] == 1

    with SessionLocal() as db:
        place = db.get(Place, place_id)
        assert place is not None
        assert place.user_id == user_a
        assert place.user_name == "家"
        assert place.name_revision == 1
        assert db.scalar(
            select(func.count())
            .select_from(PlaceNameCorrection)
            .where(PlaceNameCorrection.place_id == place_id)
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(ClientMutation)
            .where(
                ClientMutation.user_id == user_a,
                ClientMutation.operation_type == PLACE_NAME_CORRECTION_OPERATION,
            )
        ) == 2

        with pytest.raises(PlaceNamingError, match="PLACE_NOT_FOUND"):
            apply_automatic_place_label_candidate(
                db,
                user_id=uuid4(),
                place_id=place_id,
                label="foreign",
                source="TEST",
            )
        db.rollback()


@pytest.mark.asyncio
async def test_place_naming_export_is_owner_scoped_and_includes_correction_history(client):
    headers_a, user_a = await _new_user(client, "place-export-a")
    headers_b, user_b = await _new_user(client, "place-export-b")
    place_a, _ = await _derive_place(client, headers_a, "export-place-a")
    place_b, _ = await _derive_place(client, headers_b, "export-place-b")

    with SessionLocal() as db:
        apply_automatic_place_label_candidate(
            db,
            user_id=user_a,
            place_id=place_a,
            label="A 自动候选",
            source="POI_TEST",
        )
        apply_automatic_place_label_candidate(
            db,
            user_id=user_b,
            place_id=place_b,
            label="B 私密候选",
            source="POI_TEST",
        )
        db.commit()

    response = await client.put(
        f"/v1/location/places/{place_a}/name",
        headers=headers_a,
        json={"client_uuid": str(uuid4()), "name": "A 的家"},
    )
    assert response.status_code == 200
    response = await client.put(
        f"/v1/location/places/{place_b}/name",
        headers=headers_b,
        json={"client_uuid": str(uuid4()), "name": "B 私密地点"},
    )
    assert response.status_code == 200

    exported = await client.get("/v1/export/data", headers=headers_a)
    assert exported.status_code == 200
    location = exported.json()["location"]
    assert len(location["places"]) == 1
    assert location["places"][0]["id"] == str(place_a)
    assert location["places"][0]["name"] == "A 的家"
    assert location["places"][0]["automatic_name"] == "A 自动候选"
    assert location["places"][0]["user_name"] == "A 的家"
    assert location["places"][0]["name_source"] == "USER"
    assert len(location["place_name_corrections"]) == 1
    assert location["place_name_corrections"][0]["place_id"] == str(place_a)
    encoded = str(location)
    assert "B 私密候选" not in encoded
    assert "B 私密地点" not in encoded
