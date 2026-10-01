from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.schemas import DayFootprintResponse
from app.services.day_footprint_service import get_day_footprint
from app.services.time_service import local_today

router = APIRouter(tags=["footprint"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/footprint/day", response_model=DayFootprintResponse)
def day_footprint(
    user_id: CurrentUser,
    db: DbSession,
    requested_date: Annotated[date, Query(alias="date")],
) -> DayFootprintResponse:
    # Future personal whereabouts are not a historical fact and must never be guessed.
    if requested_date > local_today(db, user_id):
        raise HTTPException(status_code=422, detail="FUTURE_FOOTPRINT_DATE")
    return get_day_footprint(
        db,
        user_id=user_id,
        day=requested_date,
    )
