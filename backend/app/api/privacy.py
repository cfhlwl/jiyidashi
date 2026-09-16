from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.schemas import PrivacyPauseRequest, PrivacyStatusResponse
from app.services import privacy_service
from app.services.time_service import local_today, user_day_bounds_utc

router = APIRouter(prefix="/privacy", tags=["privacy"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _response(state) -> PrivacyStatusResponse:
    return PrivacyStatusResponse(
        recording_paused=privacy_service.is_pause_active(state.recording_paused_until),
        paused_since=(
            privacy_service.ensure_utc(state.recording_paused_since)
            if state.recording_paused_since
            else None
        ),
        paused_until=(
            privacy_service.ensure_utc(state.recording_paused_until)
            if state.recording_paused_until
            else None
        ),
    )


@router.get("/status", response_model=PrivacyStatusResponse)
def privacy_status(user_id: CurrentUser, db: DbSession) -> PrivacyStatusResponse:
    return _response(privacy_service.get_privacy_state(db, user_id))


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

    state = privacy_service.pause_recording(db, user_id, started_at=now, ended_at=until)
    db.commit()
    db.refresh(state)
    return _response(state)


@router.post("/pause/today", response_model=PrivacyStatusResponse)
def pause_recording_until_today_ends(
    user_id: CurrentUser,
    db: DbSession,
) -> PrivacyStatusResponse:
    # [人工注释][S1-023] “今天”必须按用户 IANA timezone 计算日界线，
    # 并且 started_at 与 local day 必须来自同一个 UTC reference，避免午夜跨日竞态。
    now = datetime.now(UTC)
    local_day = local_today(db, user_id, reference_utc=now)
    _, end_of_local_day = user_day_bounds_utc(db, user_id, local_day)
    state = privacy_service.pause_recording(
        db,
        user_id,
        started_at=now,
        ended_at=end_of_local_day,
    )
    db.commit()
    db.refresh(state)
    return _response(state)


@router.post("/resume", response_model=PrivacyStatusResponse)
def resume_recording(user_id: CurrentUser, db: DbSession) -> PrivacyStatusResponse:
    # [人工注释][S1-024] 手动恢复只关闭当前 pause interval；历史暂停区间仍保留，
    # 因而暂停期间产生的自动位置点以后补传仍会被服务端拒绝。
    state = privacy_service.resume_recording(db, user_id, resumed_at=datetime.now(UTC))
    db.commit()
    db.refresh(state)
    return _response(state)
