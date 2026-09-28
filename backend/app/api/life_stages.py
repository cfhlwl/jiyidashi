from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.life_stage_schemas import (
    LifeStageCreate,
    LifeStageEventEvidenceRead,
    LifeStagePatch,
    LifeStageRead,
)
from app.services.life_stage_service import (
    LifeStageError,
    create_life_stage,
    create_life_stage_event_link,
    delete_life_stage,
    delete_life_stage_event_link,
    get_life_stage,
    life_stage_read,
    list_life_stage_events,
    list_life_stages,
    patch_life_stage,
)

router = APIRouter(prefix="/life-stages", tags=["life-stages"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _raise_life_stage_error(exc: LifeStageError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.post("", response_model=LifeStageRead, status_code=status.HTTP_201_CREATED)
def create_life_stage_route(
    payload: LifeStageCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeStageRead:
    try:
        return life_stage_read(create_life_stage(db, user_id=user_id, payload=payload))
    except LifeStageError as exc:
        _raise_life_stage_error(exc)


@router.get("", response_model=list[LifeStageRead])
def list_life_stages_route(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[LifeStageRead]:
    return [
        life_stage_read(item)
        for item in list_life_stages(db, user_id=user_id, limit=limit)
    ]


@router.get("/{life_stage_id}", response_model=LifeStageRead)
def get_life_stage_route(
    life_stage_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeStageRead:
    try:
        return life_stage_read(
            get_life_stage(db, user_id=user_id, life_stage_id=life_stage_id)
        )
    except LifeStageError as exc:
        _raise_life_stage_error(exc)


@router.patch("/{life_stage_id}", response_model=LifeStageRead)
def patch_life_stage_route(
    life_stage_id: UUID,
    payload: LifeStagePatch,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeStageRead:
    try:
        return life_stage_read(
            patch_life_stage(
                db,
                user_id=user_id,
                life_stage_id=life_stage_id,
                payload=payload,
            )
        )
    except LifeStageError as exc:
        _raise_life_stage_error(exc)


@router.delete("/{life_stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_life_stage_route(
    life_stage_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        delete_life_stage(db, user_id=user_id, life_stage_id=life_stage_id)
    except LifeStageError as exc:
        _raise_life_stage_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{life_stage_id}/events",
    response_model=list[LifeStageEventEvidenceRead],
)
def list_life_stage_events_route(
    life_stage_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[LifeStageEventEvidenceRead]:
    try:
        return list_life_stage_events(
            db,
            user_id=user_id,
            life_stage_id=life_stage_id,
            limit=limit,
        )
    except LifeStageError as exc:
        _raise_life_stage_error(exc)


@router.post(
    "/{life_stage_id}/events/{life_event_id}",
    response_model=LifeStageEventEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_life_stage_event_link_route(
    life_stage_id: UUID,
    life_event_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeStageEventEvidenceRead:
    try:
        return create_life_stage_event_link(
            db,
            user_id=user_id,
            life_stage_id=life_stage_id,
            life_event_id=life_event_id,
        )
    except LifeStageError as exc:
        _raise_life_stage_error(exc)


@router.delete(
    "/{life_stage_id}/events/{life_event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_life_stage_event_link_route(
    life_stage_id: UUID,
    life_event_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        delete_life_stage_event_link(
            db,
            user_id=user_id,
            life_stage_id=life_stage_id,
            life_event_id=life_event_id,
        )
    except LifeStageError as exc:
        _raise_life_stage_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
