import asyncio
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from httpx import AsyncClient


async def test_pause_blocks_automatic_location_ingest(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    paused = await client.post(
        "/v1/privacy/pause",
        headers=auth_headers,
        json={"duration_minutes": 30},
    )
    assert paused.status_code == 200
    assert paused.json()["recording_paused"] is True
    assert paused.json()["paused_since"] is not None

    location = await client.post(
        "/v1/location/batch",
        headers=auth_headers,
        json={
            "points": [
                {
                    "client_uuid": "test-point-1",
                    "latitude": 39.9042,
                    "longitude": 116.4074,
                    "accuracy": 20,
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
            ]
        },
    )
    assert location.status_code == 409
    assert location.json()["detail"] == "RECORDING_PAUSED"


async def test_paused_timestamp_is_rejected_even_after_resume(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    paused = await client.post(
        "/v1/privacy/pause",
        headers=auth_headers,
        json={"duration_minutes": 30},
    )
    assert paused.status_code == 200
    await asyncio.sleep(0.01)
    point_time = datetime.now(UTC)

    resumed = await client.post("/v1/privacy/resume", headers=auth_headers)
    assert resumed.status_code == 200
    assert resumed.json()["recording_paused"] is False

    delayed = await client.post(
        "/v1/location/batch",
        headers=auth_headers,
        json={
            "points": [
                {
                    "client_uuid": "paused-delayed-point",
                    "latitude": 39.9042,
                    "longitude": 116.4074,
                    "accuracy": 20,
                    "recorded_at": point_time.isoformat(),
                }
            ]
        },
    )
    assert delayed.status_code == 200
    assert delayed.json()["accepted"] == 0
    assert delayed.json()["rejected_privacy"] == 1


async def test_pause_today_ends_at_user_local_midnight(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # [人工注释][S1-023] “暂停今天”由服务端按用户资料里的 Asia/Shanghai
    # 计算下一次本地午夜，不能依赖客户端设备时区。
    response = await client.post("/v1/privacy/pause/today", headers=auth_headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["recording_paused"] is True

    zone = ZoneInfo("Asia/Shanghai")
    local_day = datetime.now(UTC).astimezone(zone).date()
    expected = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    actual = datetime.fromisoformat(payload["paused_until"])
    assert actual == expected

    resumed = await client.post("/v1/privacy/resume", headers=auth_headers)
    assert resumed.status_code == 200
    assert resumed.json()["recording_paused"] is False


async def test_manual_memory_still_works_during_pause(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    await client.post(
        "/v1/privacy/pause",
        headers=auth_headers,
        json={"duration_minutes": 30},
    )

    memory = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={"content": "即使暂停自动记录，我也要主动记住这件事"},
    )
    assert memory.status_code == 201
    await client.post("/v1/privacy/resume", headers=auth_headers)


async def test_location_batch_is_idempotent_by_client_uuid(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    point = {
        "client_uuid": "offline-retry-point-1",
        "latitude": 31.2304,
        "longitude": 121.4737,
        "accuracy": 15,
        "recorded_at": datetime.now(UTC).isoformat(),
    }

    first = await client.post("/v1/location/batch", headers=auth_headers, json={"points": [point]})
    second = await client.post("/v1/location/batch", headers=auth_headers, json={"points": [point]})

    assert first.status_code == 200
    assert first.json()["accepted"] == 1
    assert second.status_code == 200
    assert second.json()["accepted"] == 0


async def test_location_batch_rejects_timezone_naive_timestamp(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # [人工注释][FND-023] 混入 naive datetime 必须在 schema 层返回 422，
    # 不能进入 min/max 后变成 500。
    response = await client.post(
        "/v1/location/batch",
        headers=auth_headers,
        json={
            "points": [
                {
                    "client_uuid": "aware-point",
                    "latitude": 31.2304,
                    "longitude": 121.4737,
                    "recorded_at": datetime.now(UTC).isoformat(),
                },
                {
                    "client_uuid": "naive-point",
                    "latitude": 31.2305,
                    "longitude": 121.4738,
                    "recorded_at": "2026-09-15T10:30:00",
                },
            ]
        },
    )
    assert response.status_code == 422
