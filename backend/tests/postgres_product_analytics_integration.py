"""Real PostgreSQL gate for retrieval/retention analytics V1."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.analytics_models import (
    ProductActiveDay,
    ProductActivity,
    RetrievalAnalyticsAttempt,
    RetrievalOutcome,
    RetrievalSurface,
)
from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    SessionLocal,
    UserDataAdmission,
)
from app.core.observability import reset_request_id, set_request_id
from app.data_deletion_models import DataDeletionOperation
from app.models import User
from app.schemas import MemoryQueryResponse
from app.services.account_deletion_service import delete_current_account
from app.services.analytics_service import (
    record_active_day_safe,
    record_retrieval_and_activity_safe,
    retention_aggregates,
    retrieval_aggregate,
)
from app.services.data_deletion_service import delete_all_user_data


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _admit(db, user_id: UUID) -> None:
    existing = db.scalar(
        select(User.id).where(User.id == user_id).with_for_update(read=True, key_share=True)
    )
    assert existing == user_id
    generation = int(
        db.scalar(
            select(func.count(DataDeletionOperation.id)).where(
                DataDeletionOperation.user_id == user_id
            )
        )
        or 0
    )
    db.info[USER_DATA_ADMISSION_INFO_KEY] = UserDataAdmission(
        user_id=user_id,
        deletion_generation=generation,
    )


def _no_evidence() -> MemoryQueryResponse:
    return MemoryQueryResponse(
        answer=None,
        can_answer=False,
        certainty="unknown",
        reason="NO_EVIDENCE",
        intent="MEMORY_SEARCH",
        evidence=[],
        memory_ids=[],
    )


def _record_same_retrieval(user_id: UUID, operation_id: UUID) -> None:
    with SessionLocal() as source:
        _admit(source, user_id)
        token = set_request_id(str(operation_id))
        try:
            record_retrieval_and_activity_safe(
                source,
                user_id=user_id,
                response=_no_evidence(),
                occurred_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
            )
        finally:
            reset_request_id(token)
            source.rollback()


def _record_same_day(user_id: UUID) -> None:
    with SessionLocal() as source:
        _admit(source, user_id)
        try:
            record_active_day_safe(
                source,
                user_id=user_id,
                activity=ProductActivity.TIMELINE,
                occurred_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
            )
        finally:
            source.rollback()


def _cleanup_user(user_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def main() -> None:
    user_id = uuid4()
    operation_id = uuid4()
    with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                nickname="analytics-concurrency",
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )
        db.commit()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _record_same_retrieval(user_id, operation_id), range(8)))
    with SessionLocal() as db:
        attempts = list(
            db.scalars(
                select(RetrievalAnalyticsAttempt).where(
                    RetrievalAnalyticsAttempt.user_id == user_id
                )
            )
        )
        assert len(attempts) == 1, attempts
        assert attempts[0].outcome == RetrievalOutcome.NO_EVIDENCE

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: _record_same_day(user_id), range(8)))
    with SessionLocal() as db:
        active = list(
            db.scalars(
                select(ProductActiveDay).where(ProductActiveDay.user_id == user_id)
            )
        )
        assert len(active) == 1, active

        db.add(
            RetrievalAnalyticsAttempt(
                user_id=user_id,
                operation_id=uuid4(),
                surface=RetrievalSurface.MEMORY_QUERY,
                outcome=RetrievalOutcome.SUCCESS,
                result_count=1,
                answerable_count=1,
                occurred_at=datetime(2026, 9, 10, 13, tzinfo=UTC),
            )
        )
        db.add_all(
            [
                ProductActiveDay(
                    user_id=user_id,
                    activity_date_utc=date(2026, 9, 2),
                ),
                ProductActiveDay(
                    user_id=user_id,
                    activity_date_utc=date(2026, 9, 8),
                ),
            ]
        )
        db.commit()

        retrieval = retrieval_aggregate(
            db,
            start_date=date(2026, 9, 10),
            end_date=date(2026, 9, 10),
        )
        assert retrieval.attempts == 2
        assert retrieval.successes == 1
        assert retrieval.success_rate == 0.5

        retention = retention_aggregates(
            db,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )
        cohort = next(item for item in retention if item.cohort_day == date(2026, 9, 1))
        assert cohort.eligible_d1 == 1 and cohort.retained_d1 == 1
        assert cohort.eligible_d7 == 1 and cohort.retained_d7 == 1
        assert cohort.eligible_d30 == 0 and cohort.d30_rate is None

    d30_user = uuid4()
    with SessionLocal() as db:
        db.add(
            User(
                id=d30_user,
                nickname="analytics-d30",
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        db.add_all(
            [
                ProductActiveDay(
                    user_id=d30_user,
                    activity_date_utc=date(2026, 7, 2),
                ),
                ProductActiveDay(
                    user_id=d30_user,
                    activity_date_utc=date(2026, 7, 8),
                ),
                ProductActiveDay(
                    user_id=d30_user,
                    activity_date_utc=date(2026, 7, 31),
                ),
            ]
        )
        db.commit()
        retention = retention_aggregates(
            db,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )
        cohort = next(item for item in retention if item.cohort_day == date(2026, 7, 1))
        assert cohort.eligible_d1 == 1 and cohort.retained_d1 == 1
        assert cohort.eligible_d7 == 1 and cohort.retained_d7 == 1
        assert cohort.eligible_d30 == 1 and cohort.retained_d30 == 1
        assert cohort.d30_rate == 1.0

    delete_user = uuid4()
    with SessionLocal() as db:
        db.add(User(id=delete_user, nickname="analytics-data-delete"))
        db.add(
            RetrievalAnalyticsAttempt(
                user_id=delete_user,
                operation_id=uuid4(),
                surface=RetrievalSurface.MEMORY_QUERY,
                outcome=RetrievalOutcome.SUCCESS,
                result_count=1,
                answerable_count=1,
                occurred_at=datetime.now(UTC),
            )
        )
        db.add(
            ProductActiveDay(
                user_id=delete_user,
                activity_date_utc=datetime.now(UTC).date(),
            )
        )
        db.commit()

    stale_source = SessionLocal()
    try:
        _admit(stale_source, delete_user)
        stale_source.rollback()
        with SessionLocal() as deleting:
            result = delete_all_user_data(
                deleting,
                user_id=delete_user,
                request_id=uuid4(),
                storage=EmptyStorage(),
            )
            assert result.completed is True

        record_active_day_safe(
            stale_source,
            user_id=delete_user,
            activity=ProductActivity.TIMELINE,
        )
        token = set_request_id(str(uuid4()))
        try:
            record_retrieval_and_activity_safe(
                stale_source,
                user_id=delete_user,
                response=_no_evidence(),
            )
        finally:
            reset_request_id(token)

        with SessionLocal() as verify:
            assert (
                verify.scalar(
                    select(func.count(RetrievalAnalyticsAttempt.id)).where(
                        RetrievalAnalyticsAttempt.user_id == delete_user
                    )
                )
                == 0
            )
            assert (
                verify.scalar(
                    select(func.count(ProductActiveDay.id)).where(
                        ProductActiveDay.user_id == delete_user
                    )
                )
                == 0
            )
    finally:
        stale_source.close()

    account_user = uuid4()
    with SessionLocal() as db:
        db.add(User(id=account_user, nickname="analytics-account-delete"))
        db.add(
            ProductActiveDay(
                user_id=account_user,
                activity_date_utc=datetime.now(UTC).date(),
            )
        )
        db.commit()

    account_stale = SessionLocal()
    try:
        _admit(account_stale, account_user)
        account_stale.rollback()
        with SessionLocal() as deleting:
            result = delete_current_account(
                deleting,
                user_id=account_user,
                request_id=uuid4(),
                storage=EmptyStorage(),
                local_cleanup_ready=True,
            )
            assert result.completed is True

        record_active_day_safe(
            account_stale,
            user_id=account_user,
            activity=ProductActivity.TIMELINE,
        )
        with SessionLocal() as verify:
            assert verify.get(User, account_user) is None
            assert (
                verify.scalar(
                    select(func.count(ProductActiveDay.id)).where(
                        ProductActiveDay.user_id == account_user
                    )
                )
                == 0
            )
    finally:
        account_stale.close()

    _cleanup_user(user_id)
    _cleanup_user(d30_user)
    _cleanup_user(delete_user)
    print("PostgreSQL Retrieval & Retention Analytics PASS")


if __name__ == "__main__":
    main()
