import asyncio
from datetime import UTC, datetime

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
