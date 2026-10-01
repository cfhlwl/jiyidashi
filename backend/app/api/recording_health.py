from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id
from app.core.db import get_db
from app.schemas import (
    RecordingClientState,
    RecordingHealthResponse,
)
from app.services.recording_health_service import get_recording_health

router = APIRouter(prefix="/recording", tags=["recording-health"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/health", response_model=RecordingHealthResponse)
def recording_health_server_observed(
    user_id: CurrentUser,
    db: DbSession,
) -> RecordingHealthResponse:
    # Mini/web-safe view: server evidence only. Native fields stay unavailable instead of
    # pretending the server can inspect the current Android/iOS runtime.
    return get_recording_health(db, user_id=user_id)


@router.post("/health", response_model=RecordingHealthResponse)
def recording_health_with_client_state(
    payload: RecordingClientState,
    user_id: CurrentUser,
    db: DbSession,
) -> RecordingHealthResponse:
    # No caller-supplied user_id exists in the contract. The authenticated owner is the only
    # authority; the client contributes privacy-safe local diagnostics, never coordinates/content.
    return get_recording_health(db, user_id=user_id, client_state=payload)
