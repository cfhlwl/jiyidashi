"""Real PostgreSQL authority gates for NOTIFY-001A."""

from __future__ import annotations

import os
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text, update

from app.admin_models import AdminAccount, AdminRole
from app.core.db import SessionLocal, engine
from app.maintenance_job_models import MaintenanceJob, MaintenanceJobType
from app.models import Device, User
from app.notification_models import (
    NotificationAudienceType,
    NotificationCampaign,
    NotificationDelivery,
    NotificationDeliveryStatus,
    NotificationTargetPlatform,
    PushPlatform,
    PushProvider,
)
from app.notification_schemas import (
    AdminNotificationCampaignCreate,
    AdminNotificationCampaignSubmit,
    DevicePushRegistrationRequest,
)
from app.services import notification_service
from app.services.admin_security import hash_admin_password
from app.services.maintenance_jobs import (
    claim_next_maintenance_job,
    complete_maintenance_job,
    enqueue_maintenance_job,
)
from app.services.notification_provider import (
    NotificationProviderRequest,
    NotificationProviderResult,
    set_notification_provider_for_testing,
)
from app.services.notification_service import (
    _deliver_notification_attempt_under_handoff,
    begin_notification_delivery_attempt,
    campaign_confirmation_token,
    create_notification_campaign,
    finalize_notification_delivery_attempt,
    process_notification_delivery_claim,
    process_notification_fanout_claim,
    push_token_digest,
    register_device_push,
    submit_notification_campaign,
)

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def _user(label: str) -> User:
    row = User(nickname=f"notify-pg-{label}-{uuid4().hex[:8]}")
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    return row


def _admin() -> AdminAccount:
    row = AdminAccount(
        email=f"notify-pg-{uuid4()}@example.com",
        display_name="Notify PG",
        password_hash=hash_admin_password("Notify-PG-Password-123!"),
        role=AdminRole.OPERATOR.value,
        disabled=False,
        revision=0,
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    return row


def _register(
    user_id: UUID,
    *,
    client_uuid: str,
    token: str,
    platform: PushPlatform = PushPlatform.IOS,
):
    with SessionLocal() as db:
        return register_device_push(
            db,
            user_id=user_id,
            payload=DevicePushRegistrationRequest(
                client_uuid=client_uuid,
                platform=platform,
                provider=PushProvider.TEST,
                push_token=token,
                app_version="pg-1",
                os_version="pg-test",
            ),
        )


def _campaign_payload() -> AdminNotificationCampaignCreate:
    return AdminNotificationCampaignCreate.model_validate(
        {
            "message": {
                "category": "ADMIN",
                "title": "PostgreSQL 通知",
                "body": "NOTIFY-001A authority proof",
                "route_intent": "HOME",
                "source_type": "ADMIN",
            },
            "target": {
                "platform": NotificationTargetPlatform.ALL.value,
                "audience": NotificationAudienceType.ALL_ELIGIBLE_DEVICES.value,
                "user_ids": [],
                "device_ids": [],
            },
        }
    )


def _submitted_campaign(actor_id: UUID) -> NotificationCampaign:
    with SessionLocal() as db:
        actor = db.get(AdminAccount, actor_id)
        assert actor is not None
        campaign = create_notification_campaign(
            db,
            actor=actor,
            payload=_campaign_payload(),
        )
        confirmation = campaign_confirmation_token(db, campaign=campaign)
        campaign = submit_notification_campaign(
            db,
            actor=actor,
            campaign_id=campaign.id,
            payload=AdminNotificationCampaignSubmit(
                expected_revision=campaign.revision,
                confirmation_token=confirmation,
            ),
        )
        db.expunge(campaign)
        return campaign


def _cleanup_users(*user_ids: UUID) -> None:
    with SessionLocal() as db:
        db.execute(
            delete(MaintenanceJob).where(
                MaintenanceJob.job_type.in_(
                    (
                        MaintenanceJobType.NOTIFICATION_FANOUT.value,
                        MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                    )
                )
            )
        )
        for user_id in user_ids:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
        db.commit()


def _prove_legacy_token_migrates_inactive() -> None:
    _alembic("downgrade", "0035_sec017_human_alert_delivery")
    user_id = uuid4()
    device_id = uuid4()
    legacy_token = f"legacy-notify-{uuid4().hex}"
    now = datetime.now(UTC)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, nickname, timezone, locale, elder_mode_enabled,
                        created_at, updated_at
                    ) VALUES (
                        :id, 'notify-legacy', 'Asia/Shanghai', 'zh-CN', false,
                        :now, :now
                    )
                    """
                ),
                {"id": user_id, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO devices (
                        id, user_id, client_uuid, platform, push_token, created_at
                    ) VALUES (
                        :id, :user_id, :client_uuid, 'ios-legacy',
                        :push_token, :now
                    )
                    """
                ),
                {
                    "id": device_id,
                    "user_id": user_id,
                    "client_uuid": f"legacy-{uuid4().hex}",
                    "push_token": legacy_token,
                    "now": now,
                },
            )

        _alembic("upgrade", "head")

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT platform, push_token, push_provider, push_token_digest,
                           push_enabled, push_token_updated_at, push_invalidated_at
                    FROM devices
                    WHERE id = :id
                    """
                ),
                {"id": device_id},
            ).mappings().one()
            assert row.platform == "ios-legacy"
            assert row.push_token is None
            assert row.push_provider is None
            assert row.push_token_digest is None
            assert row.push_enabled is False
            assert row.push_token_updated_at is None
            assert row.push_invalidated_at is not None
    finally:
        _alembic("upgrade", "head")
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
                db.commit()


def _prove_concurrent_token_rebind_has_one_authority() -> None:
    first = _user("rebind-a")
    second = _user("rebind-b")
    token = f"shared-notify-token-{uuid4().hex}"
    digest = push_token_digest(token)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def bind(user_id: UUID, client_uuid: str) -> None:
        try:
            barrier.wait(timeout=5)
            _register(
                user_id,
                client_uuid=client_uuid,
                token=token,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(
            target=bind,
            args=(first.id, f"rebind-a-{uuid4().hex}"),
            daemon=True,
        ),
        threading.Thread(
            target=bind,
            args=(second.id, f"rebind-b-{uuid4().hex}"),
            daemon=True,
        ),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors, errors

    try:
        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(Device).where(
                        Device.user_id.in_((first.id, second.id))
                    )
                )
            )
            assert len(rows) == 2
            active = [
                row
                for row in rows
                if row.push_enabled
                and row.push_provider == PushProvider.TEST.value
                and row.push_token_digest == digest
            ]
            assert len(active) == 1
            inactive = [row for row in rows if row.id != active[0].id]
            assert len(inactive) == 1
            assert inactive[0].push_enabled is False
            assert inactive[0].push_token is None
            assert inactive[0].push_token_digest is None

            count = db.scalar(
                select(func.count(Device.id)).where(
                    Device.push_enabled.is_(True),
                    Device.push_provider == PushProvider.TEST.value,
                    Device.push_token_digest == digest,
                )
            )
            assert count == 1
    finally:
        _cleanup_users(first.id, second.id)


class _BlockingDisclosureAdapter:
    def __init__(
        self,
        *,
        entered: threading.Event,
        release: threading.Event,
    ) -> None:
        self.entered = entered
        self.release = release
        self.calls: list[UUID] = []

    def deliver(
        self,
        request: NotificationProviderRequest,
    ) -> NotificationProviderResult:
        self.calls.append(request.delivery_id)
        self.entered.set()
        if not self.release.wait(timeout=15):
            raise AssertionError("provider disclosure was not released")
        return NotificationProviderResult.accepted_result()


def _prove_token_rebind_waits_for_provider_disclosure_handoff() -> None:
    actor = _admin()
    owner_a = _user("handoff-a")
    owner_b = _user("handoff-b")
    token = f"notify-pg-handoff-{uuid4().hex}"
    digest = push_token_digest(token)
    device_a = _register(
        owner_a.id,
        client_uuid=f"handoff-a-{uuid4().hex}",
        token=token,
    )
    campaigns = [
        _submitted_campaign(actor.id),
        _submitted_campaign(actor.id),
    ]
    provider_entered = threading.Event()
    provider_release = threading.Event()
    rebind_done = threading.Event()
    errors: list[BaseException] = []
    adapter = _BlockingDisclosureAdapter(
        entered=provider_entered,
        release=provider_release,
    )

    try:
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type.in_(
                        (
                            MaintenanceJobType.NOTIFICATION_FANOUT.value,
                            MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        )
                    )
                )
            )
            db.commit()

        for index, campaign in enumerate(campaigns):
            with SessionLocal() as db:
                job, created = enqueue_maintenance_job(
                    db,
                    job_type=MaintenanceJobType.NOTIFICATION_FANOUT,
                    dedupe_key=f"notify-pg-handoff-fanout:{campaign.id}:{index}",
                    resource_key=f"notification-campaign:{campaign.id}",
                    payload={
                        "campaign_id": str(campaign.id),
                        "campaign_revision": campaign.revision,
                    },
                    max_attempts=3,
                    next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                assert created
                fanout_job_id = job.id
                db.commit()
            fanout_claim = _claim_exact_job(
                fanout_job_id,
                f"notify-pg-handoff-fanout-{index}-{uuid4().hex}",
            )
            process_notification_fanout_claim(fanout_claim)
            with SessionLocal() as db:
                assert complete_maintenance_job(
                    db,
                    job_id=fanout_claim.id,
                    claim_token=fanout_claim.claim_token,
                )
                db.commit()

        with SessionLocal() as db:
            delivery_jobs = list(
                db.scalars(
                    select(MaintenanceJob)
                    .where(
                        MaintenanceJob.job_type
                        == MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        MaintenanceJob.owner_user_id == owner_a.id,
                    )
                    .order_by(MaintenanceJob.created_at, MaintenanceJob.id)
                )
            )
            assert len(delivery_jobs) == 2
            first_job_id = delivery_jobs[0].id
            second_job_id = delivery_jobs[1].id

        first_claim = _claim_exact_job(
            first_job_id,
            f"notify-pg-handoff-first-{uuid4().hex}",
        )
        second_claim = _claim_exact_job(
            second_job_id,
            f"notify-pg-handoff-second-{uuid4().hex}",
        )
        second_attempt = begin_notification_delivery_attempt(second_claim)
        assert second_attempt is not None
        assert second_attempt.device_id == device_a.id
        assert second_attempt.token_digest == digest

        set_notification_provider_for_testing(
            platform=PushPlatform.IOS,
            provider=PushProvider.TEST,
            adapter=adapter,
        )

        def deliver_first() -> None:
            try:
                process_notification_delivery_claim(first_claim)
            except BaseException as exc:
                errors.append(exc)

        delivery_thread = threading.Thread(
            target=deliver_first,
            name="notify-disclosure-a",
            daemon=True,
        )
        delivery_thread.start()
        assert provider_entered.wait(timeout=10)

        def rebind_to_b() -> None:
            try:
                _register(
                    owner_b.id,
                    client_uuid=f"handoff-b-{uuid4().hex}",
                    token=token,
                )
            except BaseException as exc:
                errors.append(exc)
            finally:
                rebind_done.set()

        rebind_thread = threading.Thread(
            target=rebind_to_b,
            name="notify-rebind-b",
            daemon=True,
        )
        rebind_thread.start()

        # Ownership transition must not commit while A is still allowed to disclose T.
        assert not rebind_done.wait(timeout=0.25)

        provider_release.set()
        delivery_thread.join(timeout=15)
        rebind_thread.join(timeout=15)
        assert not delivery_thread.is_alive()
        assert not rebind_thread.is_alive()
        assert not errors, errors
        assert rebind_done.is_set()
        assert len(adapter.calls) == 1

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(Device).where(
                        Device.user_id.in_((owner_a.id, owner_b.id))
                    )
                )
            )
            active = [
                row
                for row in rows
                if row.push_enabled
                and row.push_provider == PushProvider.TEST.value
                and row.push_token_digest == digest
            ]
            assert len(active) == 1
            assert active[0].user_id == owner_b.id
            old = db.get(Device, device_a.id)
            assert old is not None
            assert old.push_enabled is False
            assert old.push_token is None
            assert old.push_token_digest is None

        # This attempt captured A's token before B completed the rebind. The
        # disclosure handoff must re-check authority and cancel it before provider I/O.
        result = _deliver_notification_attempt_under_handoff(second_attempt)
        assert result is None
        assert len(adapter.calls) == 1

        with SessionLocal() as db:
            second_delivery = db.get(
                NotificationDelivery,
                second_attempt.delivery_id,
            )
            assert second_delivery is not None
            assert second_delivery.status == NotificationDeliveryStatus.CANCELLED.value
            assert second_delivery.error_code == "DEVICE_PUSH_AUTHORITY_CHANGED"
            assert second_delivery.attempt_token is None
            assert second_delivery.revision == second_attempt.revision + 1

        stale, _ = finalize_notification_delivery_attempt(
            attempt=second_attempt,
            result=NotificationProviderResult.accepted_result(),
        )
        assert stale is False
    finally:
        provider_release.set()
        set_notification_provider_for_testing(
            platform=PushPlatform.IOS,
            provider=PushProvider.TEST,
            adapter=None,
        )
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type.in_(
                        (
                            MaintenanceJobType.NOTIFICATION_FANOUT.value,
                            MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        )
                    )
                )
            )
            for campaign in campaigns:
                saved = db.get(NotificationCampaign, campaign.id)
                if saved is not None:
                    message_id = saved.message_id
                    db.delete(saved)
                    db.flush()
                    from app.notification_models import NotificationMessage

                    message = db.get(NotificationMessage, message_id)
                    if message is not None:
                        db.delete(message)
            db.commit()
        _cleanup_users(owner_a.id, owner_b.id)


def _claim_exact_job(job_id: UUID, worker_id: str):
    # The shared CI database may have unrelated maintenance rows. Make this test's
    # job the earliest due notification work and claim only after other notify rows
    # are cleaned.
    with SessionLocal() as db:
        job = db.get(MaintenanceJob, job_id)
        assert job is not None
        job.next_attempt_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id=worker_id,
            lease_seconds=30,
        )
        assert claim is not None
        assert claim.id == job_id, (claim.id, job_id, claim.job_type)
        db.commit()
        return claim


def _prove_fanout_crash_reclaim_resumes_from_cursor() -> None:
    actor = _admin()
    users = [_user(f"reclaim-{index}") for index in range(3)]
    for index, user in enumerate(users):
        _register(
            user.id,
            client_uuid=f"pg-reclaim-{index}-{uuid4().hex}",
            token=f"pg-reclaim-token-{index}-{uuid4().hex}",
            platform=PushPlatform.IOS,
        )

    campaign = _submitted_campaign(actor.id)
    original_batch_size = notification_service.FANOUT_BATCH_SIZE
    notification_service.FANOUT_BATCH_SIZE = 1
    started_at = datetime.now(UTC)

    try:
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type.in_(
                        (
                            MaintenanceJobType.NOTIFICATION_FANOUT.value,
                            MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        )
                    )
                )
            )
            job, created = enqueue_maintenance_job(
                db,
                job_type=MaintenanceJobType.NOTIFICATION_FANOUT,
                dedupe_key=f"notify-pg-reclaim:{campaign.id}",
                resource_key=f"notification-campaign:{campaign.id}",
                payload={
                    "campaign_id": str(campaign.id),
                    "campaign_revision": campaign.revision,
                },
                max_attempts=3,
                next_attempt_at=started_at,
            )
            assert created
            job_id = job.id
            db.commit()

        with SessionLocal() as db:
            first_claim = claim_next_maintenance_job(
                db,
                worker_id=f"notify-pg-crash-a-{uuid4().hex}",
                lease_seconds=1,
                now=started_at,
            )
            assert first_claim is not None
            assert first_claim.id == job_id
            db.commit()

        # Commit one bounded page, then deliberately omit complete_maintenance_job:
        # this is the process-crash boundary between business progress and job ACK.
        process_notification_fanout_claim(first_claim)

        with SessionLocal() as db:
            first_campaign = db.get(NotificationCampaign, campaign.id)
            assert first_campaign is not None
            first_cursor = first_campaign.fanout_cursor_device_id
            assert first_cursor is not None
            first_deliveries = list(
                db.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.campaign_id == campaign.id
                    )
                )
            )
            assert len(first_deliveries) == 1
            first_device_id = first_deliveries[0].device_id

            # The committed page also created a continuation. Keep it out of the
            # artificial reclaim timestamp so claim_next must reclaim the crashed job.
            db.execute(
                update(MaintenanceJob)
                .where(
                    MaintenanceJob.job_type
                    == MaintenanceJobType.NOTIFICATION_FANOUT.value,
                    MaintenanceJob.id != job_id,
                )
                .values(next_attempt_at=started_at + timedelta(hours=1))
            )
            db.commit()

        with SessionLocal() as db:
            reclaimed = claim_next_maintenance_job(
                db,
                worker_id=f"notify-pg-crash-b-{uuid4().hex}",
                lease_seconds=30,
                now=started_at + timedelta(seconds=2),
            )
            assert reclaimed is not None
            assert reclaimed.id == job_id
            assert reclaimed.claim_token != first_claim.claim_token
            assert reclaimed.attempt_count == 2
            db.commit()

        process_notification_fanout_claim(reclaimed)
        with SessionLocal() as db:
            assert complete_maintenance_job(
                db,
                job_id=reclaimed.id,
                claim_token=reclaimed.claim_token,
            )
            db.commit()

        with SessionLocal() as db:
            resumed_campaign = db.get(NotificationCampaign, campaign.id)
            assert resumed_campaign is not None
            assert resumed_campaign.fanout_cursor_device_id is not None
            assert resumed_campaign.fanout_cursor_device_id != first_cursor

            deliveries = list(
                db.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.campaign_id == campaign.id
                    )
                )
            )
            assert len(deliveries) == 2
            assert len({row.device_id for row in deliveries}) == 2
            assert sum(row.device_id == first_device_id for row in deliveries) == 1
    finally:
        notification_service.FANOUT_BATCH_SIZE = original_batch_size
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type.in_(
                        (
                            MaintenanceJobType.NOTIFICATION_FANOUT.value,
                            MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        )
                    )
                )
            )
            saved = db.get(NotificationCampaign, campaign.id)
            if saved is not None:
                message_id = saved.message_id
                db.delete(saved)
                db.flush()
                from app.notification_models import NotificationMessage

                message = db.get(NotificationMessage, message_id)
                if message is not None:
                    db.delete(message)
            # AdminAudit is append-only in PostgreSQL. The actor FK uses SET NULL,
            # which correctly cannot mutate historical audit rows, so this disposable
            # integration database intentionally retains its random test admin.
            db.commit()
        _cleanup_users(*(user.id for user in users))


def _prove_two_worker_fanout_unique_and_stale_delivery_fenced() -> None:
    actor = _admin()
    users = [_user(f"fanout-{index}") for index in range(4)]
    device_ids: list[UUID] = []
    for index, user in enumerate(users):
        device = _register(
            user.id,
            client_uuid=f"pg-fanout-{index}-{uuid4().hex}",
            token=f"pg-fanout-token-{index}-{uuid4().hex}",
            platform=PushPlatform.IOS if index % 2 == 0 else PushPlatform.ANDROID,
        )
        device_ids.append(device.id)

    campaign = _submitted_campaign(actor.id)
    original_batch_size = notification_service.FANOUT_BATCH_SIZE
    notification_service.FANOUT_BATCH_SIZE = 2
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    try:
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type.in_(
                        (
                            MaintenanceJobType.NOTIFICATION_FANOUT.value,
                            MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        )
                    )
                )
            )
            db.commit()

        job_ids: list[UUID] = []
        with SessionLocal() as db:
            for suffix in ("a", "b"):
                job, created = enqueue_maintenance_job(
                    db,
                    job_type=MaintenanceJobType.NOTIFICATION_FANOUT,
                    dedupe_key=f"notify-pg-race:{campaign.id}:{suffix}",
                    resource_key=f"notification-campaign:{campaign.id}",
                    payload={
                        "campaign_id": str(campaign.id),
                        "campaign_revision": campaign.revision,
                    },
                    max_attempts=10,
                    next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                assert created
                job_ids.append(job.id)
            db.commit()

        claims = [
            _claim_exact_job(job_ids[0], f"notify-pg-a-{uuid4().hex}"),
            _claim_exact_job(job_ids[1], f"notify-pg-b-{uuid4().hex}"),
        ]

        def fanout(claim) -> None:
            try:
                barrier.wait(timeout=5)
                process_notification_fanout_claim(claim)
                with SessionLocal() as db:
                    complete_maintenance_job(
                        db,
                        job_id=claim.id,
                        claim_token=claim.claim_token,
                    )
                    db.commit()
            except BaseException as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=fanout, args=(claim,), daemon=True)
            for claim in claims
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert not errors, errors

        with SessionLocal() as db:
            deliveries = list(
                db.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.campaign_id == campaign.id
                    )
                )
            )
            assert len(deliveries) == 4
            assert len({row.device_id for row in deliveries}) == 4
            assert {row.device_id for row in deliveries} == set(device_ids)

            # Drop the harmless continuation fan-out job created by the first page so
            # the next claim is deterministically a delivery job.
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type
                    == MaintenanceJobType.NOTIFICATION_FANOUT.value
                )
            )
            delivery_job = db.scalar(
                select(MaintenanceJob)
                .where(
                    MaintenanceJob.job_type
                    == MaintenanceJobType.NOTIFICATION_DELIVERY.value
                )
                .order_by(MaintenanceJob.created_at, MaintenanceJob.id)
                .limit(1)
            )
            assert delivery_job is not None
            delivery_job_id = delivery_job.id
            db.commit()

        claim = _claim_exact_job(
            delivery_job_id,
            f"notify-pg-delivery-{uuid4().hex}",
        )
        attempt = begin_notification_delivery_attempt(claim)
        assert attempt is not None
        finalized, _ = finalize_notification_delivery_attempt(
            attempt=attempt,
            result=NotificationProviderResult.accepted_result(),
        )
        assert finalized is True
        stale, _ = finalize_notification_delivery_attempt(
            attempt=attempt,
            result=NotificationProviderResult.retryable_failure(
                "STALE_POSTGRES_ATTEMPT"
            ),
        )
        assert stale is False

        with SessionLocal() as db:
            delivery = db.get(NotificationDelivery, attempt.delivery_id)
            assert delivery is not None
            assert delivery.status == NotificationDeliveryStatus.ACCEPTED.value
            assert delivery.attempt_token is None
            assert delivery.revision == attempt.revision + 1
    finally:
        notification_service.FANOUT_BATCH_SIZE = original_batch_size
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type.in_(
                        (
                            MaintenanceJobType.NOTIFICATION_FANOUT.value,
                            MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        )
                    )
                )
            )
            saved = db.get(NotificationCampaign, campaign.id)
            if saved is not None:
                message_id = saved.message_id
                db.delete(saved)
                db.flush()
                from app.notification_models import NotificationMessage

                message = db.get(NotificationMessage, message_id)
                if message is not None:
                    db.delete(message)
            # AdminAudit is append-only in PostgreSQL. The actor FK uses SET NULL,
            # which correctly cannot mutate historical audit rows, so this disposable
            # integration database intentionally retains its random test admin.
            db.commit()
        _cleanup_users(*(user.id for user in users))


def _prove_final_account_delete_cascade_cannot_leave_delivery() -> None:
    actor = _admin()
    victim = _user("delete-race")
    survivor = _user("delete-survivor")
    _register(
        victim.id,
        client_uuid=f"victim-{uuid4().hex}",
        token=f"victim-token-{uuid4().hex}",
    )
    _register(
        survivor.id,
        client_uuid=f"survivor-{uuid4().hex}",
        token=f"survivor-token-{uuid4().hex}",
    )
    campaign = _submitted_campaign(actor.id)

    with SessionLocal() as db:
        db.execute(
            delete(MaintenanceJob).where(
                MaintenanceJob.job_type.in_(
                    (
                        MaintenanceJobType.NOTIFICATION_FANOUT.value,
                        MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                    )
                )
            )
        )
        job, created = enqueue_maintenance_job(
            db,
            job_type=MaintenanceJobType.NOTIFICATION_FANOUT,
            dedupe_key=f"notify-delete-race:{campaign.id}",
            resource_key=f"notification-campaign:{campaign.id}",
            payload={
                "campaign_id": str(campaign.id),
                "campaign_revision": campaign.revision,
            },
            max_attempts=10,
            next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert created
        job_id = job.id
        db.commit()

    claim = _claim_exact_job(
        job_id,
        f"notify-delete-race-{uuid4().hex}",
    )
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def fanout() -> None:
        try:
            barrier.wait(timeout=5)
            process_notification_fanout_claim(claim)
        except BaseException as exc:
            errors.append(exc)

    def delete_victim() -> None:
        try:
            barrier.wait(timeout=5)
            with SessionLocal() as db:
                row = db.get(User, victim.id)
                if row is not None:
                    db.delete(row)
                db.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=fanout, daemon=True),
        threading.Thread(target=delete_victim, daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors, errors

    try:
        with SessionLocal() as db:
            assert db.get(User, victim.id) is None
            assert (
                db.scalar(
                    select(func.count(Device.id)).where(
                        Device.user_id == victim.id
                    )
                )
                == 0
            )
            assert (
                db.scalar(
                    select(func.count(NotificationDelivery.id)).where(
                        NotificationDelivery.owner_user_id == victim.id
                    )
                )
                == 0
            )
    finally:
        with SessionLocal() as db:
            db.execute(
                delete(MaintenanceJob).where(
                    MaintenanceJob.job_type.in_(
                        (
                            MaintenanceJobType.NOTIFICATION_FANOUT.value,
                            MaintenanceJobType.NOTIFICATION_DELIVERY.value,
                        )
                    )
                )
            )
            saved = db.get(NotificationCampaign, campaign.id)
            if saved is not None:
                message_id = saved.message_id
                db.delete(saved)
                db.flush()
                from app.notification_models import NotificationMessage

                message = db.get(NotificationMessage, message_id)
                if message is not None:
                    db.delete(message)
            # AdminAudit is append-only in PostgreSQL. The actor FK uses SET NULL,
            # which correctly cannot mutate historical audit rows, so this disposable
            # integration database intentionally retains its random test admin.
            survivor_row = db.get(User, survivor.id)
            if survivor_row is not None:
                db.delete(survivor_row)
            db.commit()


def main() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("NOTIFY-001A PostgreSQL gate requires PostgreSQL")
    _alembic("upgrade", "head")
    _prove_legacy_token_migrates_inactive()
    _prove_concurrent_token_rebind_has_one_authority()
    _prove_token_rebind_waits_for_provider_disclosure_handoff()
    _prove_fanout_crash_reclaim_resumes_from_cursor()
    _prove_two_worker_fanout_unique_and_stale_delivery_fenced()
    _prove_final_account_delete_cascade_cannot_leave_delivery()
    _alembic("upgrade", "head")
    print("PostgreSQL NOTIFY-001A notification authority PASS")


if __name__ == "__main__":
    main()
