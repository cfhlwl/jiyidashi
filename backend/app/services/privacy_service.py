from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import LocationDerivationState, PrivacyPauseInterval, PrivacyState

# 隐私暂停既有“当前状态”也有不可丢失的历史区间；延迟到达的数据必须按历史区间继续 fail closed。
# location derivation 与 privacy mutation 共用 owner 行锁，避免并发恢复/暂停与派生写入互相越过。


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_pause_active(paused_until: datetime | None) -> bool:
    if paused_until is None:
        return False
    return ensure_utc(paused_until) > datetime.now(UTC)


def lock_location_derivation_state(
    db: Session,
    user_id: UUID,
) -> LocationDerivationState:
    """Serialize one owner's location derivation and privacy mutations."""

    state = db.scalar(
        select(LocationDerivationState)
        .where(LocationDerivationState.user_id == user_id)
        .with_for_update()
    )
    if state is not None:
        return state

    candidate = LocationDerivationState(user_id=user_id)
    try:
        # [人工注释][S2-006][SEC-011] 首次请求可能并发创建 owner state；
        # SAVEPOINT 只吸收唯一键竞争，胜者提交后再锁同一行，privacy/location 共用此锁。
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate
    except IntegrityError:
        state = db.scalar(
            select(LocationDerivationState)
            .where(LocationDerivationState.user_id == user_id)
            .with_for_update()
        )
        if state is None:
            raise
        return state


def get_privacy_state(db: Session, user_id: UUID) -> PrivacyState:
    state = db.scalar(select(PrivacyState).where(PrivacyState.user_id == user_id))
    if state is None:
        state = PrivacyState(user_id=user_id)
        db.add(state)
        db.flush()
    return state


def pause_recording(
    db: Session,
    user_id: UUID,
    *,
    started_at: datetime,
    ended_at: datetime,
) -> PrivacyState:
    started_at = ensure_utc(started_at)
    ended_at = ensure_utc(ended_at)
    lock_location_derivation_state(db, user_id)
    state = get_privacy_state(db, user_id)

    if is_pause_active(state.recording_paused_until) and state.recording_paused_since:
        interval = db.scalar(
            select(PrivacyPauseInterval)
            .where(
                PrivacyPauseInterval.user_id == user_id,
                PrivacyPauseInterval.started_at == state.recording_paused_since,
            )
            .order_by(PrivacyPauseInterval.created_at.desc())
            .limit(1)
        )
        if interval is not None:
            interval.ended_at = max(ensure_utc(interval.ended_at or ended_at), ended_at)
            state.recording_paused_until = interval.ended_at
            return state

    state.recording_paused_since = started_at
    state.recording_paused_until = ended_at
    db.add(
        PrivacyPauseInterval(
            user_id=user_id,
            started_at=started_at,
            ended_at=ended_at,
        )
    )
    return state


def resume_recording(
    db: Session,
    user_id: UUID,
    *,
    resumed_at: datetime,
) -> PrivacyState:
    resumed_at = ensure_utc(resumed_at)
    lock_location_derivation_state(db, user_id)
    state = get_privacy_state(db, user_id)

    if state.recording_paused_since is not None:
        interval = db.scalar(
            select(PrivacyPauseInterval)
            .where(
                PrivacyPauseInterval.user_id == user_id,
                PrivacyPauseInterval.started_at == state.recording_paused_since,
            )
            .order_by(PrivacyPauseInterval.created_at.desc())
            .limit(1)
        )
        if interval is not None and (
            interval.ended_at is None or ensure_utc(interval.ended_at) > resumed_at
        ):
            interval.ended_at = resumed_at

    state.recording_paused_since = None
    state.recording_paused_until = None
    return state


def pause_intervals_for_range(
    db: Session,
    user_id: UUID,
    *,
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, datetime | None]]:
    start = ensure_utc(start)
    end = ensure_utc(end)
    # 查询 overlap 而不是只看当前 pause state：用户恢复后，历史暂停窗口仍是永久的数据接收边界。
    rows = db.scalars(
        select(PrivacyPauseInterval).where(
            PrivacyPauseInterval.user_id == user_id,
            PrivacyPauseInterval.started_at <= end,
            or_(
                PrivacyPauseInterval.ended_at.is_(None),
                PrivacyPauseInterval.ended_at > start,
            ),
        )
    ).all()
    return [
        (ensure_utc(row.started_at), ensure_utc(row.ended_at) if row.ended_at else None)
        for row in rows
    ]


def timestamp_in_pause_intervals(
    timestamp: datetime,
    intervals: list[tuple[datetime, datetime | None]],
) -> bool:
    timestamp = ensure_utc(timestamp)
    return any(
        started <= timestamp and (ended is None or timestamp < ended)
        for started, ended in intervals
    )
