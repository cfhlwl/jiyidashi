import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.api import data_export as export_api
from app.core.db import SessionLocal
from app.media_models import MediaAsset, MediaEvidenceLink, MediaKind, MediaStatus
from app.models import (
    Memory,
    MemorySource,
    MemoryType,
    ObjectItem,
    ObjectLocation,
    ObjectLocationStatus,
    PrivacyPauseInterval,
    PrivacyState,
    Reminder,
    ReminderStatus,
    SourceType,
    User,
)


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


@pytest.mark.asyncio
async def test_data_export_requires_authentication(client):
    # [人工注释][S1-020] 导出没有匿名模式；缺少 Bearer token 必须在读取任何个人数据前被拒绝。
    response = await client.get("/v1/export/data")
    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_empty_account_exports_versioned_json(client, auth_headers):
    # [人工注释][S1-020] 空账号也是合法导出，格式版本和所有集合必须稳定存在，客户端无需猜字段。
    response = await client.get("/v1/export/data", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["format"] == "jiyidashi.user-export.v1"
    assert body["profile"]["elder_mode_enabled"] is False
    assert body["memories"] == []
    assert body["memory_sources"] == []
    assert body["memory_edits"] == []
    assert body["people"] == []
    assert body["person_relationships"] == []
    assert body["person_memory_links"] == []
    assert body["objects"] == []
    assert body["object_locations"] == []
    assert body["location"]["points"] == []
    assert body["location"]["visits"] == []
    assert body["location"]["places"] == []
    assert body["location"]["place_name_corrections"] == []
    assert body["location"]["finalized_through"] is None
    assert body["reminders"] == []
    assert body["privacy"]["pause_intervals"] == []
    assert body["media"]["assets"] == []
    assert body["media"]["evidence_links"] == []
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].endswith('.json"')


@pytest.mark.asyncio
async def test_export_is_owner_scoped_complete_and_storage_safe(client):
    # [人工注释][S1-020] 同库构造 A/B 两个用户，导出 A 时同时验证 owner 隔离、Evidence 关联、
    # ObjectLocation 历史状态以及媒体内部存储字段不会穿透公开 JSON。
    headers_a, user_a = await _new_user(client, "Export A")
    _, user_b = await _new_user(client, "Export B")
    now = datetime.now(UTC)

    with SessionLocal() as db:
        user = db.get(User, user_a)
        assert user is not None
        user.email = "a@example.com"
        user.timezone = "Asia/Singapore"
        user.elder_mode_enabled = True

        memory_a = Memory(
            user_id=user_a,
            memory_type=MemoryType.PHOTO,
            title="A title",
            content="A visible memory",
            occurred_at=now,
            source_type=SourceType.USER_PHOTO,
            confidence=1.0,
            is_confirmed=True,
        )
        deleted_a = Memory(
            user_id=user_a,
            memory_type=MemoryType.NOTE,
            content="A deleted secret",
            occurred_at=now,
            source_type=SourceType.USER_TEXT,
            confidence=1.0,
            is_confirmed=True,
            is_deleted=True,
        )
        memory_b = Memory(
            user_id=user_b,
            memory_type=MemoryType.NOTE,
            content="B private memory",
            occurred_at=now,
            source_type=SourceType.USER_TEXT,
            confidence=1.0,
            is_confirmed=True,
        )
        db.add_all([memory_a, deleted_a, memory_b])
        db.flush()

        source_a = MemorySource(
            memory_id=memory_a.id,
            source_type=SourceType.USER_PHOTO,
            source_id="media-a",
            raw_text="A evidence",
            confidence=1.0,
        )
        source_deleted = MemorySource(
            memory_id=deleted_a.id,
            source_type=SourceType.USER_TEXT,
            raw_text="deleted evidence",
            confidence=1.0,
        )
        source_b = MemorySource(
            memory_id=memory_b.id,
            source_type=SourceType.USER_TEXT,
            raw_text="B evidence",
            confidence=1.0,
        )
        db.add_all([source_a, source_deleted, source_b])
        db.flush()

        object_a = ObjectItem(
            user_id=user_a,
            name="护照",
            normalized_name="护照",
        )
        object_b = ObjectItem(
            user_id=user_b,
            name="B object",
            normalized_name="b object",
        )
        db.add_all([object_a, object_b])
        db.flush()
        db.add_all(
            [
                ObjectLocation(
                    object_id=object_a.id,
                    user_id=user_a,
                    location_text="旧抽屉",
                    recorded_at=now - timedelta(days=1),
                    confidence=1.0,
                    status=ObjectLocationStatus.STALE,
                ),
                ObjectLocation(
                    object_id=object_a.id,
                    user_id=user_a,
                    memory_id=memory_a.id,
                    location_text="书房柜子",
                    recorded_at=now,
                    confidence=1.0,
                    status=ObjectLocationStatus.CURRENT,
                ),
                ObjectLocation(
                    object_id=object_b.id,
                    user_id=user_b,
                    location_text="B location",
                    recorded_at=now,
                    confidence=1.0,
                    status=ObjectLocationStatus.CURRENT,
                ),
            ]
        )
        db.add_all(
            [
                Reminder(
                    user_id=user_a,
                    memory_id=memory_a.id,
                    title="A reminder",
                    content="A reminder note",
                    remind_at=now + timedelta(hours=2),
                    status=ReminderStatus.PENDING,
                ),
                Reminder(
                    user_id=user_b,
                    memory_id=memory_b.id,
                    title="B reminder",
                    content="B reminder secret",
                    remind_at=now + timedelta(hours=3),
                    status=ReminderStatus.PENDING,
                ),
            ]
        )
        db.add(
            PrivacyState(
                user_id=user_a,
                recording_paused_since=now - timedelta(minutes=30),
                recording_paused_until=now + timedelta(minutes=30),
            )
        )
        db.add(
            PrivacyPauseInterval(
                user_id=user_a,
                started_at=now - timedelta(minutes=30),
                ended_at=None,
            )
        )

        media_a = MediaAsset(
            user_id=user_a,
            client_upload_id=uuid4(),
            kind=MediaKind.IMAGE,
            status=MediaStatus.READY,
            upload_object_key="staging/private/a.jpg",
            object_key="final/private/a.jpg",
            content_type="image/jpeg",
            size_bytes=1234,
            original_filename="photo.jpg",
            storage_etag="super-secret-etag",
            completed_at=now,
        )
        media_b = MediaAsset(
            user_id=user_b,
            client_upload_id=uuid4(),
            kind=MediaKind.IMAGE,
            status=MediaStatus.READY,
            upload_object_key="staging/private/b.jpg",
            object_key="final/private/b.jpg",
            content_type="image/jpeg",
            size_bytes=987,
            storage_etag="b-etag",
            completed_at=now,
        )
        db.add_all([media_a, media_b])
        db.flush()
        db.add(MediaEvidenceLink(media_id=media_a.id, memory_source_id=source_a.id))
        source_a_id = source_a.id
        db.commit()

    # [人工注释][S1-020] 即使调用方附带伪造 user_id query，
    # owner 仍只能来自 token，参数不得改变导出归属。
    response = await client.get(
        f"/v1/export/data?user_id={user_b}",
        headers=headers_a,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["profile"]["id"] == str(user_a)
    assert body["profile"]["timezone"] == "Asia/Singapore"
    assert body["profile"]["elder_mode_enabled"] is True
    assert [item["content"] for item in body["memories"]] == ["A visible memory"]
    assert [item["raw_text"] for item in body["memory_sources"]] == ["A evidence"]
    assert [item["name"] for item in body["objects"]] == ["护照"]
    assert [item["status"] for item in body["object_locations"]] == ["STALE", "CURRENT"]
    assert [item["title"] for item in body["reminders"]] == ["A reminder"]
    assert body["reminders"][0]["status"] == "PENDING"
    assert len(body["privacy"]["pause_intervals"]) == 1
    assert len(body["media"]["assets"]) == 1
    assert len(body["media"]["evidence_links"]) == 1
    assert body["media"]["evidence_links"][0]["memory_source_id"] == str(source_a_id)

    encoded = json.dumps(body, ensure_ascii=False)
    for forbidden in (
        "staging/private/a.jpg",
        "final/private/a.jpg",
        "super-secret-etag",
        "B private memory",
        "B evidence",
        "B location",
        "B reminder secret",
        "A deleted secret",
        "deleted evidence",
    ):
        assert forbidden not in encoded


@pytest.mark.asyncio
async def test_deleted_backing_memory_redacts_location_fact_in_export(client):
    # [人工注释][S1-020] 回归必须走真实 Object -> Location -> DELETE Memory -> Export 链路；
    # 已删除 backing Memory 只允许留下脱敏的 STALE 历史，不能把 location_text 通过导出重新复活。
    headers, _ = await _new_user(client, "Export delete location")
    now = datetime.now(UTC)

    object_response = await client.post(
        "/v1/objects",
        headers=headers,
        json={"name": "护照"},
    )
    assert object_response.status_code == 201
    object_id = object_response.json()["id"]

    old_location_response = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=headers,
        json={
            "location_text": "旧抽屉",
            "recorded_at": (now - timedelta(days=1)).isoformat(),
            "capture_source": "USER_TEXT",
        },
    )
    assert old_location_response.status_code == 201
    old_location = old_location_response.json()

    deleted_location_response = await client.post(
        f"/v1/objects/{object_id}/locations",
        headers=headers,
        json={
            "location_text": "书房抽屉",
            "recorded_at": now.isoformat(),
            "capture_source": "USER_TEXT",
        },
    )
    assert deleted_location_response.status_code == 201
    deleted_location = deleted_location_response.json()
    deleted_memory_id = deleted_location["memory_id"]
    assert deleted_memory_id is not None

    delete_response = await client.delete(
        f"/v1/memories/{deleted_memory_id}",
        headers=headers,
    )
    assert delete_response.status_code == 204

    export_response = await client.get("/v1/export/data", headers=headers)
    assert export_response.status_code == 200
    body = export_response.json()

    exported_locations = {item["id"]: item for item in body["object_locations"]}
    normal_history = exported_locations[old_location["id"]]
    redacted_history = exported_locations[deleted_location["id"]]

    # [人工注释][S1-020] 未删除 backing Memory 的正常历史仍完整可导出，
    # 证明修复没有把所有 STALE 行误删。
    assert normal_history["status"] == "STALE"
    assert normal_history["location_text"] == "旧抽屉"
    assert normal_history["confidence"] == 1.0
    assert normal_history["redacted"] is False
    assert normal_history["redaction_reason"] is None

    assert redacted_history["status"] == "STALE"
    assert redacted_history["memory_id"] is None
    assert redacted_history["location_text"] is None
    assert redacted_history["place_id"] is None
    assert redacted_history["confidence"] is None
    assert redacted_history["redacted"] is True
    assert redacted_history["redaction_reason"] == "BACKING_MEMORY_DELETED"

    assert deleted_memory_id not in {item["id"] for item in body["memories"]}
    assert deleted_memory_id not in {
        item["memory_id"] for item in body["memory_sources"]
    }
    assert "护照放在旧抽屉" in {item["content"] for item in body["memories"]}

    encoded = json.dumps(body, ensure_ascii=False)
    assert "书房抽屉" not in encoded
    assert "护照放在书房抽屉" not in encoded


@pytest.mark.asyncio
async def test_export_fails_closed_when_v1_section_limit_is_exceeded(
    client,
    auth_headers,
    monkeypatch,
):
    # [人工注释][S1-020] V1 大账号策略是显式上限而不是静默截断；超限必须整体失败，
    # 避免用户误以为拿到了完整备份。
    profile_response = await client.get("/v1/user", headers=auth_headers)
    assert profile_response.status_code == 200
    user_id = UUID(profile_response.json()["id"])
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add_all(
            [
                PrivacyPauseInterval(
                    user_id=user_id,
                    started_at=now - timedelta(minutes=2),
                    ended_at=now - timedelta(minutes=1),
                ),
                PrivacyPauseInterval(
                    user_id=user_id,
                    started_at=now - timedelta(minutes=1),
                    ended_at=now,
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(export_api, "EXPORT_MAX_ROWS_PER_SECTION", 1)
    response = await client.get("/v1/export/data", headers=auth_headers)
    assert response.status_code == 413
    assert response.json()["detail"] == "EXPORT_SECTION_TOO_LARGE:privacy_pause_intervals"


@pytest.mark.asyncio
async def test_export_includes_owner_scoped_location_history(client):
    headers_a, _ = await _new_user(client, "Export location A")
    headers_b, _ = await _new_user(client, "Export location B")
    started = datetime.now(UTC) - timedelta(minutes=20)

    def points(prefix: str):
        return [
            {
                "client_uuid": f"{prefix}-{index}",
                "latitude": 31.2304 + index * 0.00003,
                "longitude": 121.4737 + index * 0.00003,
                "recorded_at": (started + timedelta(minutes=index * 5)).isoformat(),
            }
            for index in range(3)
        ]

    assert (
        await client.post(
            "/v1/location/batch",
            headers=headers_a,
            json={"points": points("export-a")},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/v1/location/batch",
            headers=headers_b,
            json={"points": points("export-b")},
        )
    ).status_code == 200

    response = await client.get("/v1/export/data", headers=headers_a)
    assert response.status_code == 200
    location = response.json()["location"]
    assert [item["client_uuid"] for item in location["points"]] == [
        "export-a-0",
        "export-a-1",
        "export-a-2",
    ]
    assert len(location["visits"]) == 1
    assert location["visits"][0]["source_point_count"] == 3
    assert len(location["visits"][0]["source_fingerprint"]) == 64
    assert len(location["places"]) == 1
    assert location["places"][0]["name"] == "未命名地点"
    assert location["finalized_through"] is not None
    assert "export-b" not in json.dumps(location, ensure_ascii=False)
