from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.schemas import PrivacyPauseRequest, PrivacyStatusResponse
from app.services.privacy_service import (
    ensure_utc,
    get_privacy_state,
    is_pause_active,
    pause_recording as pause_recording_service,
    resume_recording as resume_recording_service,
)

router = APIRouter(prefix="/privacy", tags=["privacy"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _response(state) -> PrivacyStatusResponse:
    return PrivacyStatusResponse(
        recording_paused=is_pause_active(state.recording_paused_until),
        paused_since=(
            ensure_utc(state.recording_paused_since)
            if state.recording_paused_since
            else None
        ),
        paused_until=(
            ensure_utc(state.recording_paused_until)
            if state.recording_paused_until
            else None
        ),
    )


@router.get("/status", response_model=PrivacyStatusResponse)
def privacy_status(user_id: CurrentUser, db: DbSession) -> PrivacyStatusResponse:
    return _response(get_privacy_state(db, user_id))


@router.post("/pause", response_model=PrivacyStatusResponse)
def pause_recording(
    payload: PrivacyPauseRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> PrivacyStatusResponse:
    now = datetime.now(UTC)
    until = payload.until
    if payload.duration_minutes is not None:
        until = now + timedelta(minutes=payload.duration_minutes)
    assert until is not None
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)

    state = pause_recording_service(db, user_id, started_at=now, ended_at=until)
    db.commit()
    db.refresh(state)
    return _response(state)


@router.post("/resume", response_model=PrivacyStatusResponse)
def resume_recording(user_id: CurrentUser, db: DbSession) -> PrivacyStatusResponse:
    state = resume_recording_service(db, user_id, resumed_at=datetime.now(UTC))
    db.commit()
    db.refresh(state)
    return _response(state)
