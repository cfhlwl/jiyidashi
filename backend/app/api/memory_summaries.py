"""Public product adapter for trusted S3-015/S3-016/S3-017 summaries."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from app.annual_summary_models import AnnualSummaryResult, AnnualSummaryStatus
from app.core.db import get_db
from app.daily_summary_models import DailySummaryResult, DailySummaryStatus
from app.deps import get_current_user_id
from app.monthly_summary_models import MonthlySummaryResult, MonthlySummaryStatus
from app.services.ai_gateway import get_ai_gateway
from app.services.annual_summary_service import summarize_year
from app.services.daily_summary_service import summarize_today
from app.services.monthly_summary_service import summarize_month

router = APIRouter(prefix="/memory/summaries", tags=["memory-summaries"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]

_TARGET_MONTH_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})$")
_TARGET_YEAR_RE = re.compile(r"^(?P<year>\d{4})$")


class SummaryCitationKind(StrEnum):
    MEMORY = "MEMORY"
    VISIT = "VISIT"


class SummaryTrustState(StrEnum):
    CONFIRMED = "CONFIRMED"
    EVIDENCE_SUPPORTED = "EVIDENCE_SUPPORTED"


class DailySummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MonthlySummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_month: str | None = None

    @field_validator("target_month")
    @classmethod
    def validate_target_month(cls, value: str | None) -> str | None:
        if value is None:
            return None
        match = _TARGET_MONTH_RE.fullmatch(value)
        if match is None:
            raise ValueError("target_month must be strict YYYY-MM")
        year = int(match.group("year"))
        month = int(match.group("month"))
        if year < 1 or month < 1 or month > 12:
            raise ValueError("target_month must be a valid calendar month")
        return value


class AnnualSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_year: str | None = None

    @field_validator("target_year")
    @classmethod
    def validate_target_year(cls, value: str | None) -> str | None:
        if value is None:
            return None
        match = _TARGET_YEAR_RE.fullmatch(value)
        if match is None:
            raise ValueError("target_year must be strict YYYY")
        year = int(match.group("year"))
        if year < 1 or year >= 9999:
            raise ValueError("target_year is outside the supported calendar range")
        return value


class SummaryCitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str
    kind: SummaryCitationKind
    memory_id: UUID | None
    visit_id: UUID | None
    trust_state: SummaryTrustState | None


class DailySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DailySummaryStatus
    day: str
    timezone: str
    summary: str | None
    citations: list[SummaryCitationResponse]


class MonthlySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: MonthlySummaryStatus
    target_month: str
    timezone: str
    summary: str | None
    citations: list[SummaryCitationResponse]


class AnnualSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AnnualSummaryStatus
    target_year: str
    timezone: str
    summary: str | None
    citations: list[SummaryCitationResponse]


def _citation_response(citation) -> SummaryCitationResponse:
    # [人工注释][#103] Public projection deliberately drops memory_source_id and all
    # provider/internal provenance. Owner-scoped Memory/Visit IDs are sufficient for V1 UI.
    return SummaryCitationResponse(
        slot=citation.slot,
        kind=SummaryCitationKind(citation.kind.value),
        memory_id=citation.memory_id,
        visit_id=citation.visit_id,
        trust_state=(
            None
            if citation.trust_state is None
            else SummaryTrustState(citation.trust_state.value)
        ),
    )


def _daily_response(result: DailySummaryResult) -> DailySummaryResponse:
    return DailySummaryResponse(
        status=result.status,
        day=result.day.isoformat(),
        timezone=result.timezone,
        summary=result.summary,
        citations=[_citation_response(item) for item in result.citations],
    )


def _monthly_response(result: MonthlySummaryResult) -> MonthlySummaryResponse:
    return MonthlySummaryResponse(
        status=result.status,
        target_month=result.target_month,
        timezone=result.timezone,
        summary=result.summary,
        citations=[_citation_response(item) for item in result.citations],
    )


def _annual_response(result: AnnualSummaryResult) -> AnnualSummaryResponse:
    return AnnualSummaryResponse(
        status=result.status,
        target_year=result.target_year,
        timezone=result.timezone,
        summary=result.summary,
        citations=[_citation_response(item) for item in result.citations],
    )


@router.post("/daily", response_model=DailySummaryResponse)
async def generate_daily_summary(
    payload: DailySummaryRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> DailySummaryResponse:
    del payload
    # [人工注释][#103] This is only an authenticated adapter. Local-day boundaries,
    # authoritative snapshot/trust and provider handling remain owned by S3-015.
    result = await summarize_today(
        db,
        user_id=user_id,
        ai_gateway=get_ai_gateway(),
    )
    return _daily_response(result)


@router.post("/monthly", response_model=MonthlySummaryResponse)
async def generate_monthly_summary(
    payload: MonthlySummaryRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> MonthlySummaryResponse:
    result = await summarize_month(
        db,
        user_id=user_id,
        ai_gateway=get_ai_gateway(),
        target_month=payload.target_month,
    )
    return _monthly_response(result)


@router.post("/annual", response_model=AnnualSummaryResponse)
async def generate_annual_summary(
    payload: AnnualSummaryRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> AnnualSummaryResponse:
    result = await summarize_year(
        db,
        user_id=user_id,
        ai_gateway=get_ai_gateway(),
        target_year=payload.target_year,
    )
    return _annual_response(result)
