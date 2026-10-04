from __future__ import annotations

from uuid import uuid4

import pytest

from app.api import annual_memoir as annual_memoir_api
from app.api import life_memoir as life_memoir_api
from app.api import long_term_reasoning as reasoning_api
from app.api import memory_summaries as summaries_api
from app.services.ai_gateway import AIEntitlementError


async def _headers(client, label: str) -> dict[str, str]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": label})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _saturated(*args, **kwargs):
    del args, kwargs
    raise AIEntitlementError(
        "PROVIDER_CONCURRENCY_SATURATED",
        status_code=429,
        retry_after=23,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "attribute", "method", "path", "payload"),
    [
        (
            summaries_api,
            "summarize_today",
            "post",
            "/v1/memory/summaries/daily",
            {},
        ),
        (
            summaries_api,
            "summarize_month",
            "post",
            "/v1/memory/summaries/monthly",
            {"target_month": "2026-09"},
        ),
        (
            summaries_api,
            "summarize_year",
            "post",
            "/v1/memory/summaries/annual",
            {"target_year": "2026"},
        ),
        (
            reasoning_api,
            "reason_about_life_stage",
            "post",
            f"/v1/life-stages/{uuid4()}/reason",
            {"question": "阶段是什么？"},
        ),
        (
            annual_memoir_api,
            "build_annual_memoir",
            "post",
            "/v1/memoirs/annual",
            {"target_year": "2025"},
        ),
        (
            life_memoir_api,
            "build_life_memoir_chapter",
            "post",
            f"/v1/memoirs/life/stages/{uuid4()}",
            None,
        ),
    ],
)
async def test_public_ai_surfaces_keep_provider_saturation_429_retry_after(
    client,
    monkeypatch,
    module,
    attribute,
    method,
    path,
    payload,
):
    monkeypatch.setattr(module, attribute, _saturated)
    headers = await _headers(client, f"sec016-public-ai-{attribute}")

    response = await getattr(client, method)(
        path,
        headers=headers,
        **({} if payload is None else {"json": payload}),
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "PROVIDER_CONCURRENCY_SATURATED"
    assert response.headers["Retry-After"] == "23"
