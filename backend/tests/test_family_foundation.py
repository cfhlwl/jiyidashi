from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.api.family import router as family_router
from app.core.db import SessionLocal
from app.family_models import (
    FamilyInvite,
    FamilyMembership,
    FamilyPermissionCode,
    FamilyPermissionGrant,
    FamilyRole,
)
from app.models import User
from app.services.family_service import (
    FamilyServiceError,
    create_family,
    create_invite,
    has_family_permission,
    replace_permissions,
)


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return (
        {"Authorization": f"Bearer {body['access_token']}"},
        UUID(body["user_id"]),
    )


@pytest.mark.asyncio
async def test_family_create_is_atomic_and_second_family_is_denied(client):
    headers, user_id = await _new_user(client, "family-owner")

    created = await client.post("/v1/family", headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["current_user_role"] == "OWNER"
    assert body["members"] == [
        {
            "user_id": str(user_id),
            "role": "OWNER",
            "created_at": body["members"][0]["created_at"],
        }
    ]

    second = await client.post("/v1/family", headers=headers)
    assert second.status_code == 409
    assert second.json()["detail"] == "FAMILY_ALREADY_JOINED"

    with SessionLocal() as db:
        membership = db.scalar(
            select(FamilyMembership).where(FamilyMembership.user_id == user_id)
        )
        assert membership is not None
        assert membership.role == FamilyRole.OWNER.value


@pytest.mark.asyncio
async def test_owner_only_invite_hash_expiry_revoke_and_single_use(client):
    owner_headers, owner_id = await _new_user(client, "invite-owner")
    member_headers, member_id = await _new_user(client, "invite-member")
    outsider_headers, _ = await _new_user(client, "invite-outsider")

    assert (await client.post("/v1/family", headers=owner_headers)).status_code == 201
    invite = await client.post("/v1/family/invites", headers=owner_headers)
    assert invite.status_code == 201
    invite_body = invite.json()
    raw = invite_body["token"]

    with SessionLocal() as db:
        row = db.get(FamilyInvite, UUID(invite_body["invite_id"]))
        assert row is not None
        assert row.token_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert raw not in row.token_hash
        assert row.inviter_user_id == owner_id

    accepted = await client.post(
        "/v1/family/invites/accept",
        headers=member_headers,
        json={"token": raw},
    )
    assert accepted.status_code == 200
    assert accepted.json()["current_user_role"] == "MEMBER"

    replay = await client.post(
        "/v1/family/invites/accept",
        headers=outsider_headers,
        json={"token": raw},
    )
    assert replay.status_code == 409
    assert replay.json()["detail"] == "FAMILY_INVITE_NOT_ACTIVE"

    member_invite = await client.post("/v1/family/invites", headers=member_headers)
    assert member_invite.status_code == 403
    assert member_invite.json()["detail"] == "FAMILY_OWNER_REQUIRED"

    second = await client.post("/v1/family/invites", headers=owner_headers)
    assert second.status_code == 201
    revoked = await client.delete(
        f"/v1/family/invites/{second.json()['invite_id']}",
        headers=owner_headers,
    )
    assert revoked.status_code == 204
    rejected = await client.post(
        "/v1/family/invites/accept",
        headers=outsider_headers,
        json={"token": second.json()["token"]},
    )
    assert rejected.status_code == 409

    with SessionLocal() as db:
        expired = create_invite(
            db,
            user_id=owner_id,
            now=datetime.now(UTC) - timedelta(days=2),
        )
    expired_accept = await client.post(
        "/v1/family/invites/accept",
        headers=outsider_headers,
        json={"token": expired.token},
    )
    assert expired_accept.status_code == 410
    assert expired_accept.json()["detail"] == "FAMILY_INVITE_EXPIRED"


@pytest.mark.asyncio
async def test_user_in_another_family_cannot_accept_invite(client):
    first_headers, _ = await _new_user(client, "family-a-owner")
    second_headers, _ = await _new_user(client, "family-b-owner")

    assert (await client.post("/v1/family", headers=first_headers)).status_code == 201
    assert (await client.post("/v1/family", headers=second_headers)).status_code == 201
    invite = await client.post("/v1/family/invites", headers=first_headers)

    response = await client.post(
        "/v1/family/invites/accept",
        headers=second_headers,
        json={"token": invite.json()["token"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "FAMILY_ALREADY_JOINED"


@pytest.mark.asyncio
async def test_default_deny_owner_has_no_bypass_and_only_self_data_can_be_granted(client):
    owner_headers, owner_id = await _new_user(client, "permission-owner")
    alice_headers, alice_id = await _new_user(client, "permission-alice")
    bob_headers, bob_id = await _new_user(client, "permission-bob")

    assert (await client.post("/v1/family", headers=owner_headers)).status_code == 201
    for headers in (alice_headers, bob_headers):
        invite = await client.post("/v1/family/invites", headers=owner_headers)
        accepted = await client.post(
            "/v1/family/invites/accept",
            headers=headers,
            json={"token": invite.json()["token"]},
        )
        assert accepted.status_code == 200

    with SessionLocal() as db:
        assert (
            has_family_permission(
                db,
                resource_owner_user_id=alice_id,
                grantee_user_id=owner_id,
                permission_code=FamilyPermissionCode.VIEW_MEMORY,
            )
            is False
        )
        assert (
            has_family_permission(
                db,
                resource_owner_user_id=alice_id,
                grantee_user_id=bob_id,
                permission_code="UNKNOWN_SCOPE",
            )
            is False
        )

    # OWNER can only grant access to OWNER's own data because resource owner comes from auth.
    owner_grant = await client.put(
        f"/v1/family/permissions/{bob_id}",
        headers=owner_headers,
        json={"permissions": ["VIEW_MEMORY"]},
    )
    assert owner_grant.status_code == 200

    with SessionLocal() as db:
        assert has_family_permission(
            db,
            resource_owner_user_id=owner_id,
            grantee_user_id=bob_id,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )
        assert not has_family_permission(
            db,
            resource_owner_user_id=alice_id,
            grantee_user_id=bob_id,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )

    alice_grant = await client.put(
        f"/v1/family/permissions/{bob_id}",
        headers=alice_headers,
        json={"permissions": ["VIEW_FOOTPRINT", "VIEW_PHOTOS"]},
    )
    assert alice_grant.status_code == 200
    listed = await client.get("/v1/family/permissions", headers=alice_headers)
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "grantee_user_id": str(bob_id),
            "permissions": ["VIEW_FOOTPRINT", "VIEW_PHOTOS"],
        }
    ]

    unknown = await client.put(
        f"/v1/family/permissions/{bob_id}",
        headers=alice_headers,
        json={"permissions": ["ROOT_ALL_DATA"]},
    )
    assert unknown.status_code == 422


@pytest.mark.asyncio
async def test_membership_removal_and_leave_immediately_invalidate_grants(client):
    owner_headers, owner_id = await _new_user(client, "remove-owner")
    member_headers, member_id = await _new_user(client, "remove-member")

    await client.post("/v1/family", headers=owner_headers)
    invite = await client.post("/v1/family/invites", headers=owner_headers)
    await client.post(
        "/v1/family/invites/accept",
        headers=member_headers,
        json={"token": invite.json()["token"]},
    )
    granted = await client.put(
        f"/v1/family/permissions/{member_id}",
        headers=owner_headers,
        json={"permissions": ["VIEW_MEMORY"]},
    )
    assert granted.status_code == 200

    removed = await client.delete(
        f"/v1/family/members/{member_id}",
        headers=owner_headers,
    )
    assert removed.status_code == 204

    with SessionLocal() as db:
        assert not has_family_permission(
            db,
            resource_owner_user_id=owner_id,
            grantee_user_id=member_id,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )
        assert db.scalar(
            select(FamilyMembership.id).where(FamilyMembership.user_id == member_id)
        ) is None
        assert db.scalar(
            select(FamilyPermissionGrant.id).where(
                FamilyPermissionGrant.grantee_user_id == member_id
            )
        ) is None

    owner_leave = await client.delete(
        f"/v1/family/members/{owner_id}",
        headers=owner_headers,
    )
    assert owner_leave.status_code == 409
    assert owner_leave.json()["detail"] == "FAMILY_OWNER_CANNOT_LEAVE"


@pytest.mark.asyncio
async def test_member_can_leave_but_cannot_remove_another_member(client):
    owner_headers, _ = await _new_user(client, "leave-owner")
    first_headers, first_id = await _new_user(client, "leave-first")
    second_headers, second_id = await _new_user(client, "leave-second")
    await client.post("/v1/family", headers=owner_headers)

    for headers in (first_headers, second_headers):
        invite = await client.post("/v1/family/invites", headers=owner_headers)
        await client.post(
            "/v1/family/invites/accept",
            headers=headers,
            json={"token": invite.json()["token"]},
        )

    denied = await client.delete(
        f"/v1/family/members/{second_id}",
        headers=first_headers,
    )
    assert denied.status_code == 403

    left = await client.delete(
        f"/v1/family/members/{first_id}",
        headers=first_headers,
    )
    assert left.status_code == 204


def test_dirty_pending_grant_is_not_authoritative():
    owner_id = uuid4()
    grantee_id = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                User(id=owner_id, nickname="dirty-owner"),
                User(id=grantee_id, nickname="dirty-grantee"),
            ]
        )
        db.commit()
        family = create_family(db, user_id=owner_id)
        membership = FamilyMembership(
            family_id=family.family_id,
            user_id=grantee_id,
            role=FamilyRole.MEMBER.value,
        )
        db.add(membership)
        db.commit()

        pending = FamilyPermissionGrant(
            family_id=family.family_id,
            resource_owner_user_id=owner_id,
            grantee_user_id=grantee_id,
            permission_code=FamilyPermissionCode.VIEW_MEMORY.value,
        )
        db.add(pending)
        assert pending in db.new
        assert not has_family_permission(
            db,
            resource_owner_user_id=owner_id,
            grantee_user_id=grantee_id,
            permission_code=FamilyPermissionCode.VIEW_MEMORY,
        )
        db.rollback()


def test_cross_family_mutation_fails_closed():
    owner_a = uuid4()
    owner_b = uuid4()
    member_b = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                User(id=owner_a, nickname="cross-a"),
                User(id=owner_b, nickname="cross-b"),
                User(id=member_b, nickname="cross-member"),
            ]
        )
        db.commit()
        create_family(db, user_id=owner_a)
        family_b = create_family(db, user_id=owner_b)
        db.add(
            FamilyMembership(
                family_id=family_b.family_id,
                user_id=member_b,
                role=FamilyRole.MEMBER.value,
            )
        )
        db.commit()

        with pytest.raises(FamilyServiceError) as exc:
            replace_permissions(
                db,
                resource_owner_user_id=owner_a,
                grantee_user_id=member_b,
                permission_codes=[FamilyPermissionCode.VIEW_MEMORY.value],
            )
        assert exc.value.code == "FAMILY_MEMBER_NOT_FOUND"
        assert exc.value.status_code == 404


def test_family_router_exposes_only_reviewed_stage4a_and_stage4b_routes():
    # Inspect the family router itself: unrelated tests may temporarily alter global
    # FastAPI app routes, while this invariant is specifically about Stage 4A's surface.
    family_paths = {
        route.path
        for route in family_router.routes
        if isinstance(getattr(route, "path", None), str)
    }
    assert family_paths == {
        "/family",
        "/family/invites",
        "/family/invites/accept",
        "/family/invites/{invite_id}",
        "/family/members/{target_user_id}",
        "/family/permissions",
        "/family/permissions/{grantee_user_id}",
        "/family/members/{resource_owner_user_id}/current-location",
        "/family/members/{resource_owner_user_id}/today/footprint",
    }
    assert all("memory" not in path.lower() for path in family_paths)
    assert all("photo" not in path.lower() for path in family_paths)
