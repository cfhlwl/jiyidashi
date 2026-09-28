from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.life_history_models import LifeHistoryTimelineResponse
from app.services.life_history_service import LifeHistoryError, list_life_history_timeline

router = APIRouter(prefix="/life-history", tags=["life-history"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/timeline", response_model=LifeHistoryTimelineResponse)
def get_life_history_timeline(
    user_id: CurrentUser,
    db: DbSession,
    start_year: Annotated[int, Query(ge=1, le=9998)],
    end_year: Annotated[int, Query(ge=1, le=9998)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> LifeHistoryTimelineResponse:
    try:
        return list_life_history_timeline(
            db,
            user_id=user_id,
            start_year=start_year,
            end_year=end_year,
            limit=limit,
            cursor_value=cursor,
        )
    except LifeHistoryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
