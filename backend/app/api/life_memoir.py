from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.life_memoir_models import (
    LifeMemoirChapterResponse,
    LifeMemoirStageIndexResponse,
)
from app.services.ai_gateway import get_ai_gateway
from app.services.life_memoir_service import (
    LifeMemoirError,
    build_life_memoir_chapter,
    list_life_memoir_stages,
)
from app.services.long_term_reasoning_service import LongTermReasoningError

router = APIRouter(prefix="/memoirs/life", tags=["life-memoir"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/stages", response_model=LifeMemoirStageIndexResponse)
def list_life_memoir_stages_route(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> LifeMemoirStageIndexResponse:
    try:
        return list_life_memoir_stages(
            db,
            user_id=user_id,
            limit=limit,
            cursor_value=cursor,
        )
    except LifeMemoirError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.post(
    "/stages/{life_stage_id}",
    response_model=LifeMemoirChapterResponse,
)
async def build_life_memoir_chapter_route(
    life_stage_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeMemoirChapterResponse:
    try:
        return await build_life_memoir_chapter(
            db,
            user_id=user_id,
            life_stage_id=life_stage_id,
            ai_gateway=get_ai_gateway(),
        )
    except LongTermReasoningError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
