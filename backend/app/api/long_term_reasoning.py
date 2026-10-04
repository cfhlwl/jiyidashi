"""Public adapter for V2-007 stage-scoped long-term reasoning."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.long_term_reasoning_models import (
    LongTermEvidenceKind,
    LongTermReasoningResult,
    LongTermReasoningStatus,
)
from app.services.ai_gateway import AIEntitlementError, AIProvenance, get_ai_gateway
from app.services.answer_trust_service import AnswerTrustState
from app.services.api_abuse import enforce_authenticated_api_rate
from app.services.auth_rate_limit import ApiRouteClass
from app.services.long_term_reasoning_service import (
    LongTermReasoningError,
    reason_about_life_stage,
)

router = APIRouter(prefix="/life-stages", tags=["long-term-reasoning"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]
ReasoningQuestion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class LongTermReasoningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: ReasoningQuestion


class LongTermReasoningCitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: str
    kind: LongTermEvidenceKind
    life_stage_id: UUID | None
    life_event_id: UUID | None
    memory_id: UUID | None
    memory_source_id: UUID | None
    memory_trust_state: AnswerTrustState | None


class AIProvenanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gateway_request_id: str
    purpose: str
    provider_request_id: str | None
    provider: str
    model: str


class LongTermReasoningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: LongTermReasoningStatus
    answer: str | None
    citations: list[LongTermReasoningCitationResponse]
    provider_error_code: str | None
    ai_provenance: AIProvenanceResponse | None


def _provenance_response(value: AIProvenance | None) -> AIProvenanceResponse | None:
    if value is None:
        return None
    return AIProvenanceResponse(
        gateway_request_id=value.gateway_request_id,
        purpose=value.purpose,
        provider_request_id=value.provider_request_id,
        provider=value.provider,
        model=value.model,
    )


def _response(result: LongTermReasoningResult) -> LongTermReasoningResponse:
    return LongTermReasoningResponse(
        status=result.status,
        answer=result.answer,
        citations=[
            LongTermReasoningCitationResponse(
                slot=item.slot,
                kind=item.kind,
                life_stage_id=item.life_stage_id,
                life_event_id=item.life_event_id,
                memory_id=item.memory_id,
                memory_source_id=item.memory_source_id,
                memory_trust_state=item.memory_trust_state,
            )
            for item in result.citations
        ],
        provider_error_code=result.provider_error_code,
        ai_provenance=_provenance_response(result.ai_provenance),
    )


@router.post(
    "/{life_stage_id}/reason",
    response_model=LongTermReasoningResponse,
)
async def reason_about_stage_route(
    life_stage_id: UUID,
    payload: LongTermReasoningRequest,
    request: Request,
    user_id: CurrentUser,
    db: DbSession,
) -> LongTermReasoningResponse:
    enforce_authenticated_api_rate(
        db,
        user_id=user_id,
        request=request,
        route_class=ApiRouteClass.EXPENSIVE_AI,
    )
    try:
        result = await reason_about_life_stage(
            db,
            user_id=user_id,
            life_stage_id=life_stage_id,
            question=payload.question,
            ai_gateway=get_ai_gateway(),
        )
    except AIEntitlementError as exc:
        if exc.code != "PROVIDER_CONCURRENCY_SATURATED":
            raise
        headers = (
            {"Retry-After": str(max(1, int(exc.retry_after)))}
            if exc.retry_after is not None
            else None
        )
        raise HTTPException(
            status_code=429,
            detail=exc.code,
            headers=headers,
        ) from exc
    except LongTermReasoningError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    return _response(result)
