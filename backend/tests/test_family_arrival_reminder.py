from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.family_models import (
    FamilyArrivalReminder,
    FamilyArrivalReminderStatus,
    FamilyEmergencyLocationShare,
    FamilyPermissionCode,
    FamilyPermissionGrant,
)
from app.models import Place, Visit
from app.services.family_arrival_reminder_service import (
    derive_arrival_for_finalized_visit,
    list_arrival_reminders,
)
from app.services.privacy_service import ensure_utc, pause_recording


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


async def _family_pair(client, prefix: str):
    owner_headers, owner_id = await _new_user(client, f"{prefix}-owner")
    member_headers, member_id = await _new_user(client, f"{prefix}-member")
    assert (await client.post("/v1/family", headers=owner_headers)).status_code == 201
    invite = await client.post("/v1/family/invites", headers=owner_headers)
    accepted = await client.post(
        "/v1/family/invites/accept",
        headers=member_headers,
        json={"token": invite.json()["token"]},
    )
    assert accepted.status_code == 200
    return owner_headers, owner_id, member_headers, member_id


def _place(user_id: UUID, name: str = "家") -> UUID:
    place_id = uuid4()
    with SessionLocal() as db:
        db.add(
            Place(
                id=place_id,
                user_id=user_id,
                name=name,
                user_name=name,
                name_revision=1,
                is_user_named=True,
            )
        )
        db.commit()
    return place_id


async def _create(
    client,
    owner_headers,
    member_id: UUID,
    place_id: UUID,
    validity: int = 120,
):
    response = await client.post(
        "/v1/family/arrival-reminders",
        headers=owner_headers,
        json={
            "grantee_user_id": str(member_id),
            "destination_place_id": str(place_id),
            "validity_minutes": validity,
        },
    )
    assert response.status_code == 201
    return response.json()


def _visit(
    user_id: UUID,
    place_id: UUID,
    *,
    arrived_at: datetime,
    finalized_at: datetime | None,
) -> Visit:
    return Visit(
        id=uuid4(),
        user_id=user_id,
        place_id=place_id,
        arrived_at=arrived_at,
        left_at=arrived_at + timedelta(minutes=12),
        duration_seconds=720,
        confidence=0.9,
        source="LOCATION_CLUSTER",
        derivation_key=uuid4().hex,
        source_started_at=arrived_at,
        source_ended_at=arrived_at + timedelta(minutes=12),
        source_point_count=4,
        source_fingerprint=uuid4().hex,
        algorithm_version="visit-seq-v1",
        finalized_at=finalized_at,
    )


@pytest.mark.asyncio
async def test_arrival_reminder_create_list_cancel_contract(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "arrival-contract"
    )
    place_id = _place(owner_id)

    for validity in (120, 360, 720):
        body = await _create(client, owner_headers, member_id, place_id, validity)
        assert body["resource_owner_user_id"] == str(owner_id)
        assert body["grantee_user_id"] == str(member_id)
        assert body["destination_place_id"] == str(place_id)
        assert body["destination_display_name"] == "家"
        assert body["status"] == "ACTIVE"
        assert body["direction"] == "OUTGOING"
        created = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert expires - created == timedelta(minutes=validity)

    invalid = await client.post(
        "/v1/family/arrival-reminders",
        headers=owner_headers,
        json={
            "grantee_user_id": str(member_id),
            "destination_place_id": str(place_id),
            "validity_minutes": 721,
        },
    )
    assert invalid.status_code == 422

    raw_coordinates = await client.post(
        "/v1/family/arrival-reminders",
        headers=owner_headers,
        json={
            "grantee_user_id": str(member_id),
            "destination_place_id": str(place_id),
            "validity_minutes": 120,
            "latitude": 31.2,
            "longitude": 121.4,
        },
    )
    assert raw_coordinates.status_code == 422

    outgoing = await client.get("/v1/family/arrival-reminders", headers=owner_headers)
    incoming = await client.get("/v1/family/arrival-reminders", headers=member_headers)
    assert outgoing.status_code == 200
    assert incoming.status_code == 200
    assert outgoing.json()[0]["direction"] == "OUTGOING"
    assert incoming.json()[0]["direction"] == "INCOMING"
    assert set(outgoing.json()[0]) == {
        "reminder_id",
        "resource_owner_user_id",
        "grantee_user_id",
        "destination_place_id",
        "destination_display_name",
        "status",
        "created_at",
        "expires_at",
        "arrived_at",
        "direction",
    }
    serialized = str(incoming.json()).lower()
    for forbidden in (
        "latitude",
        "longitude",
        "visit_id",
        "locationpoint",
        "accuracy",
        "speed",
        "route",
        "eta",
    ):
        assert forbidden not in serialized

    reminder_id = outgoing.json()[0]["reminder_id"]
    denied = await client.post(
        f"/v1/family/arrival-reminders/{reminder_id}/cancel",
        headers=member_headers,
    )
    assert denied.status_code == 404

    first = await client.post(
        f"/v1/family/arrival-reminders/{reminder_id}/cancel",
        headers=owner_headers,
    )
    second = await client.post(
        f"/v1/family/arrival-reminders/{reminder_id}/cancel",
        headers=owner_headers,
    )
    assert first.status_code == 204
    assert second.status_code == 204


@pytest.mark.asyncio
async def test_arrival_reminder_self_cross_family_and_foreign_place_denied(client):
    owner_headers, owner_id, _, member_id = await _family_pair(client, "arrival-target")
    other_headers, other_id, _, _ = await _family_pair(client, "arrival-other")
    own_place = _place(owner_id, "我家")
    foreign_place = _place(other_id, "别人家")

    self_target = await client.post(
        "/v1/family/arrival-reminders",
        headers=owner_headers,
        json={
            "grantee_user_id": str(owner_id),
            "destination_place_id": str(own_place),
            "validity_minutes": 120,
        },
    )
    assert self_target.status_code == 409

    cross = await client.post(
        "/v1/family/arrival-reminders",
        headers=owner_headers,
        json={
            "grantee_user_id": str(other_id),
            "destination_place_id": str(own_place),
            "validity_minutes": 120,
        },
    )
    assert cross.status_code == 404

    foreign = await client.post(
        "/v1/family/arrival-reminders",
        headers=owner_headers,
        json={
            "grantee_user_id": str(member_id),
            "destination_place_id": str(foreign_place),
            "validity_minutes": 120,
        },
    )
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_arrival_reminder_independent_from_location_grant_and_emergency_share(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "arrival-independent"
    )
    place_id = _place(owner_id)
    reminder = await _create(client, owner_headers, member_id, place_id)

    normal = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert normal.status_code == 403

    with SessionLocal() as db:
        assert db.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.resource_owner_user_id == owner_id,
                FamilyPermissionGrant.grantee_user_id == member_id,
                FamilyPermissionGrant.permission_code
                == FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
            )
        ) is None
        assert db.scalar(
            select(FamilyEmergencyLocationShare.id).where(
                FamilyEmergencyLocationShare.resource_owner_user_id == owner_id,
                FamilyEmergencyLocationShare.grantee_user_id == member_id,
            )
        ) is None
        assert db.get(FamilyArrivalReminder, UUID(reminder["reminder_id"])) is not None


@pytest.mark.asyncio
async def test_arrival_transition_is_finalized_visit_exact_place_and_monotonic(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "arrival-transition"
    )
    home = _place(owner_id, "家")
    office = _place(owner_id, "公司")
    reminder = await _create(client, owner_headers, member_id, home, 120)
    now = datetime.now(UTC)
    visit = _visit(
        owner_id,
        home,
        arrived_at=now + timedelta(minutes=5),
        finalized_at=now + timedelta(minutes=20),
    )
    wrong = _visit(
        owner_id,
        office,
        arrived_at=now + timedelta(minutes=3),
        finalized_at=now + timedelta(minutes=18),
    )

    with SessionLocal() as db:
        db.add_all([visit, wrong])
        db.commit()
        assert derive_arrival_for_finalized_visit(
            db,
            visit=wrong,
            now=now + timedelta(minutes=25),
        ) == 0
        assert derive_arrival_for_finalized_visit(
            db,
            visit=visit,
            now=now + timedelta(minutes=25),
        ) == 1
        db.commit()
        assert derive_arrival_for_finalized_visit(
            db,
            visit=visit,
            now=now + timedelta(minutes=26),
        ) == 0
        db.commit()

        row = db.get(FamilyArrivalReminder, UUID(reminder["reminder_id"]))
        assert row is not None
        assert row.status == FamilyArrivalReminderStatus.ARRIVED.value
        assert row.arrived_at is not None
        assert ensure_utc(row.arrived_at) == ensure_utc(visit.arrived_at)

    incoming = await client.get("/v1/family/arrival-reminders", headers=member_headers)
    assert incoming.status_code == 200
    item = incoming.json()[0]
    assert item["status"] == "ARRIVED"
    assert item["arrived_at"] is not None


@pytest.mark.asyncio
async def test_cancelled_expired_and_paused_visit_never_arrive(client):
    owner_headers, owner_id, _, member_id = await _family_pair(client, "arrival-terminal")
    home = _place(owner_id, "家")
    now = datetime.now(UTC)

    cancelled = await _create(client, owner_headers, member_id, home, 120)
    assert (
        await client.post(
            f"/v1/family/arrival-reminders/{cancelled['reminder_id']}/cancel",
            headers=owner_headers,
        )
    ).status_code == 204

    expired = await _create(client, owner_headers, member_id, home, 120)
    with SessionLocal() as db:
        row = db.get(FamilyArrivalReminder, UUID(expired["reminder_id"]))
        assert row is not None
        row.created_at = now - timedelta(hours=3)
        row.expires_at = now - timedelta(hours=1)
        db.commit()

    paused = await _create(client, owner_headers, member_id, home, 120)
    visit = _visit(
        owner_id,
        home,
        arrived_at=now + timedelta(minutes=10),
        finalized_at=now + timedelta(minutes=30),
    )
    with SessionLocal() as db:
        pause_recording(
            db,
            owner_id,
            started_at=now + timedelta(minutes=5),
            ended_at=now + timedelta(minutes=20),
        )
        db.add(visit)
        db.commit()
        assert derive_arrival_for_finalized_visit(
            db,
            visit=visit,
            now=now + timedelta(minutes=30),
        ) == 0
        db.commit()
        for reminder_id in (
            cancelled["reminder_id"],
            expired["reminder_id"],
            paused["reminder_id"],
        ):
            row = db.get(FamilyArrivalReminder, UUID(reminder_id))
            assert row is not None
            assert row.status != FamilyArrivalReminderStatus.ARRIVED.value


@pytest.mark.asyncio
async def test_exact_expiry_boundary_materializes_expired(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "arrival-expiry"
    )
    home = _place(owner_id)
    reminder = await _create(client, owner_headers, member_id, home, 120)
    with SessionLocal() as db:
        row = db.get(FamilyArrivalReminder, UUID(reminder["reminder_id"]))
        assert row is not None
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        rows = list_arrival_reminders(db, user_id=member_id, now=expires)
        assert rows[0].status == FamilyArrivalReminderStatus.EXPIRED.value
        db.commit()
