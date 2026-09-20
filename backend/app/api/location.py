from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import Place, Visit
from app.schemas import (
    LocationBatchRequest,
    LocationBatchResponse,
    PlaceNameCorrectionRequest,
    PlaceRead,
    VisitRead,
)
from app.services.location_service import LocationIngestError, ingest_location_batch
from app.services.place_naming_service import PlaceNamingError, correct_place_name

router = APIRouter(prefix="/location", tags=["location"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.post("/batch", response_model=LocationBatchResponse)
def upload_location_batch(
    payload: LocationBatchRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> LocationBatchResponse:
    try:
        result = ingest_location_batch(db, user_id=user_id, payload=payload)
    except LocationIngestError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    return LocationBatchResponse(**result.__dict__)


@router.get("/visits", response_model=list[VisitRead])
def list_visits(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[Visit]:
    # [人工注释][S2-007] owner 只来自认证 token，不接受 caller 指定 user_id。
    return list(
        db.scalars(
            select(Visit)
            .where(Visit.user_id == user_id)
            .order_by(Visit.arrived_at.desc(), Visit.id)
            .limit(limit)
        )
    )


@router.get("/places", response_model=list[PlaceRead])
def list_places(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[Place]:
    return list(
        db.scalars(
            select(Place)
            .where(Place.user_id == user_id)
            .order_by(Place.last_visited_at.desc().nullslast(), Place.id)
            .limit(limit)
        )
    )


@router.put("/places/{place_id}/name", response_model=PlaceRead)
def update_place_name(
    place_id: UUID,
    payload: PlaceNameCorrectionRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> Place:
    # [人工注释][S2-010] owner 只来自 token；服务层对 Place 行加锁并使用 ClientMutation
    # 收敛重放。客户端只提交“用户想叫什么”，不能提交 name_source/is_user_named。
    try:
        return correct_place_name(
            db,
            user_id=user_id,
            place_id=place_id,
            client_uuid=payload.client_uuid,
            name=payload.name,
        )
    except PlaceNamingError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
