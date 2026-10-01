from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Place, Visit
from app.schemas import DayFootprintResponse, DayFootprintVisit
from app.services.time_service import user_day_bounds_utc, user_timezone_name

MAX_DAY_VISITS = 500


def _as_utc(value: datetime) -> datetime:
    # SQLite tests can round-trip timezone-aware DateTime as naive; production
    # PostgreSQL keeps the offset. Product ordering always treats DB-naive as UTC.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_day_footprint(
    db: Session,
    *,
    user_id: UUID,
    day: date,
) -> DayFootprintResponse:
    """Return one canonical owner-local day of Visit + Place evidence.

    Day boundaries come only from the authenticated owner's stored IANA timezone.
    A Visit is included when it overlaps the requested local day, not merely when
    its arrival timestamp has the same calendar date.
    """

    timezone_name = user_timezone_name(db, user_id)
    start_utc, end_utc = user_day_bounds_utc(db, user_id, day)
    zone = ZoneInfo(timezone_name)

    statement = (
        select(Visit, Place)
        .join(Place, Visit.place_id == Place.id)
        .where(
            Visit.user_id == user_id,
            Place.user_id == user_id,
            Visit.arrived_at < end_utc,
            or_(
                Visit.left_at.is_(None),
                Visit.left_at >= start_utc,
            ),
        )
        .order_by(Visit.arrived_at.asc(), Visit.id.asc())
        .limit(MAX_DAY_VISITS)
    )

    visits: list[DayFootprintVisit] = []
    for visit, place in db.execute(statement).all():
        arrived_at = _as_utc(visit.arrived_at)
        left_at = None if visit.left_at is None else _as_utc(visit.left_at)
        visits.append(
            DayFootprintVisit(
                id=visit.id,
                place_id=place.id,
                place_name=place.name,
                place_latitude=place.latitude,
                place_longitude=place.longitude,
                place_address=place.address,
                place_category=place.category,
                arrived_at=arrived_at,
                left_at=left_at,
                arrived_at_local=arrived_at.astimezone(zone),
                left_at_local=None if left_at is None else left_at.astimezone(zone),
                confidence=visit.confidence,
                visit_source=visit.source,
                visit_finalized=visit.finalized_at is not None,
            )
        )

    return DayFootprintResponse(
        timezone=timezone_name,
        day=day,
        empty=not visits,
        visits=visits,
    )
