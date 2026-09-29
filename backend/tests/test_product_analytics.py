from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.account_deletion_models import AccountDeletionOperation
from app.analytics_models import (
    ProductActiveDay,
    ProductActivity,
    RetrievalAnalyticsAttempt,
    RetrievalOutcome,
    RetrievalSurface,
)
from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    Base,
    GuardedSession,
    UserDataAdmission,
)
from app.data_deletion_models import DataDeletionOperation
from app.models import SourceType, User
from app.schemas import Evidence, MemoryQueryResponse
from app.services.analytics_service import (
    record_active_day_safe,
    record_retrieval_and_activity_safe,
    retention_aggregates,
    retrieval_aggregate,
)
from app.core.observability import reset_request_id, set_request_id


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            DataDeletionOperation.__table__,
            AccountDeletionOperation.__table__,
            RetrievalAnalyticsAttempt.__table__,
            ProductActiveDay.__table__,
        ],
    )
    return engine


def _source(engine, user_id):
    db = GuardedSession(bind=engine, expire_on_commit=False)
    db.info[USER_DATA_ADMISSION_INFO_KEY] = UserDataAdmission(
        user_id=user_id,
        deletion_generation=0,
    )
    return db


def test_memory_query_success_definition_and_privacy_minimization() -> None:
    engine = _engine()
    user_id = uuid4()
    operation_id = uuid4()
    sentinel = "query-secret-sentinel"
    with Session(engine) as db:
        db.add(User(id=user_id, nickname="analytics"))
        db.commit()

    evidence = Evidence(
        kind="MEMORY",
        id=uuid4(),
        source_type=SourceType.USER_TEXT,
        memory_source_id=uuid4(),
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        excerpt=sentinel,
        confidence=1.0,
    )
    response = MemoryQueryResponse(
        answer=f"answer-{sentinel}",
        can_answer=True,
        certainty="evidence",
        intent="MEMORY_SEARCH",
        evidence=[evidence],
        memory_ids=[uuid4()],
    )
    source = _source(engine, user_id)
    token = set_request_id(str(operation_id))
    try:
        record_retrieval_and_activity_safe(
            source,
            user_id=user_id,
            response=response,
            occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
    finally:
        reset_request_id(token)
        source.close()

    with Session(engine) as db:
        attempt = db.scalar(select(RetrievalAnalyticsAttempt))
        assert attempt is not None
        assert attempt.outcome == RetrievalOutcome.SUCCESS
        assert attempt.result_count == 1
        assert attempt.answerable_count == 1
        assert sentinel not in repr(attempt.__dict__)
        assert db.scalar(select(ProductActiveDay)) is not None


def test_no_evidence_is_denominator_but_not_success() -> None:
    engine = _engine()
    user_id = uuid4()
    with Session(engine) as db:
        db.add(
            User(
                id=user_id,
                nickname="analytics",
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )
        db.add(
            RetrievalAnalyticsAttempt(
                user_id=user_id,
                operation_id=uuid4(),
                surface=RetrievalSurface.MEMORY_QUERY,
                outcome=RetrievalOutcome.SUCCESS,
                result_count=1,
                answerable_count=1,
                occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
            )
        )
        db.add(
            RetrievalAnalyticsAttempt(
                user_id=user_id,
                operation_id=uuid4(),
                surface=RetrievalSurface.MEMORY_QUERY,
                outcome=RetrievalOutcome.NO_EVIDENCE,
                result_count=0,
                answerable_count=0,
                occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
            )
        )
        db.commit()
        result = retrieval_aggregate(
            db,
            start_date=date(2026, 9, 2),
            end_date=date(2026, 9, 2),
        )
    assert result.attempts == 2
    assert result.successes == 1
    assert result.success_rate == 0.5


def test_retention_uses_utc_signup_cohort_and_null_zero_denominator() -> None:
    engine = _engine()
    first = uuid4()
    late = uuid4()
    with Session(engine) as db:
        db.add_all(
            [
                User(
                    id=first,
                    nickname="first",
                    created_at=datetime(2026, 8, 1, 23, 30, tzinfo=UTC),
                ),
                User(
                    id=late,
                    nickname="late",
                    created_at=datetime(2026, 8, 31, 23, 30, tzinfo=UTC),
                ),
            ]
        )
        db.add_all(
            [
                ProductActiveDay(
                    user_id=first,
                    activity_date_utc=date(2026, 8, 2),
                ),
                ProductActiveDay(
                    user_id=first,
                    activity_date_utc=date(2026, 8, 8),
                ),
            ]
        )
        db.commit()
        rows = retention_aggregates(
            db,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )

    first_row = next(item for item in rows if item.cohort_day == date(2026, 8, 1))
    assert first_row.eligible_d1 == 1 and first_row.retained_d1 == 1
    assert first_row.d1_rate == 1.0
    assert first_row.eligible_d7 == 1 and first_row.retained_d7 == 1
    assert first_row.eligible_d30 == 1 and first_row.retained_d30 == 0
    late_row = next(item for item in rows if item.cohort_day == date(2026, 8, 31))
    assert late_row.eligible_d1 == 0
    assert late_row.d1_rate is None
    assert late_row.d7_rate is None
    assert late_row.d30_rate is None


def test_active_day_duplicate_is_idempotent() -> None:
    engine = _engine()
    user_id = uuid4()
    with Session(engine) as db:
        db.add(User(id=user_id, nickname="active"))
        db.commit()
    source = _source(engine, user_id)
    try:
        for _ in range(3):
            record_active_day_safe(
                source,
                user_id=user_id,
                activity=ProductActivity.TIMELINE,
                occurred_at=datetime(2026, 9, 29, 1, tzinfo=UTC),
            )
    finally:
        source.close()
    with Session(engine) as db:
        assert len(list(db.scalars(select(ProductActiveDay)))) == 1
