"""Authenticated HTTP boundary for S3-003 Intent Router.

Owner identity is server-derived and the endpoint returns control metadata only;
downstream capability services keep authority over facts, Evidence and mutations.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.intent_models import IntentRouteRequest, IntentRouteResult
from app.services.intent_router import route_intent

router = APIRouter(prefix="/intent", tags=["intent"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/route", response_model=IntentRouteResult)
def intent_route(
    payload: IntentRouteRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> IntentRouteResult:
    # Owner context comes only from authentication. The request body cannot
    # select another user's Object/Place inventory for routing.
    return route_intent(
        db,
        user_id=user_id,
        question=payload.question,
    )
