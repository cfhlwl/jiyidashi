from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.family_models import (
    FamilyMembership,
    FamilyPermissionCode,
    FamilyPermissionGrant,
    FamilyRole,
)
from app.models import LocationPoint, Place, PrivacyState, User, Visit
from app.services.family_sensitive_read_service import (
    CURRENT_LOCATION_MAX_AGE,
    FamilySensitiveReadError,
    get_family_current_location,
)
from app.services.family_service import create_family
from app.services.time_service import local_today, user_day_bounds_utc


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return (
        {"Authorization": f"Bearer {body['access_token']}"},
        UUID(body["user_id"]),
    )


async def _family_pair(client, prefix: str):
    owner_headers, owner_id = await _new_user(client, f"{prefix}-owner")
    member_headers, member_id = await _new_user(client, f"{prefix}-member")
    assert (await client.post("/v1/family", headers=owner_headers)).status_code == 201
    invite = await client.post("/v1/family/invites", headers=owner_headers)
    assert invite.status_code == 201
    accepted = await client.post(
        "/v1/family/invites/accept",
        headers=member_headers,
        json={"token": invite.json()["token"]},
    )
    assert accepted.status_code == 200
    return owner_headers, owner_id, member_headers, member_id


async def _grant(client, owner_headers, grantee_id: UUID, *codes: str):
    response = await client.put(
        f"/v1/family/permissions/{grantee_id}",
        headers=owner_headers,
        json={"permissions": list(codes)},
    )
    assert response.status_code == 200
    return response


def _point(
    *,
    user_id: UUID,
    recorded_at: datetime,
    latitude: float,
    client_uuid: str,
    point_id: UUID | None = None,
) -> LocationPoint:
    return LocationPoint(
        id=point_id or uuid4(),
        user_id=user_id,
        client_uuid=client_uuid,
        latitude=latitude,
        longitude=121.4737,
        accuracy=8.0,
        speed=0.5,
        recorded_at=recorded_at,
    )


@pytest.mark.asyncio
async def test_exact_grant_isolation_owner_no_bypass_self_and_cross_family(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-read-auth"
    )
    _, _, outsider_headers, outsider_id = await _family_pair(
        client, "family-read-other"
    )
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(_point(
            user_id=owner_id,
            recorded_at=now,
            latitude=31.2304,
            client_uuid="auth-owner",
        ))
        db.add(_point(
            user_id=member_id,
            recorded_at=now,
            latitude=30.0,
            client_uuid="auth-member",
        ))
        db.commit()

    no_grant = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert no_grant.status_code == 403
    assert no_grant.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"

    # OWNER role alone cannot read MEMBER data.
    owner_bypass = await client.get(
        f"/v1/family/members/{member_id}/current-location",
        headers=owner_headers,
    )
    assert owner_bypass.status_code == 403

    self_read = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=owner_headers,
    )
    assert self_read.status_code == 409
    assert self_read.json()["detail"] == "FAMILY_SELF_READ_NOT_APPLICABLE"

    cross_family = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=outsider_headers,
    )
    assert cross_family.status_code == 403
    assert cross_family.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_MEMORY.value,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )
    wrong_current = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert wrong_current.status_code == 403
    wrong_footprint = await client.get(
        f"/v1/family/members/{owner_id}/today/footprint",
        headers=member_headers,
    )
    assert wrong_footprint.status_code == 403

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
    )
    allowed = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["resource_owner_user_id"] == str(owner_id)

    footprint_wrong_code = await client.get(
        f"/v1/family/members/{owner_id}/today/footprint",
        headers=member_headers,
    )
    assert footprint_wrong_code.status_code == 403

    # Cross-family probing stays the same shape regardless of the guessed owner UUID.
    outsider_probe = await client.get(
        f"/v1/family/members/{outsider_id}/current-location",
        headers=member_headers,
    )
    assert outsider_probe.status_code == 403
    assert outsider_probe.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_current_location_latest_freshness_privacy_whitelist_and_side_effect_free(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-current"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
    )
    reference = datetime.now(UTC)
    same_time = reference - timedelta(minutes=1)
    with SessionLocal() as db:
        other_user = uuid4()
        db.add(User(id=other_user, nickname="newer-foreign"))
        db.add_all(
            [
                _point(
                    user_id=owner_id,
                    recorded_at=same_time,
                    latitude=31.1,
                    client_uuid="tie-low",
                    point_id=UUID(int=101),
                ),
                _point(
                    user_id=owner_id,
                    recorded_at=same_time,
                    latitude=31.2,
                    client_uuid="tie-high",
                    point_id=UUID(int=102),
                ),
                _point(
                    user_id=other_user,
                    recorded_at=reference + timedelta(seconds=1),
                    latitude=45.0,
                    client_uuid="foreign-newer",
                ),
            ]
        )
        db.commit()
        before_points = int(db.scalar(select(func.count()).select_from(LocationPoint)) or 0)
        before_visits = int(db.scalar(select(func.count()).select_from(Visit)) or 0)
        before_places = int(db.scalar(select(func.count()).select_from(Place)) or 0)
        before_privacy = int(db.scalar(select(func.count()).select_from(PrivacyState)) or 0)

    response = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "resource_owner_user_id",
        "latitude",
        "longitude",
        "accuracy",
        "recorded_at",
        "fresh_until",
    }
    assert body["resource_owner_user_id"] == str(owner_id)
    assert body["latitude"] == 31.2
    assert "id" not in body
    assert "client_uuid" not in body
    assert "device_id" not in body
    assert "speed" not in body

    with SessionLocal() as db:
        assert int(db.scalar(select(func.count()).select_from(LocationPoint)) or 0) == before_points
        assert int(db.scalar(select(func.count()).select_from(Visit)) or 0) == before_visits
        assert int(db.scalar(select(func.count()).select_from(Place)) or 0) == before_places
        assert int(db.scalar(select(func.count()).select_from(PrivacyState)) or 0) == before_privacy

        # Exactly at 15 minutes is fresh; one microsecond older is stale.
        db.query(LocationPoint).filter(LocationPoint.user_id == owner_id).delete()
        db.add(_point(
            user_id=owner_id,
            recorded_at=reference - CURRENT_LOCATION_MAX_AGE,
            latitude=32.0,
            client_uuid="boundary",
        ))
        db.commit()
        boundary = get_family_current_location(
            db,
            resource_owner_user_id=owner_id,
            grantee_user_id=member_id,
            now=reference,
        )
        assert boundary.latitude == 32.0

        db.query(LocationPoint).filter(LocationPoint.user_id == owner_id).delete()
        db.add(_point(
            user_id=owner_id,
            recorded_at=reference - CURRENT_LOCATION_MAX_AGE - timedelta(microseconds=1),
            latitude=33.0,
            client_uuid="stale",
        ))
        db.commit()
        with pytest.raises(FamilySensitiveReadError) as stale:
            get_family_current_location(
                db,
                resource_owner_user_id=owner_id,
                grantee_user_id=member_id,
                now=reference,
            )
        assert stale.value.code == "CURRENT_LOCATION_UNAVAILABLE"

        db.query(LocationPoint).filter(LocationPoint.user_id == owner_id).delete()
        db.add(_point(
            user_id=owner_id,
            recorded_at=reference,
            latitude=34.0,
            client_uuid="privacy",
        ))
        db.add(
            PrivacyState(
                user_id=owner_id,
                recording_paused_since=reference - timedelta(minutes=1),
                recording_paused_until=reference + timedelta(minutes=10),
            )
        )
        db.commit()

    paused = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert paused.status_code == 404
    assert paused.json()["detail"] == "CURRENT_LOCATION_UNAVAILABLE"

    resumed = await client.post("/v1/privacy/resume", headers=owner_headers)
    assert resumed.status_code == 200
    after_resume = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert after_resume.status_code == 200
    assert after_resume.json()["latitude"] == 34.0


@pytest.mark.asyncio
async def test_current_location_no_point_future_and_pending_grant_fail_closed(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-current-unavailable"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
    )

    missing = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "CURRENT_LOCATION_UNAVAILABLE"

    reference = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(_point(
            user_id=owner_id,
            recorded_at=reference + timedelta(hours=1),
            latitude=50.0,
            client_uuid="future",
        ))
        db.commit()
        with pytest.raises(FamilySensitiveReadError) as future:
            get_family_current_location(
                db,
                resource_owner_user_id=owner_id,
                grantee_user_id=member_id,
                now=reference,
            )
        assert future.value.code == "CURRENT_LOCATION_UNAVAILABLE"

    skew = timedelta(seconds=get_settings().location_future_skew_seconds)
    with SessionLocal() as db:
        db.query(LocationPoint).filter(LocationPoint.user_id == owner_id).delete()
        db.add(
            _point(
                user_id=owner_id,
                recorded_at=reference + skew,
                latitude=51.0,
                client_uuid="future-exact-boundary",
            )
        )
        db.commit()
        exact_boundary = get_family_current_location(
            db,
            resource_owner_user_id=owner_id,
            grantee_user_id=member_id,
            now=reference,
        )
        assert exact_boundary.latitude == 51.0

        db.query(LocationPoint).filter(LocationPoint.user_id == owner_id).delete()
        db.add(
            _point(
                user_id=owner_id,
                recorded_at=reference + skew + timedelta(microseconds=1),
                latitude=52.0,
                client_uuid="future-over-boundary",
            )
        )
        db.commit()
        with pytest.raises(FamilySensitiveReadError) as over_boundary:
            get_family_current_location(
                db,
                resource_owner_user_id=owner_id,
                grantee_user_id=member_id,
                now=reference,
            )
        assert over_boundary.value.code == "CURRENT_LOCATION_UNAVAILABLE"

    pending_owner = uuid4()
    pending_member = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                User(id=pending_owner, nickname="pending-owner"),
                User(id=pending_member, nickname="pending-member"),
            ]
        )
        db.commit()
        family = create_family(db, user_id=pending_owner)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=pending_member,
                role=FamilyRole.MEMBER.value,
            )
        )
        db.add(_point(
            user_id=pending_owner,
            recorded_at=reference,
            latitude=10.0,
            client_uuid="pending-point",
        ))
        db.commit()
        db.add(
            FamilyPermissionGrant(
                family_id=family.family_id,
                resource_owner_user_id=pending_owner,
                grantee_user_id=pending_member,
                permission_code=FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
            )
        )
        with pytest.raises(FamilySensitiveReadError) as pending:
            get_family_current_location(
                db,
                resource_owner_user_id=pending_owner,
                grantee_user_id=pending_member,
                now=reference,
            )
        assert pending.value.code == "FAMILY_READ_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_today_footprint_uses_owner_timezone_overlap_and_existing_projection(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-footprint"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_FOOTPRINT.value,
    )

    with SessionLocal() as db:
        owner = db.get(User, owner_id)
        member = db.get(User, member_id)
        assert owner is not None and member is not None
        owner.timezone = "Asia/Shanghai"
        member.timezone = "America/New_York"
        db.commit()

        day = local_today(db, owner_id)
        start_utc, _ = user_day_bounds_utc(db, owner_id, day)
        place = Place(
            user_id=owner_id,
            name="Owner Place",
            cluster_key="fp-owner",
        )
        foreign_place = Place(
            user_id=member_id,
            name="Foreign Place",
            cluster_key="fp-foreign",
        )
        db.add_all([place, foreign_place])
        db.flush()
        first = Visit(
            user_id=owner_id,
            place_id=place.id,
            arrived_at=start_utc - timedelta(hours=1),
            left_at=start_utc + timedelta(minutes=20),
            confidence=0.9,
            source="TEST",
        )
        second = Visit(
            user_id=owner_id,
            place_id=place.id,
            arrived_at=start_utc + timedelta(hours=2),
            left_at=start_utc + timedelta(hours=3),
            confidence=0.8,
            source="TEST",
        )
        # Deliberately mismatched owner/place pair must be excluded by owner Place join.
        corrupt = Visit(
            user_id=owner_id,
            place_id=foreign_place.id,
            arrived_at=start_utc + timedelta(hours=4),
            left_at=start_utc + timedelta(hours=5),
            confidence=0.7,
            source="TEST",
        )
        db.add_all([second, corrupt, first])
        db.commit()
        place_id = place.id
        before_visits = int(
            db.scalar(
                select(func.count()).select_from(Visit).where(Visit.user_id == owner_id)
            )
            or 0
        )
        before_places = int(
            db.scalar(
                select(func.count()).select_from(Place).where(Place.user_id == owner_id)
            )
            or 0
        )

    family = await client.get(
        f"/v1/family/members/{owner_id}/today/footprint",
        headers=member_headers,
    )
    assert family.status_code == 200
    body = family.json()
    assert body["timezone"] == "Asia/Shanghai"
    assert body["day"] == day.isoformat()
    assert [item["place_name"] for item in body["visits"]] == [
        "Owner Place",
        "Owner Place",
    ]
    assert [
        datetime.fromisoformat(item["arrived_at"]) for item in body["visits"]
    ] == sorted(datetime.fromisoformat(item["arrived_at"]) for item in body["visits"])
    assert all("latitude" not in item and "longitude" not in item for item in body["visits"])

    with SessionLocal() as db:
        assert int(
            db.scalar(
                select(func.count()).select_from(Visit).where(Visit.user_id == owner_id)
            )
            or 0
        ) == before_visits
        assert int(
            db.scalar(
                select(func.count()).select_from(Place).where(Place.user_id == owner_id)
            )
            or 0
        ) == before_places

    # Existing first-party projection remains unchanged and matches the owner view.
    self_view = await client.get("/v1/today/footprint", headers=owner_headers)
    assert self_view.status_code == 200
    assert self_view.json() == body

    # Existing location list remains bound to the authenticated caller.
    member_visits = await client.get("/v1/location/visits", headers=member_headers)
    assert member_visits.status_code == 200
    assert member_visits.json() == []

    owner_place = await client.get(
        f"/v1/location/places/{place_id}",
        headers=owner_headers,
    )
    assert owner_place.status_code == 200
    member_place_probe = await client.get(
        f"/v1/location/places/{place_id}",
        headers=member_headers,
    )
    assert member_place_probe.status_code == 404


@pytest.mark.asyncio
async def test_removed_resource_owner_membership_denies_family_sensitive_reads(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-read-owner-leave"
    )
    await _grant(
        client,
        member_headers,
        owner_id,
        FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
        FamilyPermissionCode.VIEW_FOOTPRINT.value,
    )
    with SessionLocal() as db:
        db.add(
            _point(
                user_id=member_id,
                recorded_at=datetime.now(UTC),
                latitude=35.0,
                client_uuid="owner-leave-point",
            )
        )
        db.commit()

    allowed = await client.get(
        f"/v1/family/members/{member_id}/current-location",
        headers=owner_headers,
    )
    assert allowed.status_code == 200

    left = await client.delete(
        f"/v1/family/members/{member_id}",
        headers=member_headers,
    )
    assert left.status_code == 204

    for suffix in ("current-location", "today/footprint"):
        denied = await client.get(
            f"/v1/family/members/{member_id}/{suffix}",
            headers=owner_headers,
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_removed_membership_immediately_denies_family_sensitive_reads(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-read-remove"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
        FamilyPermissionCode.VIEW_FOOTPRINT.value,
    )
    with SessionLocal() as db:
        db.add(_point(
            user_id=owner_id,
            recorded_at=datetime.now(UTC),
            latitude=31.0,
            client_uuid="remove-point",
        ))
        db.commit()

    removed = await client.delete(
        f"/v1/family/members/{member_id}",
        headers=owner_headers,
    )
    assert removed.status_code == 204

    for suffix in ("current-location", "today/footprint"):
        denied = await client.get(
            f"/v1/family/members/{owner_id}/{suffix}",
            headers=member_headers,
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"
