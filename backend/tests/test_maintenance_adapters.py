from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.analytics_models import (
    ProductActiveDay,
    RetrievalAnalyticsAttempt,
    RetrievalOutcome,
    RetrievalSurface,
)
from app.core.db import SessionLocal
from app.maintenance_adapters import (
    RetryableMaintenanceError,
    TerminalMaintenanceError,
    handle_analytics_retention,
    handle_media_pending_cleanup,
    handle_security_alert_delivery,
)
from app.maintenance_job_models import MaintenanceJob, MaintenanceJobStatus, MaintenanceJobType
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import User
from app.security_models import (
    SecurityAlert,
    SecurityAlertDeliveryStatus,
    SecuritySeverity,
    SecuritySignalCode,
)
from app.services import maintenance_adapters, security_alerting
from app.services.entitlement_service import storage_usage_bytes
from app.services.maintenance_jobs import (
    claim_next_maintenance_job,
    complete_maintenance_job,
    enqueue_maintenance_job,
    fail_maintenance_job,
)


class FakeCleanupStorage:
    def __init__(self, *keys: str):
        self.objects = set(keys)
        self.deleted: list[str] = []

    def delete_object(self, object_key: str) -> None:
        self.deleted.append(object_key)
        self.objects.discard(object_key)


def _enqueue_and_claim(
    *,
    job_type: MaintenanceJobType,
    dedupe_key: str,
    payload: dict,
    owner_user_id=None,
    max_attempts: int = 5,
):
    with SessionLocal() as db:
        job, created = enqueue_maintenance_job(
            db,
            job_type=job_type,
            dedupe_key=dedupe_key,
            owner_user_id=owner_user_id,
            payload=payload,
            max_attempts=max_attempts,
        )
        assert created
        job_id = job.id
        db.commit()

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id=f"test-worker:{uuid4().hex}",
        )
        assert claim is not None
        assert claim.id == job_id
        db.commit()
        return claim


@pytest.mark.asyncio
async def test_stale_pending_media_cleanup_waits_for_capability_and_releases_quota(
    client,
    monkeypatch,
):
    del client
    now = datetime.now(UTC)
    user_id = uuid4()
    active_media_id = uuid4()
    stale_media_id = uuid4()
    active_key = f"media/_staging/{user_id}/{active_media_id.hex}/active"
    stale_key = f"media/_staging/{user_id}/{stale_media_id.hex}/stale"
    storage = FakeCleanupStorage(active_key, stale_key)
    monkeypatch.setattr(
        maintenance_adapters,
        "get_object_storage",
        lambda: storage,
    )

    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="ops002-media-cleanup"))
        db.add_all(
            [
                MediaAsset(
                    id=active_media_id,
                    user_id=user_id,
                    client_upload_id=uuid4(),
                    kind=MediaKind.IMAGE,
                    status=MediaStatus.PENDING,
                    upload_object_key=active_key,
                    object_key=f"media/{user_id}/{active_media_id.hex}",
                    content_type="image/jpeg",
                    size_bytes=111,
                    upload_capability_expires_at=now + timedelta(minutes=10),
                    created_at=now - timedelta(hours=2),
                ),
                MediaAsset(
                    id=stale_media_id,
                    user_id=user_id,
                    client_upload_id=uuid4(),
                    kind=MediaKind.IMAGE,
                    status=MediaStatus.PENDING,
                    upload_object_key=stale_key,
                    object_key=f"media/{user_id}/{stale_media_id.hex}",
                    content_type="image/jpeg",
                    size_bytes=222,
                    upload_capability_expires_at=now - timedelta(minutes=10),
                    created_at=now - timedelta(hours=2),
                ),
            ]
        )
        db.commit()
        assert storage_usage_bytes(db, user_id=user_id) == 333

    active_claim = _enqueue_and_claim(
        job_type=MaintenanceJobType.MEDIA_PENDING_CLEANUP,
        dedupe_key=f"ops002-media-active:{active_media_id}",
        owner_user_id=user_id,
        payload={
            "media_id": str(active_media_id),
            "upload_object_key": active_key,
        },
    )
    with pytest.raises(RetryableMaintenanceError) as exc_info:
        handle_media_pending_cleanup(active_claim)
    assert exc_info.value.code == "MEDIA_CLEANUP_CAPABILITY_ACTIVE"

    with SessionLocal() as db:
        assert db.get(MediaAsset, active_media_id) is not None
        assert storage_usage_bytes(db, user_id=user_id) == 333
        db.execute(delete(MaintenanceJob).where(MaintenanceJob.id == active_claim.id))
        db.commit()
    assert active_key in storage.objects
    assert active_key not in storage.deleted

    stale_claim = _enqueue_and_claim(
        job_type=MaintenanceJobType.MEDIA_PENDING_CLEANUP,
        dedupe_key=f"ops002-media-stale:{stale_media_id}",
        owner_user_id=user_id,
        payload={
            "media_id": str(stale_media_id),
            "upload_object_key": stale_key,
        },
    )
    handle_media_pending_cleanup(stale_claim)
    with SessionLocal() as db:
        complete_maintenance_job(
            db,
            job_id=stale_claim.id,
            claim_token=stale_claim.claim_token,
            scrub_identity=True,
        )
        db.commit()

    with SessionLocal() as db:
        assert db.get(MediaAsset, stale_media_id) is None
        assert db.get(MediaAsset, active_media_id) is not None
        assert storage_usage_bytes(db, user_id=user_id) == 111
        db.execute(delete(MaintenanceJob).where(MaintenanceJob.id == stale_claim.id))
        db.execute(delete(MediaAsset).where(MediaAsset.user_id == user_id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()

    assert stale_key not in storage.objects
    assert stale_key in storage.deleted


@pytest.mark.asyncio
async def test_security_alert_worker_retries_transient_then_stops_after_success(
    client,
    monkeypatch,
):
    del client
    now = datetime.now(UTC)
    alert_id = uuid4()
    dedupe_key = uuid4().hex + uuid4().hex

    with SessionLocal() as db:
        db.add(
            SecurityAlert(
                id=alert_id,
                dedupe_key=dedupe_key,
                rule_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED.value,
                severity=SecuritySeverity.MEDIUM.value,
                correlation_digest="b" * 64,
                scope="AUTH_REGISTER_IP",
                window_started_at=now,
                window_seconds=600,
                signal_count=1,
                delivery_status=SecurityAlertDeliveryStatus.PENDING.value,
                delivery_attempts=0,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    monkeypatch.setattr(
        security_alerting,
        "emit_security_alert_event_checked",
        lambda **_: False,
    )
    first = _enqueue_and_claim(
        job_type=MaintenanceJobType.SECURITY_ALERT_DELIVERY,
        dedupe_key=f"ops002-alert:{alert_id}",
        payload={"alert_id": str(alert_id)},
        max_attempts=5,
    )
    with pytest.raises(RetryableMaintenanceError) as exc_info:
        handle_security_alert_delivery(first)
    assert exc_info.value.code == "SECURITY_ALERT_RETRYABLE_FAILURE"

    with SessionLocal() as db:
        alert = db.get(SecurityAlert, alert_id)
        assert alert is not None
        assert alert.delivery_status == SecurityAlertDeliveryStatus.RETRYABLE_FAILURE.value
        assert alert.delivery_attempts == 1
        status = fail_maintenance_job(
            db,
            job_id=first.id,
            claim_token=first.claim_token,
            error_code=exc_info.value.code,
            retry_after_seconds=1,
        )
        assert status == MaintenanceJobStatus.RETRY_WAIT.value
        alert.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        job = db.get(MaintenanceJob, first.id)
        assert job is not None
        job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    monkeypatch.setattr(
        security_alerting,
        "emit_security_alert_event_checked",
        lambda **_: True,
    )
    with SessionLocal() as db:
        second = claim_next_maintenance_job(
            db,
            worker_id="security-retry-worker",
        )
        assert second is not None
        assert second.id == first.id
        db.commit()

    handle_security_alert_delivery(second)
    with SessionLocal() as db:
        complete_maintenance_job(
            db,
            job_id=second.id,
            claim_token=second.claim_token,
        )
        db.commit()

    with SessionLocal() as db:
        alert = db.get(SecurityAlert, alert_id)
        assert alert is not None
        assert alert.delivery_status == SecurityAlertDeliveryStatus.DELIVERED.value
        assert alert.delivery_attempts == 2
        job = db.get(MaintenanceJob, second.id)
        assert job is not None
        assert job.status == MaintenanceJobStatus.SUCCEEDED.value
        db.execute(delete(MaintenanceJob).where(MaintenanceJob.id == second.id))
        db.execute(delete(SecurityAlert).where(SecurityAlert.id == alert_id))
        db.commit()


@pytest.mark.asyncio
async def test_security_alert_terminal_delivery_does_not_loop(
    client,
):
    del client
    now = datetime.now(UTC)
    alert_id = uuid4()
    with SessionLocal() as db:
        db.add(
            SecurityAlert(
                id=alert_id,
                dedupe_key=uuid4().hex + uuid4().hex,
                rule_code=SecuritySignalCode.AUTH_RATE_LIMIT_TRIGGERED.value,
                severity=SecuritySeverity.MEDIUM.value,
                correlation_digest="c" * 64,
                scope="AUTH_REGISTER_IP",
                window_started_at=now,
                window_seconds=600,
                signal_count=1,
                delivery_status=SecurityAlertDeliveryStatus.TERMINAL_FAILURE.value,
                delivery_attempts=security_alerting.MAX_DELIVERY_ATTEMPTS,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    claim = _enqueue_and_claim(
        job_type=MaintenanceJobType.SECURITY_ALERT_DELIVERY,
        dedupe_key=f"ops002-alert-terminal:{alert_id}",
        payload={"alert_id": str(alert_id)},
    )
    with pytest.raises(TerminalMaintenanceError) as exc_info:
        handle_security_alert_delivery(claim)
    assert exc_info.value.code == "SECURITY_ALERT_TERMINAL_FAILURE"

    with SessionLocal() as db:
        alert = db.get(SecurityAlert, alert_id)
        assert alert is not None
        assert alert.delivery_attempts == security_alerting.MAX_DELIVERY_ATTEMPTS
        db.execute(delete(MaintenanceJob).where(MaintenanceJob.id == claim.id))
        db.execute(delete(SecurityAlert).where(SecurityAlert.id == alert_id))
        db.commit()


@pytest.mark.asyncio
async def test_analytics_retention_job_is_bounded_and_resumable(
    client,
    monkeypatch,
):
    del client
    now = datetime.now(UTC)
    user_id = uuid4()
    operation_ids = [uuid4() for _ in range(3)]

    with SessionLocal() as db:
        db.add(User(id=user_id, nickname="ops002-analytics-retention"))
        for operation_id in operation_ids:
            db.add(
                RetrievalAnalyticsAttempt(
                    user_id=user_id,
                    operation_id=operation_id,
                    surface=RetrievalSurface.MEMORY_QUERY,
                    outcome=RetrievalOutcome.SUCCESS,
                    result_count=1,
                    answerable_count=1,
                    occurred_at=now - timedelta(days=90),
                )
            )
        for offset in range(3):
            db.add(
                ProductActiveDay(
                    user_id=user_id,
                    activity_date_utc=date.today() - timedelta(days=90 + offset),
                )
            )
        db.commit()

    monkeypatch.setattr(
        maintenance_adapters,
        "ANALYTICS_RETENTION_BATCH_SIZE",
        2,
    )
    first = _enqueue_and_claim(
        job_type=MaintenanceJobType.ANALYTICS_RETENTION,
        dedupe_key=f"ops002-analytics:{uuid4()}",
        payload={
            "retrieval_days": 31,
            "active_day_days": 31,
        },
        max_attempts=5,
    )
    with pytest.raises(RetryableMaintenanceError) as exc_info:
        handle_analytics_retention(first)
    assert exc_info.value.code == "ANALYTICS_RETENTION_CONTINUE"

    with SessionLocal() as db:
        remaining_retrieval = list(
            db.scalars(
                select(RetrievalAnalyticsAttempt).where(
                    RetrievalAnalyticsAttempt.user_id == user_id
                )
            )
        )
        remaining_active = list(
            db.scalars(
                select(ProductActiveDay).where(ProductActiveDay.user_id == user_id)
            )
        )
        assert len(remaining_retrieval) == 1
        assert len(remaining_active) == 1
        fail_maintenance_job(
            db,
            job_id=first.id,
            claim_token=first.claim_token,
            error_code=exc_info.value.code,
            retry_after_seconds=1,
        )
        job = db.get(MaintenanceJob, first.id)
        assert job is not None
        job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    with SessionLocal() as db:
        second = claim_next_maintenance_job(
            db,
            worker_id="analytics-retry-worker",
        )
        assert second is not None
        assert second.id == first.id
        db.commit()

    handle_analytics_retention(second)
    with SessionLocal() as db:
        complete_maintenance_job(
            db,
            job_id=second.id,
            claim_token=second.claim_token,
        )
        db.commit()

    with SessionLocal() as db:
        assert (
            db.scalar(
                select(RetrievalAnalyticsAttempt.id).where(
                    RetrievalAnalyticsAttempt.user_id == user_id
                )
            )
            is None
        )
        assert (
            db.scalar(
                select(ProductActiveDay.id).where(ProductActiveDay.user_id == user_id)
            )
            is None
        )
        db.execute(delete(MaintenanceJob).where(MaintenanceJob.id == second.id))
        db.execute(delete(User).where(User.id == user_id))
        db.commit()
