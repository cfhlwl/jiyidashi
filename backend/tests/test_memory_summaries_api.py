from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.annual_summary_models import AnnualSummaryResult, AnnualSummaryStatus
from app.daily_summary_models import (
    DailySummaryCitation,
    DailySummaryResult,
    DailySummarySlotKind,
    DailySummaryStatus,
)
from app.monthly_summary_models import MonthlySummaryResult, MonthlySummaryStatus
from app.services.answer_trust_service import AnswerTrustState


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _daily_result(
    status: DailySummaryStatus = DailySummaryStatus.DAILY_SUMMARY_READY,
) -> DailySummaryResult:
    ready = status == DailySummaryStatus.DAILY_SUMMARY_READY
    memory_id = uuid4()
    return DailySummaryResult(
        status=status,
        day=date(2026, 9, 22),
        timezone="Asia/Shanghai",
        summary="今天完成了可信回忆整理。" if ready else None,
        citations=(
            (
                DailySummaryCitation(
                    slot="D1",
                    kind=DailySummarySlotKind.MEMORY,
                    memory_id=memory_id,
                    memory_source_id=uuid4(),
                    visit_id=None,
                    trust_state=AnswerTrustState.CONFIRMED,
                ),
            )
            if ready
            else ()
        ),
        incomplete_code="INTERNAL_INCOMPLETE_MUST_NOT_LEAK",
        provider_error_code="PROVIDER_SECRET_MUST_NOT_LEAK",
        ai_provenance=None,
    )


def _monthly_result(
    status: MonthlySummaryStatus = MonthlySummaryStatus.MONTHLY_SUMMARY_READY,
    target_month: str = "2026-09",
) -> MonthlySummaryResult:
    return MonthlySummaryResult(
        status=status,
        target_month=target_month,
        timezone="Asia/Shanghai",
        summary="本月可信总结。" if status == MonthlySummaryStatus.MONTHLY_SUMMARY_READY else None,
        citations=(),
        incomplete_code="INTERNAL_MUST_NOT_LEAK",
        provider_error_code="PROVIDER_MUST_NOT_LEAK",
        ai_provenance=None,
    )


def _annual_result(
    status: AnnualSummaryStatus = AnnualSummaryStatus.ANNUAL_SUMMARY_READY,
    target_year: str = "2026",
) -> AnnualSummaryResult:
    return AnnualSummaryResult(
        status=status,
        target_year=target_year,
        timezone="Asia/Shanghai",
        summary="年度可信总结。" if status == AnnualSummaryStatus.ANNUAL_SUMMARY_READY else None,
        citations=(),
        incomplete_code="INTERNAL_MUST_NOT_LEAK",
        provider_error_code="PROVIDER_MUST_NOT_LEAK",
        ai_provenance=None,
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/memory/summaries/daily",
        "/v1/memory/summaries/monthly",
        "/v1/memory/summaries/annual",
    ],
)
async def test_trusted_summary_generation_requires_auth(client, path: str):
    response = await client.post(path, json={})
    assert response.status_code in {401, 403}


async def test_daily_adapter_uses_authenticated_user_and_trusted_service(
    client,
    monkeypatch,
):
    headers, owner = await _new_user(client, "summary-owner")
    _, other = await _new_user(client, "summary-other")
    captured: dict[str, object] = {}
    gateway = object()

    async def fake_summarize_today(db, *, user_id, ai_gateway):
        captured["db"] = db
        captured["user_id"] = user_id
        captured["ai_gateway"] = ai_gateway
        return _daily_result()

    monkeypatch.setattr("app.api.memory_summaries.get_ai_gateway", lambda: gateway)
    monkeypatch.setattr(
        "app.api.memory_summaries.summarize_today",
        fake_summarize_today,
    )

    response = await client.post(
        "/v1/memory/summaries/daily",
        headers=headers,
        json={},
    )

    assert response.status_code == 200
    assert captured["user_id"] == owner
    assert captured["user_id"] != other
    assert captured["ai_gateway"] is gateway
    assert response.json()["status"] == "DAILY_SUMMARY_READY"


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/v1/memory/summaries/daily", {"user_id": str(uuid4())}),
        ("/v1/memory/summaries/daily", {"timezone": "UTC"}),
        ("/v1/memory/summaries/monthly", {"timezone": "UTC"}),
        ("/v1/memory/summaries/monthly", {"user_id": str(uuid4())}),
        ("/v1/memory/summaries/annual", {"timezone": "UTC"}),
        ("/v1/memory/summaries/annual", {"user_id": str(uuid4())}),
    ],
)
async def test_adapter_forbids_client_authority_fields(
    client,
    auth_headers,
    path: str,
    payload: dict[str, str],
):
    response = await client.post(path, headers=auth_headers, json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "target_month",
    ["2026-9", "2026-00", "2026-13", "0000-01", "2026/09", " 2026-09"],
)
async def test_monthly_target_is_strict_calendar_month(
    client,
    auth_headers,
    target_month: str,
):
    response = await client.post(
        "/v1/memory/summaries/monthly",
        headers=auth_headers,
        json={"target_month": target_month},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "target_year",
    ["26", "0000", "9999", "2026-01", " 2026", "2026 "],
)
async def test_annual_target_is_strict_calendar_year(
    client,
    auth_headers,
    target_year: str,
):
    response = await client.post(
        "/v1/memory/summaries/annual",
        headers=auth_headers,
        json={"target_year": target_year},
    )
    assert response.status_code == 422


async def test_monthly_and_annual_forward_only_server_safe_period_inputs(
    client,
    auth_headers,
    monkeypatch,
):
    captured: list[tuple[str, str | None]] = []

    async def fake_month(db, *, user_id, ai_gateway, target_month=None):
        del db, user_id, ai_gateway
        captured.append(("month", target_month))
        return _monthly_result(target_month=target_month or "2026-09")

    async def fake_year(db, *, user_id, ai_gateway, target_year=None):
        del db, user_id, ai_gateway
        captured.append(("year", target_year))
        return _annual_result(target_year=target_year or "2026")

    monkeypatch.setattr("app.api.memory_summaries.get_ai_gateway", object)
    monkeypatch.setattr("app.api.memory_summaries.summarize_month", fake_month)
    monkeypatch.setattr("app.api.memory_summaries.summarize_year", fake_year)

    month = await client.post(
        "/v1/memory/summaries/monthly",
        headers=auth_headers,
        json={"target_month": "2026-09"},
    )
    year = await client.post(
        "/v1/memory/summaries/annual",
        headers=auth_headers,
        json={"target_year": "2026"},
    )

    assert month.status_code == 200
    assert year.status_code == 200
    assert captured == [("month", "2026-09"), ("year", "2026")]


async def test_public_trust_schema_only_advertises_summary_eligible_states(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()["components"]["schemas"]["SummaryTrustState"]
    assert schema["enum"] == ["CONFIRMED", "EVIDENCE_SUPPORTED"]


async def test_ready_response_is_public_whitelist_only(
    client,
    auth_headers,
    monkeypatch,
):
    async def fake_daily(db, *, user_id, ai_gateway):
        del db, user_id, ai_gateway
        return _daily_result()

    monkeypatch.setattr("app.api.memory_summaries.get_ai_gateway", object)
    monkeypatch.setattr("app.api.memory_summaries.summarize_today", fake_daily)

    response = await client.post(
        "/v1/memory/summaries/daily",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 200
    body = response.json()

    assert set(body) == {"status", "day", "timezone", "summary", "citations"}
    assert set(body["citations"][0]) == {
        "slot",
        "kind",
        "memory_id",
        "visit_id",
        "trust_state",
    }
    assert body["citations"][0]["trust_state"] == "CONFIRMED"
    serialized = str(body)
    assert "memory_source_id" not in serialized
    assert "INTERNAL_INCOMPLETE_MUST_NOT_LEAK" not in serialized
    assert "PROVIDER_SECRET_MUST_NOT_LEAK" not in serialized
    assert "ai_provenance" not in serialized


@pytest.mark.parametrize(
    "status",
    [
        DailySummaryStatus.NO_SUMMARIZABLE_EVIDENCE,
        DailySummaryStatus.SUMMARY_INCOMPLETE,
        DailySummaryStatus.PROVIDER_FAILED,
        DailySummaryStatus.MALFORMED_PROVIDER_OUTPUT,
        DailySummaryStatus.INVALID_CITATION,
        DailySummaryStatus.DATA_CHANGED_DURING_GENERATION,
    ],
)
async def test_daily_non_ready_statuses_remain_typed_without_fake_summary(
    client,
    auth_headers,
    monkeypatch,
    status: DailySummaryStatus,
):
    async def fake_daily(db, *, user_id, ai_gateway):
        del db, user_id, ai_gateway
        return _daily_result(status)

    monkeypatch.setattr("app.api.memory_summaries.get_ai_gateway", object)
    monkeypatch.setattr("app.api.memory_summaries.summarize_today", fake_daily)

    response = await client.post(
        "/v1/memory/summaries/daily",
        headers=auth_headers,
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == status.value
    assert body["summary"] is None
    assert body["citations"] == []


def test_adapter_is_thin_and_legacy_day_route_remains_separate():
    source = Path("app/api/memory_summaries.py").read_text(encoding="utf-8")
    legacy = Path("app/api/memories.py").read_text(encoding="utf-8")

    assert 'router = APIRouter(prefix="/memory/summaries"' in source
    assert '"/daily"' in source
    assert "summarize_today(" in source
    assert "summarize_month(" in source
    assert "summarize_year(" in source
    assert "select(" not in source
    assert "db.commit(" not in source
    assert "memory_source_id=citation.memory_source_id" not in source

    assert '@router.get("/memory/summarize/day"' in legacy
    assert "主要记录" in legacy
