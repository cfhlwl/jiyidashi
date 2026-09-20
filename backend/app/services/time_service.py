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


def user_timezone_name(db: Session, user_id: UUID) -> str:
    # [人工注释][S2-011] Timeline/Today 等产品层统一读取服务端 User.timezone；
    # 客户端不能在同一账号下自行选择另一套日界线。
    user = db.get(User, user_id)
    if user is None:
        return "UTC"
    try:
        ZoneInfo(user.timezone)
    except ZoneInfoNotFoundError:
        return "UTC"
    return user.timezone


def local_today(
    db: Session,
    user_id: UUID,
    reference_utc: datetime | None = None,
) -> date:
    # [人工注释][S1-023] 可注入同一个 reference timestamp，避免“暂停今天”跨本地午夜时
    # started_at 与 local day 分别读取系统时间而落到两个不同日期。
    reference = reference_utc or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return reference.astimezone(_user_zone(db, user_id)).date()


def user_day_bounds_utc(
    db: Session,
    user_id: UUID,
    day: date,
) -> tuple[datetime, datetime]:
    zone = _user_zone(db, user_id)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
