from datetime import UTC, datetime

from httpx import AsyncClient


async def test_timeline_uses_user_timezone_for_day_boundary(
    client: AsyncClient,
    auth_headers: dict[str, str],
):
    # 2026-09-14 16:30 UTC == 2026-09-15 00:30 Asia/Shanghai.
    created = await client.post(
        "/v1/memories",
        headers=auth_headers,
        json={
            "content": "中国时区凌晨记录",
            "occurred_at": datetime(2026, 9, 14, 16, 30, tzinfo=UTC).isoformat(),
        },
    )
    assert created.status_code == 201

    timeline = await client.get(
        "/v1/timeline?day=2026-09-15",
        headers=auth_headers,
    )
    assert timeline.status_code == 200
    assert any(item["content"] == "中国时区凌晨记录" for item in timeline.json())

    previous_day = await client.get(
        "/v1/timeline?day=2026-09-14",
        headers=auth_headers,
    )
    assert previous_day.status_code == 200
    assert not any(item["content"] == "中国时区凌晨记录" for item in previous_day.json())
