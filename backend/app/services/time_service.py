from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models import User


def _user_zone(db: Session, user_id: UUID) -> ZoneInfo:
    user = db.get(User, user_id)
    timezone_name = user.timezone if user else "UTC"
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def local_today(db: Session, user_id: UUID) -> date:
    return datetime.now(UTC).astimezone(_user_zone(db, user_id)).date()


def user_day_bounds_utc(
    db: Session,
    user_id: UUID,
    day: date,
) -> tuple[datetime, datetime]:
    zone = _user_zone(db, user_id)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
