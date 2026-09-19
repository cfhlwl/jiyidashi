from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.media_models import MediaAsset, MediaEvidenceLink, MediaKind, MediaStatus
from app.models import Memory, MemoryEdit, MemorySource, MemoryType, SourceType


async def _current_user_id(client, headers: dict[str, str]) -> UUID:
    profile = await client.get("/v1/user", headers=headers)
    assert profile.status_code == 200
    return UUID(profile.json()["id"])


@pytest.mark.asyncio
async def test_content_edit_preserves_original_source_and_uses_edit_evidence(
    client,
    auth_headers,
):
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"title": "旧标题", "content": "红色文件袋放在桌上"},
    )
    assert created.status_code == 201
    memory_id = UUID(created.json()["id"])

    with SessionLocal() as db:
        original = db.scalar(
            select(MemorySource).where(MemorySource.memory_id == memory_id)
        )
        assert original is not None
        original_source_id = original.id
        assert original.raw_text == "红色文件袋放在桌上"

    edited = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={
            "expected_revision": 0,
            "title": "合同位置",
            "content": "合同已经放入蓝色柜子",
        },
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["title"] == "合同位置"
    assert body["content"] == "合同已经放入蓝色柜子"
    assert body["edit_revision"] == 1
    assert body["edited_at"] is not None
    assert body["source_type"] == "USER_TEXT"
    assert body["confidence"] == 1.0
    assert body["is_confirmed"] is True

    with SessionLocal() as db:
        sources = db.scalars(
            select(MemorySource)
            .where(MemorySource.memory_id == memory_id)
            .order_by(MemorySource.created_at, MemorySource.id)
        ).all()
        edits = db.scalars(
            select(MemoryEdit)
            .where(MemoryEdit.memory_id == memory_id)
            .order_by(MemoryEdit.revision)
        ).all()
        assert len(sources) == 2
        assert sources[0].id == original_source_id
        assert sources[0].raw_text == "红色文件袋放在桌上"
        assert sources[1].source_type == SourceType.USER_TEXT
        assert sources[1].raw_text == "合同已经放入蓝色柜子"
        assert len(edits) == 1
        assert edits[0].previous_content == "红色文件袋放在桌上"
        assert edits[0].new_content == "合同已经放入蓝色柜子"
        assert edits[0].memory_source_id == sources[1].id
        edit_source_id = sources[1].id

    old_query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "红色文件袋桌上"},
    )
    assert old_query.status_code == 200
    assert old_query.json()["can_answer"] is False

    new_query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "蓝色柜子"},
    )
    assert new_query.status_code == 200
    evidence = new_query.json()["evidence"][0]
    assert evidence["memory_source_id"] == str(edit_source_id)
    assert evidence["provenance"] == "USER_EDIT"
    assert evidence["source_type"] == "USER_TEXT"
    assert evidence["excerpt"] == "合同已经放入蓝色柜子"

    timeline = await client.get("/v1/timeline", headers=auth_headers)
    assert timeline.status_code == 200
    current = next(item for item in timeline.json() if item["id"] == str(memory_id))
    assert current["content"] == "合同已经放入蓝色柜子"
    assert current["edit_revision"] == 1

    exported = await client.get("/v1/export/data", headers=auth_headers)
    assert exported.status_code == 200
    export_body = exported.json()
    exported_memory = next(
        item for item in export_body["memories"] if item["id"] == str(memory_id)
    )
    assert exported_memory["content"] == "合同已经放入蓝色柜子"
    assert exported_memory["edit_revision"] == 1
    audit_rows = [
        item for item in export_body["memory_edits"] if item["memory_id"] == str(memory_id)
    ]
    assert len(audit_rows) == 1
    exported_sources = [
        item for item in export_body["memory_sources"] if item["memory_id"] == str(memory_id)
    ]
    assert {item["raw_text"] for item in exported_sources} == {
        "红色文件袋放在桌上",
        "合同已经放入蓝色柜子",
    }

    # response-loss 后相同 PATCH 重试是自然 no-op，不重复制造 revision/source。
    stale_conflict = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={"expected_revision": 0, "content": "过期页面想覆盖为黄色柜子"},
    )
    assert stale_conflict.status_code == 409
    assert stale_conflict.json()["detail"] == "MEMORY_EDIT_REVISION_CONFLICT"

    retried = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={
            "expected_revision": 0,
            "title": "合同位置",
            "content": "合同已经放入蓝色柜子",
        },
    )
    assert retried.status_code == 200
    assert retried.json()["edit_revision"] == 1

    second = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={"expected_revision": 1, "content": "合同现在放在绿色柜子"},
    )
    assert second.status_code == 200
    assert second.json()["edit_revision"] == 2
    with SessionLocal() as db:
        assert len(
            db.scalars(
                select(MemoryEdit).where(MemoryEdit.memory_id == memory_id)
            ).all()
        ) == 2


@pytest.mark.asyncio
async def test_title_only_edit_does_not_forge_new_content_source(client, auth_headers):
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"title": "原题", "content": "正文保持不变"},
    )
    memory_id = UUID(created.json()["id"])

    edited = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={"expected_revision": 0, "title": "新题"},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "新题"
    assert edited.json()["content"] == "正文保持不变"
    assert edited.json()["edit_revision"] == 1

    with SessionLocal() as db:
        sources = db.scalars(
            select(MemorySource).where(MemorySource.memory_id == memory_id)
        ).all()
        audit = db.scalar(
            select(MemoryEdit).where(MemoryEdit.memory_id == memory_id)
        )
        assert len(sources) == 1
        assert audit is not None
        assert audit.changed_title is True
        assert audit.changed_content is False
        assert audit.memory_source_id is None


@pytest.mark.asyncio
async def test_edit_owner_delete_validation_and_structured_memory_fail_closed(
    client,
    auth_headers,
):
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"content": "只属于 A 的记录"},
    )
    assert created.status_code == 201
    memory_id = created.json()["id"]

    other = await client.post("/v1/auth/dev-token", json={"nickname": "Other"})
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    cross_owner = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=other_headers,
        json={"expected_revision": 0, "content": "越权修改"},
    )
    assert cross_owner.status_code == 404

    for payload in (
        {},
        {"expected_revision": 0},
        {"expected_revision": 0, "content": "   "},
        {"expected_revision": 0, "content": "合法正文", "source_type": "AI_INFERENCE"},
        {"expected_revision": 0, "content": "合法正文", "confidence": 0.1},
        {"expected_revision": 0, "content": "合法正文", "is_confirmed": False},
        {
            "expected_revision": 0,
            "content": "合法正文",
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    ):
        rejected = await client.patch(
            f"/v1/memories/{memory_id}",
            headers=auth_headers,
            json=payload,
        )
        assert rejected.status_code == 422

    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=auth_headers)
    assert deleted.status_code == 204
    deleted_edit = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={"expected_revision": 0, "content": "不能复活"},
    )
    assert deleted_edit.status_code == 404

    obj = await client.post("/v1/objects", headers=auth_headers, json={"name": "护照"})
    assert obj.status_code == 201
    location = await client.post(
        f"/v1/objects/{obj.json()['id']}/locations",
        headers=auth_headers,
        json={"location_text": "书房抽屉"},
    )
    assert location.status_code == 201
    backing_memory_id = location.json()["memory_id"]
    structured_edit = await client.patch(
        f"/v1/memories/{backing_memory_id}",
        headers=auth_headers,
        json={"expected_revision": 0, "content": "随便改成另一个位置"},
    )
    assert structured_edit.status_code == 409
    assert structured_edit.json()["detail"] == "OBJECT_LOCATION_EDIT_REQUIRES_STRUCTURED_FLOW"


@pytest.mark.asyncio
async def test_photo_edit_keeps_original_media_link_but_current_text_uses_user_edit(
    client,
    auth_headers,
):
    user_id = await _current_user_id(client, auth_headers)
    now = datetime.now(UTC)

    with SessionLocal() as db:
        memory = Memory(
            user_id=user_id,
            memory_type=MemoryType.PHOTO,
            title="原图",
            content="原图说明文字",
            occurred_at=now,
            source_type=SourceType.USER_PHOTO,
            confidence=1.0,
            is_confirmed=True,
        )
        db.add(memory)
        db.flush()
        original_source = MemorySource(
            memory_id=memory.id,
            source_type=SourceType.USER_PHOTO,
            raw_text="原图说明文字",
            confidence=1.0,
        )
        db.add(original_source)
        media = MediaAsset(
            user_id=user_id,
            client_upload_id=uuid4(),
            kind=MediaKind.IMAGE,
            status=MediaStatus.READY,
            upload_object_key="staging/edit-test.jpg",
            object_key="final/edit-test.jpg",
            content_type="image/jpeg",
            size_bytes=100,
            original_filename="edit-test.jpg",
            storage_etag="etag",
            completed_at=now,
        )
        db.add(media)
        db.flush()
        db.add(
            MediaEvidenceLink(
                media_id=media.id,
                memory_source_id=original_source.id,
            )
        )
        db.commit()
        memory_id = memory.id
        original_source_id = original_source.id
        media_id = media.id

    edited = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={"expected_revision": 0, "content": "用户后来修正成蓝色票据夹"},
    )
    assert edited.status_code == 200
    assert edited.json()["source_type"] == "USER_TEXT"
    assert edited.json()["is_confirmed"] is True

    query = await client.post(
        "/v1/memory/query",
        headers=auth_headers,
        json={"question": "蓝色票据夹"},
    )
    assert query.status_code == 200
    evidence = query.json()["evidence"][0]
    assert evidence["source_type"] == "USER_TEXT"
    assert evidence["provenance"] == "USER_EDIT"
    assert evidence["media_id"] is None
    assert evidence["memory_source_id"] != str(original_source_id)

    with SessionLocal() as db:
        link = db.scalar(
            select(MediaEvidenceLink).where(
                MediaEvidenceLink.memory_source_id == original_source_id
            )
        )
        assert link is not None
        assert link.media_id == media_id
        original = db.get(MemorySource, original_source_id)
        assert original is not None
        assert original.raw_text == "原图说明文字"
