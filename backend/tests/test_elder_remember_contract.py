from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_elder_remember_adds_no_backend_capture_authority(client: AsyncClient):
    paths = set(app.openapi()["paths"])
    assert not any(path.startswith("/v1/elder") for path in paths)
    assert "/v1/memories" in paths
    assert "/v1/media/uploads" in paths
    assert "/v1/media/{media_id}/voice-memory" in paths
    assert "/v1/privacy/pause" in paths


@pytest.mark.asyncio
async def test_privacy_pause_still_allows_explicit_user_text_capture(client: AsyncClient):
    auth = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "elder-explicit-capture"},
    )
    assert auth.status_code == 200
    headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}

    paused = await client.post(
        "/v1/privacy/pause",
        headers=headers,
        json={"duration_minutes": 60},
    )
    assert paused.status_code == 200
    assert paused.json()["recording_paused"] is True

    created = await client.post(
        "/v1/memories",
        headers=headers,
        json={
            "memory_type": "NOTE",
            "content": "这是我主动记下的内容",
            "capture_source": "USER_TEXT",
        },
    )
    assert created.status_code == 201
    assert created.json()["content"] == "这是我主动记下的内容"
    assert created.json()["capture_source"] == "USER_TEXT"
