from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.schemas import PrivacyPauseRequest, PrivacyStatusResponse
from app.services.privacy_service import get_privacy_state, is_pause_active

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.get("/status", response_model=PrivacyStatusResponse)
def privacy_status(
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PrivacyStatusResponse:
    state = get_privacy_state(db, user_id)
    return PrivacyStatusResponse(
        recording_paused=is_pause_active(state.recording_paused_until),
        paused_until=state.recording_paused_until,
    )


@router.post("/pause", response_model=PrivacyStatusResponse)
def pause_recording(
    payload: PrivacyPauseRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PrivacyStatusResponse:
    state = get_privacy_state(db, user_id)
    until = payload.until
    if payload.duration_minutes is not None:
        until = datetime.now(UTC) + timedelta(minutes=payload.duration_minutes)

    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)

    state.recording_paused_until = until
    db.commit()
    return PrivacyStatusResponse(recording_paused=True, paused_until=until)


@router.post("/resume", response_model=PrivacyStatusResponse)
def resume_recording(
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PrivacyStatusResponse:
    state = get_privacy_state(db, user_id)
    state.recording_paused_until = None
    db.commit()
    return PrivacyStatusResponse(recording_paused=False, paused_until=None)
