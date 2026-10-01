from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.schemas import TodayFootprintResponse, TodayFootprintVisit
from app.services.day_footprint_service import get_day_footprint
from app.services.time_service import local_today


def get_today_footprint(
    db: Session,
    *,
    user_id: UUID,
) -> TodayFootprintResponse:
    # Today is only an alias over the canonical CORE-002 day service. Keeping one
    # overlap/timezone definition prevents Today and historical queries from drifting.
    result = get_day_footprint(
        db,
        user_id=user_id,
        day=local_today(db, user_id),
    )
    return TodayFootprintResponse(
        timezone=result.timezone,
        day=result.day,
        empty=result.empty,
        visits=[
            TodayFootprintVisit(**visit.model_dump())
            for visit in result.visits
        ],
    )
