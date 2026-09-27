from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.life_event_schemas import (
    LifeEventCreate,
    LifeEventMemoryEvidenceRead,
    LifeEventPatch,
    LifeEventRead,
)
from app.services.life_event_service import (
    LifeEventError,
    create_life_event,
    create_life_event_memory_link,
    delete_life_event,
    delete_life_event_memory_link,
    get_life_event,
    life_event_read,
    list_life_event_memories,
    list_life_events,
    patch_life_event,
)

router = APIRouter(prefix="/life-events", tags=["life-events"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _raise_life_event_error(exc: LifeEventError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.post("", response_model=LifeEventRead, status_code=status.HTTP_201_CREATED)
def create_life_event_route(
    payload: LifeEventCreate,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeEventRead:
    try:
        return life_event_read(create_life_event(db, user_id=user_id, payload=payload))
    except LifeEventError as exc:
        _raise_life_event_error(exc)


@router.get("", response_model=list[LifeEventRead])
def list_life_events_route(
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[LifeEventRead]:
    return [
        life_event_read(item)
        for item in list_life_events(db, user_id=user_id, limit=limit)
    ]


@router.get("/{life_event_id}", response_model=LifeEventRead)
def get_life_event_route(
    life_event_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeEventRead:
    try:
        return life_event_read(
            get_life_event(db, user_id=user_id, life_event_id=life_event_id)
        )
    except LifeEventError as exc:
        _raise_life_event_error(exc)


@router.patch("/{life_event_id}", response_model=LifeEventRead)
def patch_life_event_route(
    life_event_id: UUID,
    payload: LifeEventPatch,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeEventRead:
    try:
        return life_event_read(
            patch_life_event(
                db,
                user_id=user_id,
                life_event_id=life_event_id,
                payload=payload,
            )
        )
    except LifeEventError as exc:
        _raise_life_event_error(exc)


@router.delete(
    "/{life_event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_life_event_route(
    life_event_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        delete_life_event(db, user_id=user_id, life_event_id=life_event_id)
    except LifeEventError as exc:
        _raise_life_event_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{life_event_id}/memories",
    response_model=list[LifeEventMemoryEvidenceRead],
)
def list_life_event_memories_route(
    life_event_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[LifeEventMemoryEvidenceRead]:
    try:
        return list_life_event_memories(
            db,
            user_id=user_id,
            life_event_id=life_event_id,
            limit=limit,
        )
    except LifeEventError as exc:
        _raise_life_event_error(exc)


@router.post(
    "/{life_event_id}/memories/{memory_id}",
    response_model=LifeEventMemoryEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_life_event_memory_link_route(
    life_event_id: UUID,
    memory_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> LifeEventMemoryEvidenceRead:
    try:
        return create_life_event_memory_link(
            db,
            user_id=user_id,
            life_event_id=life_event_id,
            memory_id=memory_id,
        )
    except LifeEventError as exc:
        _raise_life_event_error(exc)


@router.delete(
    "/{life_event_id}/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_life_event_memory_link_route(
    life_event_id: UUID,
    memory_id: UUID,
    user_id: CurrentUser,
    db: DbSession,
) -> Response:
    try:
        delete_life_event_memory_link(
            db,
            user_id=user_id,
            life_event_id=life_event_id,
            memory_id=memory_id,
        )
    except LifeEventError as exc:
        _raise_life_event_error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
