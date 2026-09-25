from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.family_models import (
    FamilyAccessAuditEvent,
    FamilyAuditAuthorityType,
    FamilyAuditResult,
    FamilyEmergencyLocationShare,
    FamilyPermissionCode,
    FamilyPermissionGrant,
)
from app.models import LocationPoint
from app.services.family_emergency_location_service import (
    FamilyEmergencyShareError,
    get_emergency_shared_location,
)
from app.services.privacy_service import pause_recording


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


async def _create_share(client, owner_headers, member_id: UUID, duration: int = 30):
    response = await client.post(
        "/v1/family/emergency-location-shares",
        headers=owner_headers,
        json={"grantee_user_id": str(member_id), "duration_minutes": duration},
    )
    assert response.status_code == 201
    return response.json()


def _fresh_location(user_id: UUID, *, recorded_at: datetime | None = None) -> None:
    with SessionLocal() as db:
        db.add(
            LocationPoint(
                user_id=user_id,
                client_uuid=f"emergency-{uuid4().hex}",
                latitude=39.9042,
                longitude=116.4074,
                accuracy=7.0,
                speed=None,
                recorded_at=recorded_at or datetime.now(UTC),
            )
        )
        db.commit()


@pytest.mark.asyncio
async def test_emergency_share_is_self_owned_fixed_duration_and_list_metadata_only(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-create"
    )

    for duration in (30, 60, 180):
        before = datetime.now(UTC)
        body = await _create_share(client, owner_headers, member_id, duration)
        assert body["resource_owner_user_id"] == str(owner_id)
        assert body["grantee_user_id"] == str(member_id)
        assert body["direction"] == "OUTGOING"
        expires = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        created = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
        assert expires - created == timedelta(minutes=duration)
        assert created >= before - timedelta(seconds=1)

    invalid = await client.post(
        "/v1/family/emergency-location-shares",
        headers=owner_headers,
        json={"grantee_user_id": str(member_id), "duration_minutes": 181},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "EMERGENCY_SHARE_DURATION_UNSUPPORTED"

    self_target = await client.post(
        "/v1/family/emergency-location-shares",
        headers=owner_headers,
        json={"grantee_user_id": str(owner_id), "duration_minutes": 30},
    )
    assert self_target.status_code == 409
    assert self_target.json()["detail"] == "EMERGENCY_SHARE_TARGET_INVALID"

    outgoing = await client.get(
        "/v1/family/emergency-location-shares",
        headers=owner_headers,
    )
    incoming = await client.get(
        "/v1/family/emergency-location-shares",
        headers=member_headers,
    )
    assert outgoing.status_code == 200
    assert incoming.status_code == 200
    assert len(outgoing.json()) == 1
    assert len(incoming.json()) == 1
    assert outgoing.json()[0]["direction"] == "OUTGOING"
    assert incoming.json()[0]["direction"] == "INCOMING"
    assert set(outgoing.json()[0]) == {
        "share_id",
        "resource_owner_user_id",
        "grantee_user_id",
        "expires_at",
        "created_at",
        "direction",
    }


@pytest.mark.asyncio
async def test_emergency_share_rejects_cross_family_and_supersedes_same_pair(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-supersede"
    )
    other_headers, other_id, _, _ = await _family_pair(client, "emergency-other")

    cross = await client.post(
        "/v1/family/emergency-location-shares",
        headers=owner_headers,
        json={"grantee_user_id": str(other_id), "duration_minutes": 30},
    )
    assert cross.status_code == 404
    assert cross.json()["detail"] == "EMERGENCY_SHARE_TARGET_INVALID"

    first = await _create_share(client, owner_headers, member_id, 30)
    second = await _create_share(client, owner_headers, member_id, 60)
    assert first["share_id"] != second["share_id"]

    with SessionLocal() as db:
        old = db.get(FamilyEmergencyLocationShare, UUID(first["share_id"]))
        new = db.get(FamilyEmergencyLocationShare, UUID(second["share_id"]))
        assert old is not None and old.revoked_at is not None
        assert new is not None and new.revoked_at is None


@pytest.mark.asyncio
async def test_emergency_authority_is_independent_from_ordinary_location_grant(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-independent"
    )
    _fresh_location(owner_id)
    share = await _create_share(client, owner_headers, member_id, 30)

    emergency = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=member_headers,
    )
    assert emergency.status_code == 200

    normal = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert normal.status_code == 403

    grant = await client.put(
        f"/v1/family/permissions/{member_id}",
        headers=owner_headers,
        json={"permissions": [FamilyPermissionCode.VIEW_CURRENT_LOCATION.value]},
    )
    assert grant.status_code == 200

    revoked = await client.post(
        f"/v1/family/emergency-location-shares/{share['share_id']}/revoke",
        headers=owner_headers,
    )
    assert revoked.status_code == 204

    emergency_after = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=member_headers,
    )
    assert emergency_after.status_code == 404
    assert emergency_after.json()["detail"] == "EMERGENCY_SHARE_NOT_AVAILABLE"

    normal_after = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert normal_after.status_code == 200

    share2 = await _create_share(client, owner_headers, member_id, 30)
    remove_grant = await client.put(
        f"/v1/family/permissions/{member_id}",
        headers=owner_headers,
        json={"permissions": []},
    )
    assert remove_grant.status_code == 200
    emergency_still_active = await client.get(
        f"/v1/family/emergency-location-shares/{share2['share_id']}/location",
        headers=member_headers,
    )
    assert emergency_still_active.status_code == 200

    with SessionLocal() as db:
        assert db.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.resource_owner_user_id == owner_id,
                FamilyPermissionGrant.grantee_user_id == member_id,
                FamilyPermissionGrant.permission_code
                == FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
            )
        ) is None


@pytest.mark.asyncio
async def test_emergency_location_wrong_recipient_expiry_pause_and_audit_truth(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-read"
    )
    third_headers, third_id = await _new_user(client, "emergency-third")
    _fresh_location(owner_id)
    share = await _create_share(client, owner_headers, member_id, 30)

    wrong = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=third_headers,
    )
    assert wrong.status_code == 404
    assert wrong.json()["detail"] == "EMERGENCY_SHARE_NOT_AVAILABLE"

    allowed = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=member_headers,
    )
    assert allowed.status_code == 200

    with SessionLocal() as db:
        audits = db.scalars(
            select(FamilyAccessAuditEvent).where(
                FamilyAccessAuditEvent.resource_owner_user_id == owner_id,
                FamilyAccessAuditEvent.actor_user_id == member_id,
                FamilyAccessAuditEvent.action == "READ_EMERGENCY_LOCATION",
            )
        ).all()
        assert len(audits) == 1
        assert audits[0].authority_type == FamilyAuditAuthorityType.EMERGENCY_SHARE.value
        assert audits[0].permission_code is None
        assert audits[0].result == FamilyAuditResult.ALLOWED.value

        pause_recording(
            db,
            owner_id,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        db.commit()

    paused = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=member_headers,
    )
    assert paused.status_code == 404
    assert paused.json()["detail"] == "CURRENT_LOCATION_UNAVAILABLE"

    with SessionLocal() as db:
        row = db.get(FamilyEmergencyLocationShare, UUID(share["share_id"]))
        assert row is not None
        expired_at = datetime.now(UTC) - timedelta(seconds=1)
        row.created_at = expired_at - timedelta(minutes=30)
        row.expires_at = expired_at
        db.commit()

    expired = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=member_headers,
    )
    assert expired.status_code == 404
    assert expired.json()["detail"] == "EMERGENCY_SHARE_NOT_AVAILABLE"


@pytest.mark.asyncio
async def test_emergency_revoke_is_owner_only_and_idempotent(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-revoke"
    )
    share = await _create_share(client, owner_headers, member_id, 30)

    denied = await client.post(
        f"/v1/family/emergency-location-shares/{share['share_id']}/revoke",
        headers=member_headers,
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "EMERGENCY_SHARE_NOT_AVAILABLE"

    first = await client.post(
        f"/v1/family/emergency-location-shares/{share['share_id']}/revoke",
        headers=owner_headers,
    )
    second = await client.post(
        f"/v1/family/emergency-location-shares/{share['share_id']}/revoke",
        headers=owner_headers,
    )
    assert first.status_code == 204
    assert second.status_code == 204



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recorded_at",
    [
        datetime.now(UTC) - timedelta(minutes=16),
        datetime.now(UTC) + timedelta(hours=1),
    ],
)
async def test_emergency_location_stale_or_future_point_is_unavailable(
    client,
    recorded_at: datetime,
):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, f"emergency-age-{uuid4().hex[:6]}"
    )
    _fresh_location(owner_id, recorded_at=recorded_at)
    share = await _create_share(client, owner_headers, member_id, 30)

    response = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=member_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "CURRENT_LOCATION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_expired_emergency_share_is_not_returned_in_active_list(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-expired-list"
    )
    share = await _create_share(client, owner_headers, member_id, 30)

    with SessionLocal() as db:
        row = db.get(FamilyEmergencyLocationShare, UUID(share["share_id"]))
        assert row is not None
        expired_at = datetime.now(UTC) - timedelta(seconds=1)
        row.created_at = expired_at - timedelta(minutes=30)
        row.expires_at = expired_at
        db.commit()

    owner_list = await client.get(
        "/v1/family/emergency-location-shares",
        headers=owner_headers,
    )
    member_list = await client.get(
        "/v1/family/emergency-location-shares",
        headers=member_headers,
    )
    assert owner_list.status_code == 200
    assert member_list.status_code == 200
    assert owner_list.json() == []
    assert member_list.json() == []


@pytest.mark.asyncio
async def test_family_owner_role_does_not_bypass_exact_emergency_grantee(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-role"
    )
    second_headers, second_id = await _new_user(client, "emergency-role-second")
    invite = await client.post("/v1/family/invites", headers=owner_headers)
    accepted = await client.post(
        "/v1/family/invites/accept",
        headers=second_headers,
        json={"token": invite.json()["token"]},
    )
    assert accepted.status_code == 200

    _fresh_location(member_id)
    share = await _create_share(client, member_headers, second_id, 30)

    owner_attempt = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=owner_headers,
    )
    exact_grantee = await client.get(
        f"/v1/family/emergency-location-shares/{share['share_id']}/location",
        headers=second_headers,
    )
    assert owner_attempt.status_code == 404
    assert owner_attempt.json()["detail"] == "EMERGENCY_SHARE_NOT_AVAILABLE"
    assert exact_grantee.status_code == 200



@pytest.mark.asyncio
async def test_emergency_share_exact_expiry_boundary_is_expired(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "emergency-boundary"
    )
    _fresh_location(owner_id)
    share = await _create_share(client, owner_headers, member_id, 30)

    with SessionLocal() as db:
        row = db.get(FamilyEmergencyLocationShare, UUID(share["share_id"]))
        assert row is not None
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)

    with SessionLocal() as db:
        with pytest.raises(FamilyEmergencyShareError) as expired:
            get_emergency_shared_location(
                db,
                share_id=UUID(share["share_id"]),
                grantee_user_id=member_id,
                now=expires_at,
            )
        assert expired.value.code == "EMERGENCY_SHARE_NOT_AVAILABLE"
        assert expired.value.status_code == 404
