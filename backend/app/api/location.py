from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.deps import get_current_user_id
from app.models import LocationPoint
from app.schemas import LocationBatchRequest, LocationBatchResponse
from app.services.privacy_service import get_privacy_state, is_pause_active

router = APIRouter(prefix="/location", tags=["location"])


def _new_points(
    db: Session,
    user_id: UUID,
    payload: LocationBatchRequest,
) -> list[LocationPoint]:
    requested_ids = {point.client_uuid for point in payload.points}
    existing_ids = set(
        db.scalars(
            select(LocationPoint.client_uuid).where(
                LocationPoint.user_id == user_id,
                LocationPoint.client_uuid.in_(requested_ids),
            )
        ).all()
    )

    # Deduplicate the request itself as well as already persisted points.
    seen = set(existing_ids)
    rows: list[LocationPoint] = []
    for point in payload.points:
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
                recorded_at=point.recorded_at,
            )
        )
    return rows


@router.post("/batch", response_model=LocationBatchResponse)
def upload_location_batch(
    payload: LocationBatchRequest,
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> LocationBatchResponse:
    privacy = get_privacy_state(db, user_id)
    if is_pause_active(privacy.recording_paused_until):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RECORDING_PAUSED",
        )

    rows = _new_points(db, user_id, payload)
    if not rows:
        return LocationBatchResponse(accepted=0)

    db.add_all(rows)
    try:
        db.commit()
        return LocationBatchResponse(accepted=len(rows))
    except IntegrityError:
        # A concurrent retry may win after our pre-check. Roll back and
        # re-evaluate so the endpoint remains idempotent instead of returning 500.
        db.rollback()
        retry_rows = _new_points(db, user_id, payload)
        if not retry_rows:
            return LocationBatchResponse(accepted=0)
        db.add_all(retry_rows)
        db.commit()
        return LocationBatchResponse(accepted=len(retry_rows))
