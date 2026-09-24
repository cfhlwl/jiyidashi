from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.db import SessionLocal
from app.family_models import FamilyPermissionCode
from app.main import app
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.services.object_storage import PresignedTransfer, get_object_storage


class FakeFamilyPhotoStorage:
    def __init__(self) -> None:
        self.download_keys: list[str] = []

    def sign_download(self, object_key: str) -> PresignedTransfer:
        self.download_keys.append(object_key)
        return PresignedTransfer(
            method="GET",
            url=f"https://private-storage.test/family/{object_key}?temporary=1",
            headers={"X-Test-Capability": "short-lived"},
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )


@pytest.fixture
def family_photo_storage():
    storage = FakeFamilyPhotoStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_object_storage, None)


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


def _asset(
    *,
    user_id: UUID,
    kind: MediaKind = MediaKind.IMAGE,
    status: MediaStatus = MediaStatus.READY,
    created_at: datetime | None = None,
    media_id: UUID | None = None,
) -> MediaAsset:
    asset_id = media_id or uuid4()
    suffix = asset_id.hex
    return MediaAsset(
        id=asset_id,
        user_id=user_id,
        client_upload_id=uuid4(),
        kind=kind,
        status=status,
        upload_object_key=f"staging/{user_id}/{suffix}",
        object_key=f"final/{user_id}/{suffix}",
        content_type="image/jpeg" if kind == MediaKind.IMAGE else "audio/mpeg",
        size_bytes=2048,
        original_filename="private-name.jpg",
        storage_etag="private-etag",
        created_at=created_at or datetime.now(UTC),
        completed_at=datetime.now(UTC) if status == MediaStatus.READY else None,
    )


@pytest.mark.asyncio
async def test_family_photos_require_exact_grant_no_owner_bypass_self_or_cross_family(
    client,
):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-photos-auth"
    )
    _, _, outsider_headers, _ = await _family_pair(client, "family-photos-outsider")

    with SessionLocal() as db:
        db.add(_asset(user_id=owner_id))
        db.commit()

    route = f"/v1/family/members/{owner_id}/photos"

    no_grant = await client.get(route, headers=member_headers)
    assert no_grant.status_code == 403
    assert no_grant.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"

    owner_bypass = await client.get(
        f"/v1/family/members/{member_id}/photos",
        headers=owner_headers,
    )
    assert owner_bypass.status_code == 403

    self_read = await client.get(route, headers=owner_headers)
    assert self_read.status_code == 409
    assert self_read.json()["detail"] == "FAMILY_SELF_READ_NOT_APPLICABLE"

    cross_family = await client.get(route, headers=outsider_headers)
    assert cross_family.status_code == 403
    assert cross_family.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_MEMORY.value,
    )
    memory_only = await client.get(route, headers=member_headers)
    assert memory_only.status_code == 403

    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )
    allowed = await client.get(route, headers=member_headers)
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1

    # VIEW_PHOTOS never widens another Family sensitive permission.
    location = await client.get(
        f"/v1/family/members/{owner_id}/current-location",
        headers=member_headers,
    )
    assert location.status_code == 403


@pytest.mark.asyncio
async def test_family_photo_inventory_is_owner_ready_image_bounded_ordered_and_whitelisted(
    client,
):
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-photos-list"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )

    base = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    expected: list[tuple[datetime, UUID]] = []
    with SessionLocal() as db:
        for index in range(55):
            media_id = UUID(int=1000 + index)
            created_at = base + timedelta(minutes=index // 2)
            expected.append((created_at, media_id))
            db.add(
                _asset(
                    user_id=owner_id,
                    created_at=created_at,
                    media_id=media_id,
                )
            )

        # Hidden by kind/status/owner.
        db.add(_asset(user_id=owner_id, status=MediaStatus.PENDING))
        db.add(_asset(user_id=owner_id, kind=MediaKind.AUDIO))
        db.add(_asset(user_id=member_id))
        db.commit()

    response = await client.get(
        f"/v1/family/members/{owner_id}/photos",
        headers=member_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 50

    expected_ids = [
        str(media_id)
        for _, media_id in sorted(
            expected,
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )[:50]
    ]
    assert [item["media_id"] for item in body] == expected_ids

    for item in body:
        assert set(item) == {
            "media_id",
            "content_type",
            "size_bytes",
            "created_at",
            "completed_at",
        }
        assert item["content_type"] == "image/jpeg"
        for forbidden in (
            "object_key",
            "upload_object_key",
            "storage_etag",
            "client_upload_id",
            "original_filename",
            "user_id",
            "kind",
            "status",
            "metadata",
            "ocr",
            "vision",
            "exif",
        ):
            assert forbidden not in item


@pytest.mark.asyncio
async def test_family_photo_signing_reauthorizes_and_validates_before_storage(
    client,
    family_photo_storage,
):
    storage = family_photo_storage
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-photos-sign"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )

    with SessionLocal() as db:
        ready = _asset(user_id=owner_id)
        pending = _asset(user_id=owner_id, status=MediaStatus.PENDING)
        audio = _asset(user_id=owner_id, kind=MediaKind.AUDIO)
        foreign = _asset(user_id=member_id)
        db.add_all([ready, pending, audio, foreign])
        db.commit()
        ready_id = ready.id
        ready_key = ready.object_key
        pending_id = pending.id
        audio_id = audio.id
        foreign_id = foreign.id

    prefix = f"/v1/family/members/{owner_id}/photos"
    signed = await client.post(
        f"{prefix}/{ready_id}/download",
        headers=member_headers,
    )
    assert signed.status_code == 200
    body = signed.json()
    assert set(body) == {"media_id", "download"}
    assert body["media_id"] == str(ready_id)
    assert set(body["download"]) == {"method", "url", "headers", "expires_at"}
    assert body["download"]["method"] == "GET"
    assert body["download"]["url"].startswith("https://private-storage.test/")
    assert storage.download_keys == [ready_key]

    # Invalid media state/ownership fails before the storage signer sees a key.
    for media_id in (pending_id, audio_id, foreign_id, uuid4()):
        denied = await client.post(
            f"{prefix}/{media_id}/download",
            headers=member_headers,
        )
        assert denied.status_code == 404
        assert denied.json()["detail"] == "FAMILY_PHOTO_UNAVAILABLE"
    assert storage.download_keys == [ready_key]

    # Loading the album does not create a capability. Revocation after list load must
    # block a later sign attempt and must not call storage.
    listed = await client.get(prefix, headers=member_headers)
    assert listed.status_code == 200
    await _grant(client, owner_headers, member_id)
    after_revoke = await client.post(
        f"{prefix}/{ready_id}/download",
        headers=member_headers,
    )
    assert after_revoke.status_code == 403
    assert after_revoke.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"
    assert storage.download_keys == [ready_key]

    # Restore, list again, then remove membership: signing fails closed the same way.
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )
    assert (await client.get(prefix, headers=member_headers)).status_code == 200
    removed = await client.delete(
        f"/v1/family/members/{member_id}",
        headers=owner_headers,
    )
    assert removed.status_code == 204
    after_remove = await client.post(
        f"{prefix}/{ready_id}/download",
        headers=member_headers,
    )
    assert after_remove.status_code == 403
    assert after_remove.json()["detail"] == "FAMILY_READ_NOT_AUTHORIZED"
    assert storage.download_keys == [ready_key]


@pytest.mark.asyncio
async def test_family_photo_path_does_not_invoke_ocr_or_vision(
    client,
    family_photo_storage,
    monkeypatch,
):
    storage = family_photo_storage
    owner_headers, owner_id, member_headers, member_id = await _family_pair(
        client, "family-photos-no-ai"
    )
    await _grant(
        client,
        owner_headers,
        member_id,
        FamilyPermissionCode.VIEW_PHOTOS.value,
    )
    with SessionLocal() as db:
        asset = _asset(user_id=owner_id)
        db.add(asset)
        db.commit()
        media_id = asset.id

    import app.services.ocr_service as ocr_service
    import app.services.vision_service as vision_service

    monkeypatch.setattr(
        ocr_service,
        "extract_ocr",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OCR called")),
    )
    monkeypatch.setattr(
        vision_service,
        "observe_vision",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Vision called")),
    )

    route = f"/v1/family/members/{owner_id}/photos"
    listed = await client.get(route, headers=member_headers)
    assert listed.status_code == 200
    signed = await client.post(
        f"{route}/{media_id}/download",
        headers=member_headers,
    )
    assert signed.status_code == 200
    assert len(storage.download_keys) == 1
