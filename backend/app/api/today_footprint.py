from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.schemas import TodayFootprintResponse
from app.services.today_footprint_service import get_today_footprint

router = APIRouter(tags=["today"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/today/footprint", response_model=TodayFootprintResponse)
def today_footprint(
    user_id: CurrentUser,
    db: DbSession,
) -> TodayFootprintResponse:
    # [人工注释][S2-012] 这是只读产品投影：不触发定位、不运行聚类、不写 Place/Visit。
    return get_today_footprint(db, user_id=user_id)
