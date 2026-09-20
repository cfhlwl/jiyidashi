from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Place, Visit
from app.schemas import TodayFootprintResponse, TodayFootprintVisit
from app.services.time_service import (
    local_today,
    user_day_bounds_utc,
    user_timezone_name,
)


def _as_utc(value: datetime) -> datetime:
    # SQLite tests can round-trip timezone-aware DateTime as naive; production
    # PostgreSQL keeps the offset. Product ordering always treats DB-naive as UTC.
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_today_footprint(
    db: Session,
    *,
    user_id: UUID,
) -> TodayFootprintResponse:
    # [人工注释][S2-012] “今天”只由服务端账号时区决定；客户端不能提交 day。
    # Today Footprint 是区间产品投影：Visit 只要与今天窗口有重叠就必须出现。
    # S2-011 Timeline 仍保持 event-day(arrived_at) 语义，本服务不修改也不复用其 day filter。
    day = local_today(db, user_id)
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
    )

    visits: list[TodayFootprintVisit] = []
    for visit, place in db.execute(statement).all():
        arrived_at = _as_utc(visit.arrived_at)
        left_at = None if visit.left_at is None else _as_utc(visit.left_at)
        visits.append(
            TodayFootprintVisit(
                id=visit.id,
                place_id=place.id,
                place_name=place.name,
                arrived_at=arrived_at,
                left_at=left_at,
                arrived_at_local=arrived_at.astimezone(zone),
                left_at_local=None if left_at is None else left_at.astimezone(zone),
                confidence=visit.confidence,
                visit_source=visit.source,
                visit_finalized=visit.finalized_at is not None,
            )
        )

    return TodayFootprintResponse(
        timezone=timezone_name,
        day=day,
        visits=visits,
    )
