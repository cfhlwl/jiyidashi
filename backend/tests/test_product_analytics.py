from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import analytics_report, analytics_retention
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
from app.core.observability import reset_request_id, set_request_id
from app.data_deletion_models import DataDeletionOperation
from app.models import SourceType, User
from app.schemas import Evidence, MemoryQueryResponse
from app.services.analytics_service import (
    analytics_report_payload,
    record_active_day_safe,
    record_retrieval_and_activity_safe,
    retention_aggregates,
    retrieval_aggregate,
)


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
        db.flush()
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
        db.flush()
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


def test_aggregate_report_contains_no_content_sentinels() -> None:
    engine = _engine()
    user_id = uuid4()
    sentinel = "private-query-email-coordinate-object-key-sentinel"
    with Session(engine) as db:
        db.add(
            User(
                id=user_id,
                nickname=sentinel,
                email=f"{sentinel}@example.test",
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        db.flush()
        db.add(
            RetrievalAnalyticsAttempt(
                user_id=user_id,
                operation_id=uuid4(),
                surface=RetrievalSurface.MEMORY_QUERY,
                outcome=RetrievalOutcome.SUCCESS,
                result_count=1,
                answerable_count=1,
                occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
            )
        )
        db.add(
            ProductActiveDay(
                user_id=user_id,
                activity_date_utc=date(2026, 7, 2),
            )
        )
        db.commit()
        payload = analytics_report_payload(
            db,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 2),
        )

    rendered = repr(payload)
    assert sentinel not in rendered
    assert str(user_id) not in rendered


def test_analytics_recording_failure_is_non_blocking_and_safe(monkeypatch) -> None:
    engine = _engine()
    user_id = uuid4()
    with Session(engine) as db:
        db.add(User(id=user_id, nickname="failure-safe"))
        db.commit()

    emitted: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.services.analytics_service._insert_active_day",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "app.services.analytics_service.emit_operational_event",
        lambda **kwargs: emitted.append(kwargs) or True,
    )

    source = _source(engine, user_id)
    try:
        record_active_day_safe(
            source,
            user_id=user_id,
            activity=ProductActivity.TIMELINE,
        )
    finally:
        source.close()

    assert emitted == [
        {
            "event": "analytics.recording.failed",
            "level": "WARNING",
            "error_code": "ANALYTICS_RECORDING_FAILED",
            "retryable": False,
        }
    ]


def test_report_cli_emits_aggregate_only_json(
    monkeypatch,
    capsys,
) -> None:
    engine = _engine()
    user_id = uuid4()
    sentinel = "report-private-sentinel"
    with Session(engine) as db:
        db.add(
            User(
                id=user_id,
                nickname=sentinel,
                email=f"{sentinel}@example.test",
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        db.flush()
        db.add(
            RetrievalAnalyticsAttempt(
                user_id=user_id,
                operation_id=uuid4(),
                surface=RetrievalSurface.MEMORY_QUERY,
                outcome=RetrievalOutcome.SUCCESS,
                result_count=1,
                answerable_count=1,
                occurred_at=datetime(2026, 7, 2, tzinfo=UTC),
            )
        )
        db.add(
            ProductActiveDay(
                user_id=user_id,
                activity_date_utc=date(2026, 7, 2),
            )
        )
        db.commit()

    monkeypatch.setattr(
        analytics_report,
        "SessionLocal",
        lambda: Session(engine),
    )
    assert (
        analytics_report.main(
            ["--from", "2026-07-01", "--to", "2026-07-02"]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"attempts":1' in output
    assert '"successes":1' in output
    assert sentinel not in output
    assert str(user_id) not in output


def test_retention_cli_prunes_old_rows_and_keeps_fresh(
    monkeypatch,
    capsys,
) -> None:
    engine = _engine()
    user_id = uuid4()
    now = datetime.now(UTC)
    old_day = (now - timedelta(days=100)).date()
    fresh_day = (now - timedelta(days=1)).date()

    with Session(engine) as db:
        db.add(User(id=user_id, nickname="retention-cli"))
        db.flush()
        db.add_all(
            [
                RetrievalAnalyticsAttempt(
                    user_id=user_id,
                    operation_id=uuid4(),
                    surface=RetrievalSurface.MEMORY_QUERY,
                    outcome=RetrievalOutcome.NO_EVIDENCE,
                    result_count=0,
                    answerable_count=0,
                    occurred_at=now - timedelta(days=100),
                ),
                RetrievalAnalyticsAttempt(
                    user_id=user_id,
                    operation_id=uuid4(),
                    surface=RetrievalSurface.MEMORY_QUERY,
                    outcome=RetrievalOutcome.SUCCESS,
                    result_count=1,
                    answerable_count=1,
                    occurred_at=now - timedelta(days=1),
                ),
                ProductActiveDay(
                    user_id=user_id,
                    activity_date_utc=old_day,
                ),
                ProductActiveDay(
                    user_id=user_id,
                    activity_date_utc=fresh_day,
                ),
            ]
        )
        db.commit()

    monkeypatch.setattr(
        analytics_retention,
        "SessionLocal",
        lambda: Session(engine),
    )
    assert (
        analytics_retention.main(
            ["--retrieval-days", "90", "--active-day-days", "90"]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "retrieval_deleted=1" in output
    assert "active_day_deleted=1" in output

    with Session(engine) as db:
        attempts = list(db.scalars(select(RetrievalAnalyticsAttempt)))
        active_days = list(db.scalars(select(ProductActiveDay)))
    assert len(attempts) == 1
    assert attempts[0].outcome == RetrievalOutcome.SUCCESS
    assert len(active_days) == 1
    assert active_days[0].activity_date_utc == fresh_day


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
