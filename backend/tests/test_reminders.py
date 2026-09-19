from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.core.db import SessionLocal
from app.models import Memory, Reminder, ReminderStatus


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    payload = response.json()
    return (
        {"Authorization": f"Bearer {payload['access_token']}"},
        UUID(payload["user_id"]),
    )


def _create_headers(headers: dict[str, str], key: UUID | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(key or uuid4())}


def _future_iso(
    *,
    hours: int = 24,
    offset_hours: int = 0,
    naive: bool = False,
) -> str:
    value = datetime.now(UTC) + timedelta(hours=hours)
    if offset_hours:
        value = value.astimezone(timezone(timedelta(hours=offset_hours)))
    if naive:
        value = value.replace(tzinfo=None)
    return value.isoformat()


@pytest.mark.asyncio
async def test_create_list_owner_isolation_and_timezone_gate(client, auth_headers):
    memory = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"title": "交材料", "content": "周五前提交合同材料"},
    )
    assert memory.status_code == 201
    memory_id = memory.json()["id"]

    missing_key = await client.post(
        "/v1/reminders",
        headers=auth_headers,
        json={
            "memory_id": memory_id,
            "title": "缺少幂等键",
            "remind_at": _future_iso(offset_hours=8),
        },
    )
    assert missing_key.status_code == 422

    naive = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers),
        json={
            "memory_id": memory_id,
            "title": "提交材料",
            "remind_at": _future_iso(naive=True),
        },
    )
    assert naive.status_code == 422

    created = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers),
        json={
            "memory_id": memory_id,
            "title": " 提交材料 ",
            "content": " 带上盖章件 ",
            "remind_at": _future_iso(offset_hours=8),
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["memory_id"] == memory_id
    assert body["title"] == "提交材料"
    assert body["content"] == "带上盖章件"
    assert body["status"] == "PENDING"

    pending = await client.get(
        "/v1/reminders",
        headers=auth_headers,
        params={"status": "PENDING"},
    )
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()] == [body["id"]]

    other_headers, _ = await _new_user(client, "reminder-other")
    cross_owner = await client.post(
        "/v1/reminders",
        headers=_create_headers(other_headers),
        json={
            "memory_id": memory_id,
            "title": "不应成功",
            "remind_at": _future_iso(),
        },
    )
    assert cross_owner.status_code == 404
    assert cross_owner.json()["detail"] == "REMINDER_MEMORY_NOT_FOUND"
    other_list = await client.get("/v1/reminders", headers=other_headers)
    assert other_list.status_code == 200
    assert other_list.json() == []


@pytest.mark.asyncio
async def test_create_is_response_loss_idempotent_and_rejects_past_time(
    client,
    auth_headers,
):
    memory = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"content": "明天提交材料"},
    )
    assert memory.status_code == 201
    memory_id = memory.json()["id"]

    past = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers),
        json={
            "memory_id": memory_id,
            "title": "过期提醒",
            "remind_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
    )
    assert past.status_code == 422
    assert past.json()["detail"] == "REMINDER_TIME_MUST_BE_FUTURE"

    key = uuid4()
    payload = {
        "memory_id": memory_id,
        "title": "提交材料",
        "content": "带盖章件",
        "remind_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
    }
    first = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers, key),
        json=payload,
    )
    assert first.status_code == 201

    # 模拟“服务端已提交、响应丢失”后的同请求重放：必须返回同一资源。
    replay = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers, key),
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    conflict = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers, key),
        json={**payload, "title": "同 key 的另一个提醒"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"

    profile = await client.get("/v1/user", headers=auth_headers)
    owner_id = UUID(profile.json()["id"])
    with SessionLocal() as db:
        reminders = list(
            db.query(Reminder).filter(Reminder.user_id == owner_id).all()
        )
        assert len(reminders) == 1
        assert reminders[0].id == UUID(first.json()["id"])


@pytest.mark.asyncio
async def test_pending_filter_is_not_consumed_by_large_history(client, auth_headers):
    profile = await client.get("/v1/user", headers=auth_headers)
    owner_id = UUID(profile.json()["id"])
    now = datetime.now(UTC)
    with SessionLocal() as db:
        memory = Memory(user_id=owner_id, content="older pending")
        db.add(memory)
        db.flush()
        db.add(
            Reminder(
                user_id=owner_id,
                memory_id=memory.id,
                title="不能被历史挤掉",
                remind_at=now + timedelta(days=1),
                status=ReminderStatus.PENDING,
                created_at=now - timedelta(days=1),
            )
        )
        for index in range(120):
            db.add(
                Reminder(
                    user_id=owner_id,
                    memory_id=memory.id,
                    title=f"history-{index}",
                    remind_at=now + timedelta(days=2, minutes=index),
                    status=ReminderStatus.DONE
                    if index % 2 == 0
                    else ReminderStatus.CANCELLED,
                    created_at=now + timedelta(minutes=index),
                )
            )
        db.commit()

    pending = await client.get(
        "/v1/reminders",
        headers=auth_headers,
        params={"status": "PENDING", "limit": 100},
    )
    assert pending.status_code == 200
    assert [item["title"] for item in pending.json()] == ["不能被历史挤掉"]


@pytest.mark.asyncio
async def test_terminal_transitions_are_idempotent_but_cannot_cross(client, auth_headers):
    memory = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"content": "记得处理报销"},
    )
    memory_id = memory.json()["id"]

    async def create(title: str):
        response = await client.post(
            "/v1/reminders",
            headers=_create_headers(auth_headers),
            json={
                "memory_id": memory_id,
                "title": title,
                "remind_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == 201
        return response.json()

    done_item = await create("处理报销")
    done = await client.post(
        f"/v1/reminders/{done_item['id']}/done",
        headers=auth_headers,
    )
    assert done.status_code == 200
    assert done.json()["status"] == "DONE"
    done_retry = await client.post(
        f"/v1/reminders/{done_item['id']}/done",
        headers=auth_headers,
    )
    assert done_retry.status_code == 200
    cancel_after_done = await client.post(
        f"/v1/reminders/{done_item['id']}/cancel",
        headers=auth_headers,
    )
    assert cancel_after_done.status_code == 409
    assert cancel_after_done.json()["detail"] == "REMINDER_STATUS_CONFLICT"

    cancelled_item = await create("取消测试")
    cancelled = await client.post(
        f"/v1/reminders/{cancelled_item['id']}/cancel",
        headers=auth_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    cancel_retry = await client.post(
        f"/v1/reminders/{cancelled_item['id']}/cancel",
        headers=auth_headers,
    )
    assert cancel_retry.status_code == 200
    done_after_cancel = await client.post(
        f"/v1/reminders/{cancelled_item['id']}/done",
        headers=auth_headers,
    )
    assert done_after_cancel.status_code == 409


@pytest.mark.asyncio
async def test_memory_delete_cancels_pending_reminder_and_keeps_history(client, auth_headers):
    memory = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"title": "取文件", "content": "去前台取文件"},
    )
    memory_id = memory.json()["id"]
    created = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers),
        json={
            "memory_id": memory_id,
            "title": "取文件",
            "remind_at": _future_iso(hours=10),
        },
    )
    assert created.status_code == 201
    reminder_id = UUID(created.json()["id"])

    completed = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers),
        json={
            "memory_id": memory_id,
            "title": "已完成历史",
            "remind_at": _future_iso(hours=9),
        },
    )
    assert completed.status_code == 201
    completed_id = UUID(completed.json()["id"])
    marked_done = await client.post(
        f"/v1/reminders/{completed_id}/done",
        headers=auth_headers,
    )
    assert marked_done.status_code == 200

    deleted = await client.delete(f"/v1/memories/{memory_id}", headers=auth_headers)
    assert deleted.status_code == 204

    with SessionLocal() as db:
        reminder = db.get(Reminder, reminder_id)
        assert reminder is not None
        assert reminder.status == ReminderStatus.CANCELLED
        assert reminder.memory_id is None
        completed_history = db.get(Reminder, completed_id)
        assert completed_history is not None
        assert completed_history.status == ReminderStatus.DONE
        assert completed_history.memory_id is None

    recreate = await client.post(
        "/v1/reminders",
        headers=_create_headers(auth_headers),
        json={
            "memory_id": memory_id,
            "title": "不能重新提醒",
            "remind_at": _future_iso(hours=11),
        },
    )
    assert recreate.status_code == 404
    assert recreate.json()["detail"] == "REMINDER_MEMORY_NOT_FOUND"

    history = await client.get("/v1/reminders", headers=auth_headers)
    assert history.status_code == 200
    item = next(row for row in history.json() if row["id"] == str(reminder_id))
    assert item["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_reminder_actions_are_owner_scoped(client, auth_headers):
    profile = await client.get("/v1/user", headers=auth_headers)
    owner_id = UUID(profile.json()["id"])
    with SessionLocal() as db:
        memory = Memory(user_id=owner_id, content="owner memory")
        db.add(memory)
        db.flush()
        reminder = Reminder(
            user_id=owner_id,
            memory_id=memory.id,
            title="owner reminder",
            remind_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add(reminder)
        db.commit()
        reminder_id = reminder.id

    other_headers, _ = await _new_user(client, "transition-other")
    hidden = await client.post(
        f"/v1/reminders/{reminder_id}/done",
        headers=other_headers,
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "REMINDER_NOT_FOUND"
