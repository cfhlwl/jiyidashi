from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics_models import (
    ProductActiveDay,
    ProductActivity,
    RetrievalAnalyticsAttempt,
    RetrievalOutcome,
    RetrievalSurface,
)
from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    GuardedSession,
    UserDataAdmission,
)
from app.core.observability import current_request_id, emit_operational_event
from app.models import User
from app.schemas import MemoryQueryResponse

ANALYTICS_RECORDING_ERROR_CODE = "ANALYTICS_RECORDING_FAILED"
MAX_RESULT_COUNT = 10_000


@dataclass(frozen=True)
class RetrievalAggregate:
    attempts: int
    successes: int
    success_rate: float | None


@dataclass(frozen=True)
class RetentionAggregate:
    cohort_day: date
    cohort_users: int
    eligible_d1: int
    retained_d1: int
    d1_rate: float | None
    eligible_d7: int
    retained_d7: int
    d7_rate: float | None
    eligible_d30: int
    retained_d30: int
    d30_rate: float | None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def request_operation_id() -> UUID | None:
    value = current_request_id()
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _copy_admission(source: Session, target: GuardedSession) -> bool:
    admission = source.info.get(USER_DATA_ADMISSION_INFO_KEY)
    if not isinstance(admission, UserDataAdmission):
        return False
    target.info[USER_DATA_ADMISSION_INFO_KEY] = admission
    return True


def _emit_recording_failure() -> None:
    emit_operational_event(
        event="analytics.recording.failed",
        level="WARNING",
        error_code=ANALYTICS_RECORDING_ERROR_CODE,
        retryable=False,
    )


def _isolated_guarded_session(source: Session) -> GuardedSession | None:
    bind = source.get_bind()
    analytics = GuardedSession(bind=bind, expire_on_commit=False)
    if not _copy_admission(source, analytics):
        analytics.close()
        return None
    return analytics


def _insert_retrieval_attempt(
    db: Session,
    *,
    user_id: UUID,
    operation_id: UUID,
    surface: RetrievalSurface,
    outcome: RetrievalOutcome,
    result_count: int,
    answerable_count: int,
    occurred_at: datetime,
) -> None:
    if not (0 <= result_count <= MAX_RESULT_COUNT):
        raise ValueError("ANALYTICS_RESULT_COUNT_OUT_OF_RANGE")
    if not (0 <= answerable_count <= MAX_RESULT_COUNT):
        raise ValueError("ANALYTICS_ANSWERABLE_COUNT_OUT_OF_RANGE")

    row = RetrievalAnalyticsAttempt(
        user_id=user_id,
        operation_id=operation_id,
        surface=surface,
        outcome=outcome,
        result_count=result_count,
        answerable_count=answerable_count,
        occurred_at=_as_utc(occurred_at),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        # Same logical request replay is deliberately idempotent.
        pass


def _insert_active_day(
    db: Session,
    *,
    user_id: UUID,
    occurred_at: datetime,
) -> None:
    row = ProductActiveDay(
        user_id=user_id,
        activity_date_utc=_as_utc(occurred_at).date(),
        created_at=_as_utc(occurred_at),
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError:
        pass


def record_retrieval_and_activity_safe(
    source_db: Session,
    *,
    user_id: UUID,
    response: MemoryQueryResponse | None,
    failed: bool = False,
    occurred_at: datetime | None = None,
) -> None:
    operation_id = request_operation_id()
    if operation_id is None:
        _emit_recording_failure()
        return

    observed_at = _as_utc(occurred_at or datetime.now(UTC))
    if failed:
        outcome = RetrievalOutcome.FAILED
        result_count = 0
        answerable_count = 0
    else:
        if response is None:
            _emit_recording_failure()
            return
        success = (
            response.can_answer is True
            and bool(response.memory_ids)
            and bool(response.evidence)
        )
        outcome = RetrievalOutcome.SUCCESS if success else RetrievalOutcome.NO_EVIDENCE
        result_count = len(response.memory_ids)
        answerable_count = len(response.evidence)

    analytics = _isolated_guarded_session(source_db)
    if analytics is None:
        _emit_recording_failure()
        return
    try:
        _insert_retrieval_attempt(
            analytics,
            user_id=user_id,
            operation_id=operation_id,
            surface=RetrievalSurface.MEMORY_QUERY,
            outcome=outcome,
            result_count=result_count,
            answerable_count=answerable_count,
            occurred_at=observed_at,
        )
        _insert_active_day(
            analytics,
            user_id=user_id,
            occurred_at=observed_at,
        )
        analytics.commit()
    except Exception:
        analytics.rollback()
        _emit_recording_failure()
    finally:
        analytics.close()


def record_active_day_safe(
    source_db: Session,
    *,
    user_id: UUID,
    activity: ProductActivity,
    occurred_at: datetime | None = None,
) -> None:
    # activity is intentionally validated but not persisted: one row/user/day is enough.
    if not isinstance(activity, ProductActivity):
        _emit_recording_failure()
        return

    analytics = _isolated_guarded_session(source_db)
    if analytics is None:
        _emit_recording_failure()
        return
    try:
        _insert_active_day(
            analytics,
            user_id=user_id,
            occurred_at=occurred_at or datetime.now(UTC),
        )
        analytics.commit()
    except Exception:
        analytics.rollback()
        _emit_recording_failure()
    finally:
        analytics.close()


def retrieval_aggregate(
    db: Session,
    *,
    start_date: date,
    end_date: date,
) -> RetrievalAggregate:
    start = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    attempts = int(
        db.scalar(
            select(func.count(RetrievalAnalyticsAttempt.id)).where(
                RetrievalAnalyticsAttempt.surface == RetrievalSurface.MEMORY_QUERY,
                RetrievalAnalyticsAttempt.occurred_at >= start,
                RetrievalAnalyticsAttempt.occurred_at < end,
            )
        )
        or 0
    )
    successes = int(
        db.scalar(
            select(func.count(RetrievalAnalyticsAttempt.id)).where(
                RetrievalAnalyticsAttempt.surface == RetrievalSurface.MEMORY_QUERY,
                RetrievalAnalyticsAttempt.outcome == RetrievalOutcome.SUCCESS,
                RetrievalAnalyticsAttempt.occurred_at >= start,
                RetrievalAnalyticsAttempt.occurred_at < end,
            )
        )
        or 0
    )
    return RetrievalAggregate(
        attempts=attempts,
        successes=successes,
        success_rate=_safe_rate(successes, attempts),
    )


def retention_aggregates(
    db: Session,
    *,
    start_date: date,
    end_date: date,
) -> list[RetentionAggregate]:
    users = list(
        db.execute(
            select(User.id, User.created_at).where(
                User.created_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
                User.created_at < datetime.combine(
                    end_date + timedelta(days=1),
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
            )
        ).all()
    )
    cohorts: dict[date, list[UUID]] = {}
    for user_id, created_at in users:
        cohorts.setdefault(_as_utc(created_at).date(), []).append(user_id)

    output: list[RetentionAggregate] = []
    for cohort_day in sorted(cohorts):
        user_ids = cohorts[cohort_day]
        counts: dict[int, tuple[int, int]] = {}
        for offset in (1, 7, 30):
            target = cohort_day + timedelta(days=offset)
            eligible = len(user_ids) if target <= end_date else 0
            retained = 0
            if eligible:
                retained = int(
                    db.scalar(
                        select(func.count(func.distinct(ProductActiveDay.user_id))).where(
                            ProductActiveDay.user_id.in_(user_ids),
                            ProductActiveDay.activity_date_utc == target,
                        )
                    )
                    or 0
                )
            counts[offset] = (eligible, retained)
        output.append(
            RetentionAggregate(
                cohort_day=cohort_day,
                cohort_users=len(user_ids),
                eligible_d1=counts[1][0],
                retained_d1=counts[1][1],
                d1_rate=_safe_rate(counts[1][1], counts[1][0]),
                eligible_d7=counts[7][0],
                retained_d7=counts[7][1],
                d7_rate=_safe_rate(counts[7][1], counts[7][0]),
                eligible_d30=counts[30][0],
                retained_d30=counts[30][1],
                d30_rate=_safe_rate(counts[30][1], counts[30][0]),
            )
        )
    return output


def prune_analytics(
    db: Session,
    *,
    retrieval_days: int,
    active_day_days: int,
    now: datetime | None = None,
) -> tuple[int, int]:
    if not 31 <= retrieval_days <= 3650:
        raise ValueError("ANALYTICS_RETRIEVAL_RETENTION_DAYS_OUT_OF_RANGE")
    if not 31 <= active_day_days <= 3650:
        raise ValueError("ANALYTICS_ACTIVE_DAY_RETENTION_DAYS_OUT_OF_RANGE")
    if active_day_days < retrieval_days:
        raise ValueError("ANALYTICS_ACTIVE_DAY_RETENTION_MUST_NOT_BE_SHORTER")

    observed = _as_utc(now or datetime.now(UTC))
    retrieval_cutoff = observed - timedelta(days=retrieval_days)
    active_cutoff = (observed - timedelta(days=active_day_days)).date()
    retrieval_result = db.execute(
        delete(RetrievalAnalyticsAttempt).where(
            RetrievalAnalyticsAttempt.occurred_at < retrieval_cutoff
        )
    )
    active_result = db.execute(
        delete(ProductActiveDay).where(
            ProductActiveDay.activity_date_utc < active_cutoff
        )
    )
    db.commit()
    return int(retrieval_result.rowcount or 0), int(active_result.rowcount or 0)
