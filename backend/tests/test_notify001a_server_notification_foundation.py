from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select

from app.admin_models import AdminAccount, AdminAuditEvent, AdminRole
from app.core.db import SessionLocal
from app.maintenance_adapters import (
    handle_notification_delivery,
    handle_notification_fanout,
)
from app.maintenance_job_models import MaintenanceJob, MaintenanceJobType
from app.maintenance_worker import MaintenanceWorker
from app.models import Device, User
from app.notification_models import (
    NotificationAudienceType,
    NotificationCampaign,
    NotificationCampaignStatus,
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
from app.services.export_service import generate_export_file, remove_temp_file
from app.services.notification_provider import (
    NotificationProviderResult,
    set_notification_provider_for_testing,
)
from app.services.notification_service import (
    begin_notification_delivery_attempt,
    campaign_confirmation_token,
    create_notification_campaign,
    eligible_device_counts,
    enqueue_due_notification_campaigns,
    finalize_notification_delivery_attempt,
    push_token_digest,
    register_device_push,
    submit_notification_campaign,
)


def _reset_notification_jobs() -> None:
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


def _user(nickname: str = "notify-user") -> User:
    row = User(nickname=f"{nickname}-{uuid4().hex[:8]}")
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    return row


def _admin(role: AdminRole = AdminRole.OPERATOR) -> AdminAccount:
    row = AdminAccount(
        email=f"notify-admin-{uuid4()}@example.com",
        display_name="Notify Admin",
        password_hash=hash_admin_password("Notify-Test-Password-123!"),
        role=role.value,
        disabled=False,
        revision=0,
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    return row


def _device(
    user_id: UUID,
    *,
    client_uuid: str,
    platform: PushPlatform,
    provider: PushProvider = PushProvider.TEST,
    token: str | None = None,
):
    raw_token = token or f"notify-token-{uuid4().hex}"
    with SessionLocal() as db:
        return register_device_push(
            db,
            user_id=user_id,
            payload=DevicePushRegistrationRequest(
                client_uuid=client_uuid,
                platform=platform,
                provider=provider,
                push_token=raw_token,
                app_version="1.2.3",
                os_version="test-os",
            ),
        )


def _campaign_payload(
    *,
    platform: NotificationTargetPlatform = NotificationTargetPlatform.ALL,
    audience: NotificationAudienceType = NotificationAudienceType.ALL_ELIGIBLE_DEVICES,
    user_ids: list[UUID] | None = None,
    device_ids: list[UUID] | None = None,
    expires_at: datetime | None = None,
) -> AdminNotificationCampaignCreate:
    return AdminNotificationCampaignCreate.model_validate(
        {
            "message": {
                "category": "ADMIN",
                "title": "系统通知",
                "body": "这是一条有界测试通知",
                "route_intent": "HOME",
                "source_type": "ADMIN",
                "expires_at": expires_at,
            },
            "target": {
                "platform": platform.value,
                "audience": audience.value,
                "user_ids": [str(item) for item in (user_ids or [])],
                "device_ids": [str(item) for item in (device_ids or [])],
            },
        }
    )


def _create_submitted_campaign(
    *,
    actor: AdminAccount,
    payload: AdminNotificationCampaignCreate,
    send_at: datetime | None = None,
) -> NotificationCampaign:
    with SessionLocal() as db:
        live_actor = db.get(AdminAccount, actor.id)
        assert live_actor is not None
        campaign = create_notification_campaign(
            db,
            actor=live_actor,
            payload=payload,
        )
        token = campaign_confirmation_token(db, campaign=campaign)
        campaign = submit_notification_campaign(
            db,
            actor=live_actor,
            campaign_id=campaign.id,
            payload=AdminNotificationCampaignSubmit(
                expected_revision=campaign.revision,
                confirmation_token=token,
                send_at=send_at,
            ),
        )
        db.expunge(campaign)
        return campaign


async def _login_admin(client, role: AdminRole) -> dict[str, str]:
    email = f"notify-{role.value.lower()}-{uuid4()}@example.com"
    password = "Notify-Admin-Password-123!"
    with SessionLocal() as db:
        db.add(
            AdminAccount(
                email=email,
                display_name="Notify Admin API",
                password_hash=hash_admin_password(password),
                role=role.value,
                disabled=False,
                revision=0,
            )
        )
        db.commit()
    response = await client.post(
        "/admin/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("jiyi_admin_csrf")
    assert csrf
    return {"X-CSRF-Token": csrf}


async def test_device_push_registration_rotation_rebind_unregister_and_redaction(client):
    first = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "notify-owner-one"},
    )
    assert first.status_code == 200
    first_body = first.json()
    first_user = UUID(first_body["user_id"])
    first_headers = {"Authorization": f"Bearer {first_body['access_token']}"}

    token_one = f"notify-token-{uuid4().hex}"
    payload = {
        "client_uuid": f"ios-{uuid4().hex}",
        "platform": "IOS",
        "provider": "TEST",
        "push_token": token_one,
        "app_version": "1.0.0",
        "os_version": "iOS-test",
    }
    registered = await client.put(
        "/v1/notifications/device",
        headers=first_headers,
        json=payload,
    )
    assert registered.status_code == 200, registered.text
    body = registered.json()
    assert "push_token" not in body
    assert "push_token_digest" not in body
    first_device_id = UUID(body["id"])

    with SessionLocal() as db:
        row = db.get(Device, first_device_id)
        assert row is not None
        assert row.user_id == first_user
        assert row.push_enabled is True
        assert row.push_token == token_one
        assert row.push_token_digest == push_token_digest(token_one)
        first_updated = row.push_token_updated_at
        row.device_name = "Preserve this history"
        db.commit()

    replay = await client.put(
        "/v1/notifications/device",
        headers=first_headers,
        json=payload,
    )
    assert replay.status_code == 200
    with SessionLocal() as db:
        row = db.get(Device, first_device_id)
        assert row is not None
        assert row.push_token_updated_at == first_updated

    token_two = f"notify-token-{uuid4().hex}"
    rotated_payload = dict(payload, push_token=token_two)
    rotated = await client.put(
        "/v1/notifications/device",
        headers=first_headers,
        json=rotated_payload,
    )
    assert rotated.status_code == 200
    with SessionLocal() as db:
        row = db.get(Device, first_device_id)
        assert row is not None
        assert row.push_token == token_two
        assert row.push_token_digest == push_token_digest(token_two)
        assert row.push_token_digest != push_token_digest(token_one)

    second = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": "notify-owner-two"},
    )
    assert second.status_code == 200
    second_body = second.json()
    second_headers = {"Authorization": f"Bearer {second_body['access_token']}"}

    cross_owner_delete = await client.delete(
        f"/v1/notifications/device/{payload['client_uuid']}",
        headers=second_headers,
    )
    assert cross_owner_delete.status_code == 404

    moved = await client.put(
        "/v1/notifications/device",
        headers=second_headers,
        json={
            **rotated_payload,
            "client_uuid": f"android-{uuid4().hex}",
            "platform": "ANDROID",
        },
    )
    assert moved.status_code == 200
    second_device_id = UUID(moved.json()["id"])
    with SessionLocal() as db:
        old = db.get(Device, first_device_id)
        current = db.get(Device, second_device_id)
        assert old is not None and current is not None
        assert old.push_enabled is False
        assert old.push_token is None
        assert old.push_token_digest is None
        assert current.push_enabled is True
        assert current.push_token == token_two

    bad_owner_body = await client.put(
        "/v1/notifications/device",
        headers=second_headers,
        json={
            **rotated_payload,
            "client_uuid": f"bad-owner-{uuid4().hex}",
            "platform": "ANDROID",
            "user_id": str(first_user),
        },
    )
    assert bad_owner_body.status_code == 422

    disabled = await client.delete(
        f"/v1/notifications/device/{moved.json()['client_uuid']}",
        headers=second_headers,
    )
    assert disabled.status_code == 200
    with SessionLocal() as db:
        row = db.get(Device, second_device_id)
        assert row is not None
        assert row.push_enabled is False
        assert row.push_token is None
        assert row.push_token_digest is None


def test_targeting_counts_match_eligible_devices_and_filters():
    actor = _admin()
    user_a = _user("target-a")
    user_b = _user("target-b")
    _device(
        user_a.id,
        client_uuid=f"ios-{uuid4().hex}",
        platform=PushPlatform.IOS,
    )
    android = _device(
        user_b.id,
        client_uuid=f"android-{uuid4().hex}",
        platform=PushPlatform.ANDROID,
    )
    disabled = _device(
        user_b.id,
        client_uuid=f"disabled-{uuid4().hex}",
        platform=PushPlatform.ANDROID,
    )
    with SessionLocal() as db:
        disabled_row = db.get(Device, disabled.id)
        assert disabled_row is not None
        disabled_row.push_enabled = False
        disabled_row.push_token = None
        disabled_row.push_token_digest = None
        disabled_row.push_invalidated_at = datetime.now(UTC)
        db.commit()

    cases = [
        (
            _campaign_payload(),
            (2, 1, 1),
        ),
        (
            _campaign_payload(platform=NotificationTargetPlatform.IOS),
            (1, 1, 0),
        ),
        (
            _campaign_payload(platform=NotificationTargetPlatform.ANDROID),
            (1, 0, 1),
        ),
        (
            _campaign_payload(
                audience=NotificationAudienceType.USER_IDS,
                user_ids=[user_a.id],
            ),
            (1, 1, 0),
        ),
        (
            _campaign_payload(
                audience=NotificationAudienceType.DEVICE_IDS,
                device_ids=[android.id, disabled.id],
            ),
            (1, 0, 1),
        ),
    ]

    with SessionLocal() as db:
        live_actor = db.get(AdminAccount, actor.id)
        assert live_actor is not None
        for payload, expected in cases:
            campaign = create_notification_campaign(
                db,
                actor=live_actor,
                payload=payload,
            )
            counts = eligible_device_counts(db, campaign=campaign)
            assert (counts.total, counts.ios, counts.android) == expected


async def test_admin_campaign_double_submit_schedule_cancel_and_audit(client):
    owner = _user("admin-target")
    _device(
        owner.id,
        client_uuid=f"ios-{uuid4().hex}",
        platform=PushPlatform.IOS,
    )

    support_headers = await _login_admin(client, AdminRole.SUPPORT_READONLY)
    payload = _campaign_payload().model_dump(mode="json")
    denied = await client.post(
        "/admin/api/v1/notifications/campaigns",
        headers=support_headers,
        json=payload,
    )
    assert denied.status_code == 403

    client.cookies.clear()
    operator_headers = await _login_admin(client, AdminRole.OPERATOR)
    created = await client.post(
        "/admin/api/v1/notifications/campaigns",
        headers=operator_headers,
        json=payload,
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]

    preview = await client.get(
        f"/admin/api/v1/notifications/campaigns/{campaign_id}/preview",
        headers=operator_headers,
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["eligible"]["total"] >= 1

    bad = await client.post(
        f"/admin/api/v1/notifications/campaigns/{campaign_id}/submit",
        headers=operator_headers,
        json={
            "expected_revision": preview_body["revision"],
            "confirmation_token": "x" * 64,
        },
    )
    assert bad.status_code == 409

    past = await client.post(
        f"/admin/api/v1/notifications/campaigns/{campaign_id}/submit",
        headers=operator_headers,
        json={
            "expected_revision": preview_body["revision"],
            "confirmation_token": preview_body["confirmation_token"],
            "send_at": (datetime.now(UTC) - timedelta(seconds=5)).isoformat(),
        },
    )
    assert past.status_code == 422

    future = datetime.now(UTC) + timedelta(minutes=10)
    scheduled = await client.post(
        f"/admin/api/v1/notifications/campaigns/{campaign_id}/submit",
        headers=operator_headers,
        json={
            "expected_revision": preview_body["revision"],
            "confirmation_token": preview_body["confirmation_token"],
            "send_at": future.isoformat(),
        },
    )
    assert scheduled.status_code == 200, scheduled.text
    scheduled_body = scheduled.json()
    assert scheduled_body["status"] == "SCHEDULED"

    duplicate = await client.post(
        f"/admin/api/v1/notifications/campaigns/{campaign_id}/submit",
        headers=operator_headers,
        json={
            "expected_revision": preview_body["revision"],
            "confirmation_token": preview_body["confirmation_token"],
        },
    )
    assert duplicate.status_code == 409

    cancelled = await client.post(
        f"/admin/api/v1/notifications/campaigns/{campaign_id}/cancel",
        headers=operator_headers,
        json={"expected_revision": scheduled_body["revision"]},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    with SessionLocal() as db:
        audits = list(
            db.scalars(
                select(AdminAuditEvent)
                .where(
                    AdminAuditEvent.target_type == "NOTIFICATION_CAMPAIGN",
                    AdminAuditEvent.target_id == campaign_id,
                )
                .order_by(AdminAuditEvent.created_at)
            )
        )
        actions = [row.action for row in audits]
        assert "NOTIFICATION_CAMPAIGN_CREATE" in actions
        assert "NOTIFICATION_CAMPAIGN_SCHEDULE" in actions
        assert "NOTIFICATION_CAMPAIGN_CANCEL" in actions
        rendered = json.dumps(
            [row.metadata_json for row in audits],
            ensure_ascii=False,
        )
        assert "notify-token-" not in rendered


def test_bounded_fanout_worker_delivery_and_stale_attempt_fencing(monkeypatch):
    _reset_notification_jobs()
    actor = _admin()
    owner = _user("fanout")
    devices = [
        _device(
            owner.id,
            client_uuid=f"fanout-{index}-{uuid4().hex}",
            platform=(
                PushPlatform.IOS
                if index % 2 == 0
                else PushPlatform.ANDROID
            ),
        )
        for index in range(3)
    ]
    monkeypatch.setattr(notification_service, "FANOUT_BATCH_SIZE", 2)
    campaign = _create_submitted_campaign(
        actor=actor,
        payload=_campaign_payload(),
    )

    with SessionLocal() as db:
        created, existing = enqueue_due_notification_campaigns(
            db,
            now=datetime.now(UTC),
            limit=20,
        )
        assert created == 1
        assert existing == 0
        db.commit()

    worker = MaintenanceWorker(
        worker_id=f"notify-test-{uuid4().hex}",
        handlers={
            MaintenanceJobType.NOTIFICATION_FANOUT.value: handle_notification_fanout,
            MaintenanceJobType.NOTIFICATION_DELIVERY.value: handle_notification_delivery,
        },
    )
    for _ in range(12):
        result = worker.run_once()
        if not result.claimed:
            break
    else:
        pytest.fail("notification worker did not drain bounded fanout")

    with SessionLocal() as db:
        deliveries = list(
            db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.campaign_id == campaign.id
                )
            )
        )
        assert len(deliveries) == 3
        assert len({row.device_id for row in deliveries}) == 3
        assert all(
            row.status == NotificationDeliveryStatus.ACCEPTED.value
            for row in deliveries
        )
        saved = db.get(NotificationCampaign, campaign.id)
        assert saved is not None
        assert saved.fanout_completed_at is not None
        assert saved.status == NotificationCampaignStatus.COMPLETED.value

    # Build a second campaign but claim/finalize one delivery manually so the exact
    # revision/token stale-attempt contract is proven independently from worker glue.
    _reset_notification_jobs()
    _create_submitted_campaign(
        actor=actor,
        payload=_campaign_payload(
            audience=NotificationAudienceType.DEVICE_IDS,
            device_ids=[devices[0].id],
        ),
    )
    with SessionLocal() as db:
        enqueue_due_notification_campaigns(
            db,
            now=datetime.now(UTC),
            limit=20,
        )
        db.commit()

    fanout_worker = MaintenanceWorker(
        worker_id=f"notify-fanout-{uuid4().hex}",
        handlers={
            MaintenanceJobType.NOTIFICATION_FANOUT.value: handle_notification_fanout,
        },
    )
    assert fanout_worker.run_once().outcome == "SUCCEEDED"

    from app.services.maintenance_jobs import claim_next_maintenance_job

    with SessionLocal() as db:
        claim = claim_next_maintenance_job(
            db,
            worker_id=f"notify-claim-{uuid4().hex}",
        )
        assert claim is not None
        assert claim.job_type == MaintenanceJobType.NOTIFICATION_DELIVERY.value
        db.commit()

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
            "STALE_MUST_NOT_WIN"
        ),
    )
    assert stale is False


class _InvalidTokenAdapter:
    def deliver(self, request):
        del request
        return NotificationProviderResult.terminal_failure(
            "INVALID_PROVIDER_TOKEN",
            invalid_token=True,
        )


class _ExplodingAdapter:
    def deliver(self, request):
        assert request.raw_token.startswith("notify-token-")
        raise RuntimeError("RAW_PROVIDER_SECRET_SENTINEL")


def test_terminal_invalid_token_and_provider_exception_are_bounded(monkeypatch):
    _reset_notification_jobs()
    actor = _admin()
    owner = _user("provider")
    device = _device(
        owner.id,
        client_uuid=f"provider-{uuid4().hex}",
        platform=PushPlatform.IOS,
    )

    set_notification_provider_for_testing(
        platform=PushPlatform.IOS,
        provider=PushProvider.TEST,
        adapter=_InvalidTokenAdapter(),
    )
    try:
        campaign = _create_submitted_campaign(
            actor=actor,
            payload=_campaign_payload(
                audience=NotificationAudienceType.DEVICE_IDS,
                device_ids=[device.id],
            ),
        )
        with SessionLocal() as db:
            enqueue_due_notification_campaigns(
                db,
                now=datetime.now(UTC),
                limit=20,
            )
            db.commit()
        worker = MaintenanceWorker(
            worker_id=f"notify-invalid-{uuid4().hex}",
            handlers={
                MaintenanceJobType.NOTIFICATION_FANOUT.value: handle_notification_fanout,
                MaintenanceJobType.NOTIFICATION_DELIVERY.value: handle_notification_delivery,
            },
        )
        assert worker.run_once().outcome == "SUCCEEDED"
        assert worker.run_once().outcome == "SUCCEEDED"

        with SessionLocal() as db:
            delivery = db.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.campaign_id == campaign.id
                )
            )
            current = db.get(Device, device.id)
            assert delivery is not None and current is not None
            assert delivery.status == NotificationDeliveryStatus.TERMINAL_FAILURE.value
            assert delivery.error_code == "INVALID_PROVIDER_TOKEN"
            assert current.push_enabled is False
            assert current.push_token is None
            assert current.push_token_digest is None
    finally:
        set_notification_provider_for_testing(
            platform=PushPlatform.IOS,
            provider=PushProvider.TEST,
            adapter=None,
        )

    # Re-register and prove raw provider exception text never persists.
    _device(
        owner.id,
        client_uuid=device.client_uuid,
        platform=PushPlatform.IOS,
    )
    _reset_notification_jobs()
    set_notification_provider_for_testing(
        platform=PushPlatform.IOS,
        provider=PushProvider.TEST,
        adapter=_ExplodingAdapter(),
    )
    try:
        campaign = _create_submitted_campaign(
            actor=actor,
            payload=_campaign_payload(
                audience=NotificationAudienceType.DEVICE_IDS,
                device_ids=[device.id],
            ),
        )
        with SessionLocal() as db:
            enqueue_due_notification_campaigns(
                db,
                now=datetime.now(UTC),
                limit=20,
            )
            db.commit()
        worker = MaintenanceWorker(
            worker_id=f"notify-explode-{uuid4().hex}",
            handlers={
                MaintenanceJobType.NOTIFICATION_FANOUT.value: handle_notification_fanout,
                MaintenanceJobType.NOTIFICATION_DELIVERY.value: handle_notification_delivery,
            },
        )
        assert worker.run_once().outcome == "SUCCEEDED"
        assert worker.run_once().outcome == "RETRY_WAIT"
        with SessionLocal() as db:
            delivery = db.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.campaign_id == campaign.id
                )
            )
            assert delivery is not None
            assert delivery.status == NotificationDeliveryStatus.RETRY_WAIT.value
            assert delivery.error_code == "NOTIFICATION_PROVIDER_EXCEPTION"
            assert "SENTINEL" not in (delivery.error_code or "")
    finally:
        set_notification_provider_for_testing(
            platform=PushPlatform.IOS,
            provider=PushProvider.TEST,
            adapter=None,
        )


def test_unconfigured_provider_and_expiry_never_false_accept():
    _reset_notification_jobs()
    actor = _admin()
    owner = _user("unconfigured")
    apns = _device(
        owner.id,
        client_uuid=f"apns-{uuid4().hex}",
        platform=PushPlatform.IOS,
        provider=PushProvider.APNS,
    )
    campaign = _create_submitted_campaign(
        actor=actor,
        payload=_campaign_payload(
            audience=NotificationAudienceType.DEVICE_IDS,
            device_ids=[apns.id],
        ),
    )
    with SessionLocal() as db:
        enqueue_due_notification_campaigns(
            db,
            now=datetime.now(UTC),
            limit=20,
        )
        db.commit()
    worker = MaintenanceWorker(
        worker_id=f"notify-unconfigured-{uuid4().hex}",
        handlers={
            MaintenanceJobType.NOTIFICATION_FANOUT.value: handle_notification_fanout,
            MaintenanceJobType.NOTIFICATION_DELIVERY.value: handle_notification_delivery,
        },
    )
    assert worker.run_once().outcome == "SUCCEEDED"
    assert worker.run_once().outcome == "SUCCEEDED"
    with SessionLocal() as db:
        delivery = db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.campaign_id == campaign.id
            )
        )
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.TERMINAL_FAILURE.value
        assert delivery.status != NotificationDeliveryStatus.ACCEPTED.value

    # Expiry is checked immediately before provider resolution/I/O.
    _reset_notification_jobs()
    test_device = _device(
        owner.id,
        client_uuid=f"ttl-{uuid4().hex}",
        platform=PushPlatform.IOS,
    )
    expiring = _create_submitted_campaign(
        actor=actor,
        payload=_campaign_payload(
            audience=NotificationAudienceType.DEVICE_IDS,
            device_ids=[test_device.id],
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
    )
    with SessionLocal() as db:
        message_id = db.get(NotificationCampaign, expiring.id).message_id
        from app.notification_models import NotificationMessage

        message = db.get(NotificationMessage, message_id)
        assert message is not None
        message.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        enqueue_due_notification_campaigns(
            db,
            now=datetime.now(UTC),
            limit=20,
        )
        db.commit()
    assert worker.run_once().outcome == "SUCCEEDED"
    assert worker.run_once().outcome == "SUCCEEDED"
    with SessionLocal() as db:
        delivery = db.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.campaign_id == expiring.id
            )
        )
        assert delivery is not None
        assert delivery.status == NotificationDeliveryStatus.EXPIRED.value


def test_data_export_never_contains_raw_push_token():
    owner = _user("export-redaction")
    raw_token = f"notify-token-{uuid4().hex}"
    _device(
        owner.id,
        client_uuid=f"export-{uuid4().hex}",
        platform=PushPlatform.IOS,
        token=raw_token,
    )
    generated = generate_export_file(
        owner_user_id=owner.id,
        authority_check=lambda: None,
    )
    try:
        body = open(generated.path, encoding="utf-8").read()
        assert raw_token not in body
        assert push_token_digest(raw_token) not in body
        assert '"devices"' not in body
    finally:
        remove_temp_file(generated.path)
