from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import LocationDerivationState, LocationPoint, User, Visit
from app.schemas import LocationBatchRequest, LocationPointCreate
from app.services.location_service import ingest_location_batch


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _visit_points(started: datetime, prefix: str) -> list[dict]:
    return [
        {
            "client_uuid": f"{prefix}-{index}",
            "latitude": 31.23040 + index * 0.00003,
            "longitude": 121.47370 + index * 0.00003,
            "accuracy": 12,
            "speed": 0.2,
            "recorded_at": (started + timedelta(minutes=index * 5)).isoformat(),
        }
        for index in range(3)
    ]


async def test_out_of_order_batch_derives_one_stable_visit_and_place(client):
    headers, _ = await _new_user(client, "location-order")
    points = _visit_points(datetime.now(UTC) - timedelta(minutes=20), "order")

    first = await client.post(
        "/v1/location/batch",
        headers=headers,
        json={"points": [points[2], points[0], points[1]]},
    )
    assert first.status_code == 200
    assert first.json()["accepted"] == 3
    assert first.json()["duplicates"] == 0
    assert first.json()["derived_visits"] == 1

    visits = (await client.get("/v1/location/visits", headers=headers)).json()
    places = (await client.get("/v1/location/places", headers=headers)).json()
    assert len(visits) == 1
    visit_id = visits[0]["id"]
    assert visits[0]["source_point_count"] == 3
    assert len(visits[0]["source_fingerprint"]) == 64
    assert visits[0]["algorithm_version"] == "visit-seq-v1"
    assert len(places) == 1
    assert places[0]["name"] == "未命名地点"
    assert places[0]["visit_count"] == 1

    replay = await client.post(
        "/v1/location/batch",
        headers=headers,
        json={"points": list(reversed(points))},
    )
    assert replay.status_code == 200
    assert replay.json()["accepted"] == 0
    assert replay.json()["duplicates"] == 3
    replay_visits = (await client.get("/v1/location/visits", headers=headers)).json()
    assert len(replay_visits) == 1
    assert replay_visits[0]["id"] == visit_id


async def test_client_uuid_conflict_is_fail_closed(client):
    headers, _ = await _new_user(client, "location-conflict")
    point = _visit_points(datetime.now(UTC) - timedelta(minutes=10), "conflict")[0]
    accepted = await client.post(
        "/v1/location/batch", headers=headers, json={"points": [point]}
    )
    assert accepted.status_code == 200

    changed = dict(point)
    changed["latitude"] = point["latitude"] + 0.01
    conflict = await client.post(
        "/v1/location/batch", headers=headers, json={"points": [changed]}
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "LOCATION_CLIENT_UUID_CONFLICT"


async def test_old_backfill_is_rejected_after_grace_window(client):
    headers, _ = await _new_user(client, "location-old")
    response = await client.post(
        "/v1/location/batch",
        headers=headers,
        json={
            "points": [
                {
                    "client_uuid": "too-old",
                    "latitude": 31.2,
                    "longitude": 121.4,
                    "recorded_at": (
                        datetime.now(UTC) - timedelta(days=2)
                    ).isoformat(),
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] == 0
    assert response.json()["rejected_finalized"] == 1


async def test_owner_isolation_for_derived_visits_and_places(client):
    headers_a, _ = await _new_user(client, "location-owner-a")
    headers_b, _ = await _new_user(client, "location-owner-b")
    points = _visit_points(datetime.now(UTC) - timedelta(minutes=20), "shared-client")

    for headers in (headers_a, headers_b):
        response = await client.post(
            "/v1/location/batch", headers=headers, json={"points": points}
        )
        assert response.status_code == 200
        assert response.json()["accepted"] == 3

    visits_a = (await client.get("/v1/location/visits", headers=headers_a)).json()
    visits_b = (await client.get("/v1/location/visits", headers=headers_b)).json()
    places_a = (await client.get("/v1/location/places", headers=headers_a)).json()
    places_b = (await client.get("/v1/location/places", headers=headers_b)).json()
    assert len(visits_a) == len(visits_b) == 1
    assert visits_a[0]["id"] != visits_b[0]["id"]
    assert places_a[0]["id"] != places_b[0]["id"]


def test_retention_deletes_raw_only_after_durable_visit_provenance_exists():
    now = datetime.now(UTC)
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="retention-owner"))
        db.commit()
        started = now - timedelta(days=40, minutes=10)
        db.add_all(
            [
                LocationPoint(
                    user_id=user_id,
                    client_uuid=f"retention-{index}",
                    latitude=31.2304 + index * 0.00002,
                    longitude=121.4737 + index * 0.00002,
                    recorded_at=started + timedelta(minutes=index * 5),
                )
                for index in range(3)
            ]
        )
        db.commit()

        payload = LocationBatchRequest(
            points=[
                LocationPointCreate(
                    client_uuid="recent-anchor",
                    latitude=30.0,
                    longitude=120.0,
                    recorded_at=now - timedelta(minutes=1),
                )
            ]
        )
        result = ingest_location_batch(
            db,
            user_id=user_id,
            payload=payload,
            now=now,
            settings=Settings(
                app_env="test",
                location_raw_retention_days=30,
                location_late_arrival_grace_seconds=86400,
                location_visit_max_gap_seconds=1800,
            ),
        )
        assert result.accepted == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(LocationPoint)
                .where(
                    LocationPoint.user_id == user_id,
                    LocationPoint.client_uuid.like("retention-%"),
                )
            )
            == 0
        )
        visit = db.scalar(
            select(Visit).where(
                Visit.user_id == user_id,
                Visit.source_point_count == 3,
            )
        )
        assert visit is not None
        assert visit.finalized_at is not None
        assert visit.source_started_at is not None
        assert visit.source_ended_at is not None
        assert visit.source_fingerprint is not None
        state = db.get(LocationDerivationState, user_id)
        assert state is not None
        assert state.finalized_through is not None

        user = db.get(User, user_id)
        assert user is not None
        db.delete(user)
        db.commit()
