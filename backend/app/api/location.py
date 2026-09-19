from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import LocationPoint
from app.schemas import LocationBatchRequest, LocationBatchResponse
from app.services.privacy_service import (
    ensure_utc,
    get_privacy_state,
    is_pause_active,
    pause_intervals_for_range,
    timestamp_in_pause_intervals,
)

router = APIRouter(prefix="/location", tags=["location"])
CurrentUser = Annotated[UUID, Depends(get_current_user_id)]
DbSession = Annotated[Session, Depends(get_db)]


def _new_points(
    db: Session,
    user_id: UUID,
    payload: LocationBatchRequest,
) -> tuple[list[LocationPoint], int]:
    requested_ids = {point.client_uuid for point in payload.points}
    existing_ids = set(
        db.scalars(
            select(LocationPoint.client_uuid).where(
                LocationPoint.user_id == user_id,
                LocationPoint.client_uuid.in_(requested_ids),
            )
        ).all()
    )

    # [人工注释][FND-023] 防御性地先统一到 UTC，再做 min/max 和暂停区间判断，避免时间类型混比。
    normalized_points = [(point, ensure_utc(point.recorded_at)) for point in payload.points]
    min_time = min(recorded_at for _, recorded_at in normalized_points)
    max_time = max(recorded_at for _, recorded_at in normalized_points)
    intervals = pause_intervals_for_range(
        db,
        user_id,
        start=min_time,
        end=max_time,
    )

    seen = set(existing_ids)
    rows: list[LocationPoint] = []
    rejected_privacy = 0
    for point, recorded_at in normalized_points:
        if timestamp_in_pause_intervals(recorded_at, intervals):
            rejected_privacy += 1
            continue
        if point.client_uuid in seen:
            continue
        seen.add(point.client_uuid)
        rows.append(
            LocationPoint(
                user_id=user_id,
                client_uuid=point.client_uuid,
                latitude=point.latitude,
                longitude=point.longitude,
                accuracy=point.accuracy,
                speed=point.speed,
                recorded_at=recorded_at,
            )
        )
    return rows, rejected_privacy


@router.post("/batch", response_model=LocationBatchResponse)
def upload_location_batch(
    payload: LocationBatchRequest,
    user_id: CurrentUser,
    db: DbSession,
) -> LocationBatchResponse:
    privacy = get_privacy_state(db, user_id)
    if is_pause_active(privacy.recording_paused_until):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RECORDING_PAUSED",
        )

    rows, rejected_privacy = _new_points(db, user_id, payload)
    if not rows:
        return LocationBatchResponse(accepted=0, rejected_privacy=rejected_privacy)

    try:
        # [人工注释][S1-021-FIX-001] 唯一键竞争只回滚 SAVEPOINT，不回滚请求入口
        # 的外层事务。这样 Location 自身不会主动释放 User KEY SHARE；即使未来别的
        # 路径跨 transaction，GuardedSession generation gate 仍在每次 commit 前兜底。
        with db.begin_nested():
            db.add_all(rows)
            db.flush()
        db.commit()
        return LocationBatchResponse(
            accepted=len(rows),
            rejected_privacy=rejected_privacy,
        )
    except IntegrityError:
        retry_rows, retry_rejected = _new_points(db, user_id, payload)
        if not retry_rows:
            return LocationBatchResponse(accepted=0, rejected_privacy=retry_rejected)
        db.add_all(retry_rows)
        db.commit()
        return LocationBatchResponse(
            accepted=len(retry_rows),
            rejected_privacy=retry_rejected,
        )
