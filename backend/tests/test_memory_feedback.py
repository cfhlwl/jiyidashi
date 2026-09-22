from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.memory_feedback_models import MemoryFeedback, MemoryFeedbackAction
from app.models import Memory, MemoryEdit, MemorySource, SourceType


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _feedback_headers(headers: dict[str, str], key: UUID | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(key or uuid4())}


async def _create_memory(client, headers, *, content="原始记忆", memory_type="NOTE"):
    response = await client.post(
        "/v1/memories",
        headers=headers,
        json={"content": content, "memory_type": memory_type},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_confirm_is_revision_bound_audit_and_duplicate_safe(client, auth_headers):
    memory = await _create_memory(client, auth_headers)
    memory_id = UUID(memory["id"])

    first = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert first.status_code == 201
    body = first.json()
    assert body["action"] == "CONFIRM"
    assert body["memory_revision"] == 0
    assert body["result_revision"] is None

    duplicate = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == body["id"]

    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count(MemoryFeedback.id)).where(
                    MemoryFeedback.memory_id == memory_id,
                    MemoryFeedback.action == MemoryFeedbackAction.CONFIRM.value,
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_edit_after_confirm_does_not_transfer_confirmation_to_new_revision(
    client,
    auth_headers,
):
    memory = await _create_memory(client, auth_headers)
    memory_id = memory["id"]

    confirmed = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert confirmed.status_code == 201

    edited = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={"expected_revision": 0, "content": "新的正文"},
    )
    assert edited.status_code == 200
    assert edited.json()["edit_revision"] == 1

    stale = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "MEMORY_FEEDBACK_REVISION_CONFLICT"

    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(MemoryFeedback).where(
                    MemoryFeedback.memory_id == UUID(memory_id)
                )
            ).all()
        )
        assert [(row.memory_revision, row.action) for row in rows] == [(0, "CONFIRM")]


@pytest.mark.asyncio
async def test_correct_reuses_memory_edit_and_preserves_original_evidence(
    client,
    auth_headers,
    monkeypatch,
):
    import app.services.memory_edit_service as edit_module

    memory = await _create_memory(client, auth_headers, content="错误正文")
    memory_id = UUID(memory["id"])

    with SessionLocal() as db:
        original_sources = list(
            db.scalars(
                select(MemorySource).where(MemorySource.memory_id == memory_id)
            ).all()
        )
        assert len(original_sources) == 1
        original_source_id = original_sources[0].id

    invalidated: list[UUID] = []
    original_invalidate = edit_module.invalidate_memory_embedding

    def record_invalidation(db, target_memory_id):
        invalidated.append(target_memory_id)
        return original_invalidate(db, target_memory_id)

    monkeypatch.setattr(edit_module, "invalidate_memory_embedding", record_invalidation)

    corrected = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={
            "action": "CORRECT",
            "expected_revision": 0,
            "content": "正确正文",
        },
    )
    assert corrected.status_code == 201
    assert corrected.json()["memory_revision"] == 0
    assert corrected.json()["result_revision"] == 1
    assert invalidated == [memory_id]

    with SessionLocal() as db:
        current = db.get(Memory, memory_id)
        assert current is not None
        assert current.content == "正确正文"
        assert current.edit_revision == 1
        edits = list(
            db.scalars(select(MemoryEdit).where(MemoryEdit.memory_id == memory_id)).all()
        )
        assert len(edits) == 1
        assert edits[0].previous_content == "错误正文"
        assert edits[0].new_content == "正确正文"
        sources = list(
            db.scalars(
                select(MemorySource)
                .where(MemorySource.memory_id == memory_id)
                .order_by(MemorySource.created_at.asc(), MemorySource.id.asc())
            ).all()
        )
        assert original_source_id in {source.id for source in sources}
        assert any(
            source.source_type == SourceType.USER_TEXT
            and source.raw_text == "正确正文"
            and source.id != original_source_id
            for source in sources
        )


@pytest.mark.asyncio
async def test_stale_correct_and_noop_correct_fail_closed(client, auth_headers):
    memory = await _create_memory(client, auth_headers, content="当前正文")
    memory_id = memory["id"]

    no_change = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CORRECT", "expected_revision": 0, "content": "当前正文"},
    )
    assert no_change.status_code == 409
    assert no_change.json()["detail"] == "MEMORY_FEEDBACK_CORRECTION_NO_CHANGE"

    edited = await client.patch(
        f"/v1/memories/{memory_id}",
        headers=auth_headers,
        json={"expected_revision": 0, "content": "revision 1"},
    )
    assert edited.status_code == 200

    stale = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CORRECT", "expected_revision": 0, "content": "stale correction"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "MEMORY_FEEDBACK_REVISION_CONFLICT"


@pytest.mark.asyncio
async def test_delete_reuses_trusted_delete_and_post_delete_feedback_is_hidden(
    client,
    auth_headers,
):
    memory = await _create_memory(client, auth_headers, content="删除这条")
    memory_id = UUID(memory["id"])

    deleted = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "DELETE", "expected_revision": 0},
    )
    assert deleted.status_code == 201
    assert deleted.json()["action"] == "DELETE"

    with SessionLocal() as db:
        row = db.get(Memory, memory_id)
        assert row is not None
        assert row.is_deleted is True
        audit = db.get(MemoryFeedback, UUID(deleted.json()["id"]))
        assert audit is not None
        assert audit.memory_revision == 0

    after_delete = await client.post(
        f"/v1/memories/{memory_id}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert after_delete.status_code == 404
    assert after_delete.json()["detail"] == "MEMORY_NOT_FOUND"


@pytest.mark.asyncio
async def test_feedback_owner_isolation_and_object_location_boundary(client, auth_headers):
    memory = await _create_memory(client, auth_headers)
    other_headers, _ = await _new_user(client, "feedback-other")

    foreign = await client.post(
        f"/v1/memories/{memory['id']}/feedback",
        headers=_feedback_headers(other_headers),
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "MEMORY_NOT_FOUND"

    object_memory = await _create_memory(
        client,
        auth_headers,
        content="护照在抽屉",
        memory_type="OBJECT_LOCATION",
    )
    structured = await client.post(
        f"/v1/memories/{object_memory['id']}/feedback",
        headers=_feedback_headers(auth_headers),
        json={"action": "CORRECT", "expected_revision": 0, "content": "护照在柜子"},
    )
    assert structured.status_code == 409
    assert structured.json()["detail"] == (
        "OBJECT_LOCATION_FEEDBACK_REQUIRES_STRUCTURED_FLOW"
    )


@pytest.mark.asyncio
async def test_feedback_schema_rejects_client_trust_authority(client, auth_headers):
    memory = await _create_memory(client, auth_headers)

    for field, value in [
        ("is_confirmed", True),
        ("confidence", 1.0),
        ("source_type", "USER_TEXT"),
        ("trust_state", "CONFIRMED"),
    ]:
        response = await client.post(
            f"/v1/memories/{memory['id']}/feedback",
            headers=_feedback_headers(auth_headers),
            json={
                "action": "CONFIRM",
                "expected_revision": 0,
                field: value,
            },
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_feedback_idempotency_key_replay_and_conflict(client, auth_headers):
    memory = await _create_memory(client, auth_headers)
    key = uuid4()
    headers = _feedback_headers(auth_headers, key)

    first = await client.post(
        f"/v1/memories/{memory['id']}/feedback",
        headers=headers,
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert first.status_code == 201

    replay = await client.post(
        f"/v1/memories/{memory['id']}/feedback",
        headers=headers,
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    conflict = await client.post(
        f"/v1/memories/{memory['id']}/feedback",
        headers=headers,
        json={"action": "DELETE", "expected_revision": 0},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"


@pytest.mark.asyncio
async def test_feedback_requires_explicit_authenticated_action_and_idempotency_key(
    client,
    auth_headers,
):
    memory = await _create_memory(client, auth_headers)

    missing_key = await client.post(
        f"/v1/memories/{memory['id']}/feedback",
        headers=auth_headers,
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert missing_key.status_code == 422

    unauthenticated = await client.post(
        f"/v1/memories/{memory['id']}/feedback",
        headers={"Idempotency-Key": str(uuid4())},
        json={"action": "CONFIRM", "expected_revision": 0},
    )
    assert unauthenticated.status_code in {401, 403}


def test_feedback_foundation_has_no_ai_provider_path():
    import inspect

    import app.services.memory_feedback_service as module

    source = inspect.getsource(module)
    assert "AIGateway" not in source
    assert "provider" not in source.lower()
