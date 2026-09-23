from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.db import SessionLocal
from app.family_models import (
    FamilyMembership,
    FamilyPermissionCode,
    FamilyPermissionGrant,
    FamilyRole,
)
from app.models import Memory, MemoryType, SourceType, User
from app.services import family_sensitive_read_service
from app.services.family_sensitive_read_service import (
    FamilySensitiveReadError,
    get_family_memories,
)
from app.services.family_service import create_family


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


def _memory(
    *,
    user_id: UUID,
    memory_id: UUID,
    occurred_at: datetime,
    title: str,
    content: str,
    deleted: bool = False,
) -> Memory:
    return Memory(
        id=memory_id,
        user_id=user_id,
        memory_type=MemoryType.NOTE,
        title=title,
        content=content,
        occurred_at=occurred_at,
        source_type=SourceType.USER_TEXT,
        confidence=0.42,
        latitude=31.2304,
        longitude=121.4737,
        is_confirmed=True,
        is_deleted=deleted,
        metadata_json={
            "private": "must-not-leak",
            "storage_url": "https://example.invalid/private",
        },
        edit_revision=3,
        created_at=occurred_at - timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_family_memory_requires_exact_view_memory_and_owner_role_never_bypasses(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "memory-auth"
    )
    _, _, outsider_headers, _ = await _family_pair(client, "memory-foreign")

    missing = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert missing.status_code == 403
    assert missing.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"

    owner_bypass = await client.get(
        f"/v1/family/members/{member_id}/memories",
        headers=owner_headers,
    )
    assert owner_bypass.status_code == 403

    self_read = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=owner_headers,
    )
    assert self_read.status_code == 409
    assert self_read.json()["detail"] == "FAMILY_SELF_READ_NOT_APPLICABLE"

    cross_family = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=outsider_headers,
    )
    assert cross_family.status_code == 403
    assert cross_family.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )
    photos_only = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert photos_only.status_code == 403

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_MEMORY.value,
    )
    allowed = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert allowed.status_code == 200
    assert allowed.json() == []


@pytest.mark.asyncio
async def test_family_memory_projection_scope_order_limit_and_deleted_filter(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "memory-projection"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_MEMORY.value,
    )

    occurred = datetime.now(UTC).replace(microsecond=0)
    ids = [UUID(int=101), UUID(int=102), UUID(int=103)]
    with SessionLocal() as db:
        db.add_all(
            [
                _memory(
                    user_id=owner_id,
                    memory_id=ids[0],
                    occurred_at=occurred,
                    title="owner-low",
                    content="owner content low",
                ),
                _memory(
                    user_id=owner_id,
                    memory_id=ids[1],
                    occurred_at=occurred,
                    title="owner-middle",
                    content="owner content middle",
                ),
                _memory(
                    user_id=owner_id,
                    memory_id=ids[2],
                    occurred_at=occurred,
                    title="owner-high",
                    content="owner content high",
                ),
                _memory(
                    user_id=owner_id,
                    memory_id=UUID(int=999),
                    occurred_at=occurred + timedelta(days=1),
                    title="deleted",
                    content="must disappear",
                    deleted=True,
                ),
                _memory(
                    user_id=member_id,
                    memory_id=UUID(int=1000),
                    occurred_at=occurred + timedelta(days=2),
                    title="grantee-private",
                    content="must not cross owner scope",
                ),
            ]
        )
        db.commit()

    response = await client.get(
        f"/v1/family/members/{owner_id}/memories?limit=2",
        headers=member_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert [row["memory_id"] for row in body] == [str(ids[2]), str(ids[1])]
    assert all(
        set(row)
        == {
            "memory_id",
            "memory_type",
            "title",
            "content",
            "occurred_at",
            "source_type",
            "is_confirmed",
            "edit_revision",
            "created_at",
        }
        for row in body
    )
    assert all("metadata_json" not in row for row in body)
    assert all("latitude" not in row and "longitude" not in row for row in body)
    assert all("confidence" not in row and "place_id" not in row for row in body)
    assert all("source_id" not in row and "memory_source_id" not in row for row in body)
    assert all("storage_url" not in str(row) for row in body)

    invalid_limit = await client.get(
        f"/v1/family/members/{owner_id}/memories?limit=51",
        headers=member_headers,
    )
    assert invalid_limit.status_code == 422

    with SessionLocal() as db:
        first = db.get(Memory, ids[2])
        assert first is not None
        first.is_deleted = True
        db.commit()

    after_delete = await client.get(
        f"/v1/family/members/{owner_id}/memories?limit=50",
        headers=member_headers,
    )
    assert after_delete.status_code == 200
    assert str(ids[2]) not in {row["memory_id"] for row in after_delete.json()}


@pytest.mark.asyncio
async def test_family_memory_revoke_and_membership_removal_fail_closed(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "memory-lifecycle"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_MEMORY.value,
    )

    granted = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert granted.status_code == 200

    await _grant(client, owner_headers, member_id)
    revoked = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert revoked.status_code == 403

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_MEMORY.value,
    )
    removed = await client.delete(
        f"/v1/family/members/{member_id}",
        headers=owner_headers,
    )
    assert removed.status_code == 204
    after_removal = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert after_removal.status_code == 403


def test_family_memory_pending_grant_is_not_authority_and_has_no_ai_widening():
    owner_id = uuid4()
    member_id = uuid4()
    with SessionLocal() as db:
        db.add_all(
            [
                User(id=owner_id, nickname="pending-memory-owner"),
                User(id=member_id, nickname="pending-memory-member"),
            ]
        )
        db.commit()
        family = create_family(db, user_id=owner_id)
        db.add(
            FamilyMembership(
                family_id=family.family_id,
                user_id=member_id,
                role=FamilyRole.MEMBER.value,
            )
        )
        db.commit()

        db.add(
            FamilyPermissionGrant(
                family_id=family.family_id,
                resource_owner_user_id=owner_id,
                grantee_user_id=member_id,
                permission_code=FamilyPermissionCode.VIEW_MEMORY.value,
            )
        )
        with pytest.raises(FamilySensitiveReadError) as denied:
            get_family_memories(
                db,
                resource_owner_user_id=owner_id,
                grantee_user_id=member_id,
            )
        assert denied.value.code == "FAMILY_READ_NOT_AUTHORIZED"

    source = inspect.getsource(family_sensitive_read_service.get_family_memories)
    for forbidden in (
        "query_memory(",
        "summarize_today(",
        "summarize_month(",
        "summarize_year(",
        "metadata_json",
        "MemorySource",
    ):
        assert forbidden not in source
