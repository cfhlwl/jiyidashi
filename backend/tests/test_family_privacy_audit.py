from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.family_models import (
    FamilyAccessAuditEvent,
    FamilyAuditAction,
    FamilyAuditResult,
    FamilyPermissionCode,
)
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import LocationPoint
from app.services.family_sensitive_read_service import (
    FamilySensitiveReadError,
    sign_family_photo_download,
)
from app.services.object_storage import PresignedTransfer


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


async def _grant(client, owner_headers, member_id: UUID, *codes: str):
    response = await client.put(
        f"/v1/family/permissions/{member_id}",
        headers=owner_headers,
        json={"permissions": list(codes)},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_family_audit_tracks_allowed_denied_unavailable_without_payload_leak(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "audit-outcomes"
    )

    denied = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert denied.status_code == 403

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_MEMORY.value,
        FamilyPermissionCode.VIEW_CURRENT_LOCATION.value,
        FamilyPermissionCode.VIEW_FOOTPRINT.value,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )

    memory = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert memory.status_code == 200

    footprint = await client.get(
        f"/v1/family/members/{owner_id}/today/footprint",
        headers=member_headers,
    )
    assert footprint.status_code == 200

    unavailable = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert unavailable.status_code == 404
    assert unavailable.json()["detail"] == "CURRENT_LOCATION_UNAVAILABLE"

    now = datetime.now(UTC).replace(microsecond=0)
    with SessionLocal() as db:
        db.add(
            LocationPoint(
                user_id=owner_id,
                client_uuid=f"audit-{uuid4().hex}",
                latitude=39.9042,
                longitude=116.4074,
                accuracy=8.0,
                speed=None,
                recorded_at=now,
            )
        )
        db.commit()

    location = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert location.status_code == 200

    photos = await client.get(
        f"/v1/family/members/{owner_id}/photos",
        headers=member_headers,
    )
    assert photos.status_code == 200

    audit = await client.get("/v1/family/audit", headers=owner_headers)
    assert audit.status_code == 200
    rows = audit.json()
    assert len(rows) >= 6
    assert all(
        set(row)
        == {
            "event_id",
            "actor_user_id",
            "resource_owner_user_id",
            "authority_type",
            "permission_code",
            "resource_type",
            "action",
            "result",
            "created_at",
        }
        for row in rows
    )
    assert all(row["authority_type"] == "EXACT_GRANT" for row in rows)
    assert all(row["actor_user_id"] == str(member_id) for row in rows)
    assert all(row["resource_owner_user_id"] == str(owner_id) for row in rows)

    outcomes = {(row["action"], row["result"]) for row in rows}
    assert (
        FamilyAuditAction.READ_MEMORY.value,
        FamilyAuditResult.DENIED.value,
    ) in outcomes
    assert (
        FamilyAuditAction.READ_MEMORY.value,
        FamilyAuditResult.ALLOWED.value,
    ) in outcomes
    assert (
        FamilyAuditAction.READ_TODAY_FOOTPRINT.value,
        FamilyAuditResult.ALLOWED.value,
    ) in outcomes
    assert (
        FamilyAuditAction.READ_CURRENT_LOCATION.value,
        FamilyAuditResult.UNAVAILABLE.value,
    ) in outcomes
    assert (
        FamilyAuditAction.READ_CURRENT_LOCATION.value,
        FamilyAuditResult.ALLOWED.value,
    ) in outcomes
    assert (
        FamilyAuditAction.LIST_PHOTOS.value,
        FamilyAuditResult.ALLOWED.value,
    ) in outcomes

    serialized = str(rows).lower()
    for forbidden in (
        "latitude",
        "longitude",
        "memory content",
        "signed",
        "object_key",
        "storage",
        "ocr",
        "exif",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_family_audit_is_owner_only_bounded_ordered_and_30_day_scoped(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "audit-query"
    )

    member = await client.get("/v1/family/audit", headers=member_headers)
    assert member.status_code == 403
    assert member.json()["detail"] == "OWNER_REQUIRED"

    # Seed through real denied reads so family_id is authoritative.
    denied = await client.get(
        f"/v1/family/members/{owner_id}/memories",
        headers=member_headers,
    )
    assert denied.status_code == 403

    with SessionLocal() as db:
        family_id = db.scalar(
            select(FamilyAccessAuditEvent.family_id).where(
                FamilyAccessAuditEvent.resource_owner_user_id == owner_id
            )
        )
        assert family_id is not None
        now = datetime.now(UTC)
        for index in range(55):
            db.add(
                FamilyAccessAuditEvent(
                    id=UUID(int=10_000 + index),
                    family_id=family_id,
                    actor_user_id=member_id,
                    resource_owner_user_id=owner_id,
                    permission_code=FamilyPermissionCode.VIEW_MEMORY.value,
                    resource_type="MEMORY",
                    action="READ_MEMORY",
                    result="DENIED",
                    created_at=now - timedelta(minutes=index),
                )
            )
        db.add(
            FamilyAccessAuditEvent(
                family_id=family_id,
                actor_user_id=member_id,
                resource_owner_user_id=owner_id,
                permission_code=FamilyPermissionCode.VIEW_MEMORY.value,
                resource_type="MEMORY",
                action="READ_MEMORY",
                result="DENIED",
                created_at=now - timedelta(days=31),
            )
        )
        db.commit()

    response = await client.get("/v1/family/audit?limit=50", headers=owner_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 50
    keys = [(row["created_at"], row["event_id"]) for row in body]
    assert keys == sorted(keys, reverse=True)
    for row in body:
        created_at = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        assert created_at >= datetime.now(UTC) - timedelta(days=30, minutes=1)

    invalid = await client.get("/v1/family/audit?limit=51", headers=owner_headers)
    assert invalid.status_code == 422



class _AuditPhotoStorage:
    def sign_download(self, object_key: str) -> PresignedTransfer:
        return PresignedTransfer(
            method="GET",
            url=f"https://audit-photo.test/{object_key}?temporary=1",
            headers={},
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


@pytest.mark.asyncio
async def test_photo_download_is_separate_audit_and_content_delete_keeps_history(client):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "audit-photo-download"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )
    media_id = uuid4()
    with SessionLocal() as db:
        db.add(
            MediaAsset(
                id=media_id,
                user_id=owner_id,
                client_upload_id=uuid4(),
                kind=MediaKind.IMAGE,
                status=MediaStatus.READY,
                upload_object_key=f"staging/{owner_id}/{media_id.hex}",
                object_key=f"final/{owner_id}/{media_id.hex}",
                content_type="image/jpeg",
                size_bytes=2048,
                original_filename="private.jpg",
                storage_etag="private-etag",
                created_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()

    with SessionLocal() as db:
        transfer = sign_family_photo_download(
            db,
            resource_owner_user_id=owner_id,
            grantee_user_id=member_id,
            media_id=media_id,
            storage=_AuditPhotoStorage(),
        )
        assert transfer.method == "GET"

    missing_id = uuid4()
    with SessionLocal() as db:
        with pytest.raises(FamilySensitiveReadError) as unavailable:
            sign_family_photo_download(
                db,
                resource_owner_user_id=owner_id,
                grantee_user_id=member_id,
                media_id=missing_id,
                storage=_AuditPhotoStorage(),
            )
        assert unavailable.value.code == "FAMILY_PHOTO_UNAVAILABLE"

    with SessionLocal() as db:
        rows = db.scalars(
            select(FamilyAccessAuditEvent).where(
                FamilyAccessAuditEvent.resource_owner_user_id == owner_id,
                FamilyAccessAuditEvent.action
                == FamilyAuditAction.DOWNLOAD_PHOTO.value,
            )
        ).all()
        assert sorted(row.result for row in rows) == [
            FamilyAuditResult.ALLOWED.value,
            FamilyAuditResult.UNAVAILABLE.value,
        ]

        asset = db.get(MediaAsset, media_id)
        assert asset is not None
        db.delete(asset)
        db.commit()

    # Audit is access metadata, not a child of the photo. Ordinary content deletion
    # must not erase the privacy history.
    with SessionLocal() as db:
        assert db.scalar(
            select(FamilyAccessAuditEvent.id).where(
                FamilyAccessAuditEvent.resource_owner_user_id == owner_id,
                FamilyAccessAuditEvent.action
                == FamilyAuditAction.DOWNLOAD_PHOTO.value,
                FamilyAccessAuditEvent.result == FamilyAuditResult.ALLOWED.value,
            )
        ) is not None

