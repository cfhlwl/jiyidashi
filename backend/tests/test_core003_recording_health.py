from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from app.core.db import SessionLocal
from app.models import (
    LocationIngestReceipt,
    PrivacyPauseInterval,
    PrivacyState,
    User,
)
from app.schemas import RecordingClientState
from app.services.recording_health_service import get_recording_health
from app.services.time_service import user_day_bounds_utc


async def _new_user(client, nickname: str) -> tuple[dict[str, str], UUID]:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, UUID(body["user_id"])


def _set_timezone(user_id: UUID, timezone_name: str) -> None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        user.timezone = timezone_name
        db.commit()


def _add_receipt(
    user_id: UUID,
    *,
    client_uuid: str,
    recorded_at: datetime,
    created_at: datetime,
) -> None:
    with SessionLocal() as db:
        db.add(
            LocationIngestReceipt(
                user_id=user_id,
                client_uuid=client_uuid,
                payload_hash="a" * 64,
                recorded_at=recorded_at,
                created_at=created_at,
            )
        )
        db.commit()


def _client(now: datetime, **overrides) -> RecordingClientState:
    payload = {
        "observed_at": now,
        "platform": "android",
        "automatic_enabled": True,
        "permission_state": "BACKGROUND",
        "location_services_state": "ON",
        "background_runtime_state": "ELIGIBLE",
        "battery_optimization_state": "OPTIMIZED",
        "native_producer_state": "RUNNING",
        "native_queue_schema_version": 2,
        "native_queue_depth": 0,
        "native_queue_capacity": 1000,
        "native_queue_corrupt": False,
        "native_queue_storage_unavailable": False,
        "sqlite_queue_depth": 0,
        "capacity_pressure": False,
        "dropped_sample_count": 0,
        "last_fix_at": now - timedelta(minutes=1),
        "delivery_failure_count": 0,
        "recovery_pending": False,
    }
    payload.update(overrides)
    return RecordingClientState.model_validate(payload)


async def test_core003_healthy_requires_recent_capture_and_server_ack(client):
    _, user_id = await _new_user(client, "core003-healthy")
    _set_timezone(user_id, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _add_receipt(
        user_id,
        client_uuid="healthy-receipt",
        recorded_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=2),
    )

    with SessionLocal() as db:
        result = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now),
            reference_utc=now,
        )

    assert result.health.status == "HEALTHY"
    assert result.health.status_reason == "RECENT_CAPTURE_AND_ACK"
    assert result.health.last_server_ack_at == now - timedelta(minutes=2)
    assert result.health.capacity_pressure is False
    # Battery optimization is observable, not a green-state prerequisite.
    assert result.health.battery_optimization_state == "OPTIMIZED"


async def test_core003_client_cannot_mint_server_ack_or_cross_owner_state(client):
    _, owner_a = await _new_user(client, "core003-owner-a")
    _, owner_b = await _new_user(client, "core003-owner-b")
    _set_timezone(owner_a, "UTC")
    _set_timezone(owner_b, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _add_receipt(
        owner_b,
        client_uuid="owner-b-only",
        recorded_at=now - timedelta(minutes=2),
        created_at=now - timedelta(minutes=1),
    )

    with SessionLocal() as db:
        result = get_recording_health(
            db,
            user_id=owner_a,
            client_state=_client(now),
            reference_utc=now,
        )

    assert result.health.status == "UNKNOWN"
    assert result.health.status_reason == "NO_RECENT_ACK"
    assert result.health.last_server_ack_at is None
    assert result.today.trusted_location_sample_count == 0
    assert result.today.first_observed_at is None


async def test_core003_privacy_pause_is_paused_not_failure(client):
    _, user_id = await _new_user(client, "core003-paused")
    _set_timezone(user_id, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _add_receipt(
        user_id,
        client_uuid="paused-before",
        recorded_at=now - timedelta(hours=1),
        created_at=now - timedelta(hours=1),
    )
    with SessionLocal() as db:
        db.add(
            PrivacyState(
                user_id=user_id,
                recording_paused_since=now - timedelta(minutes=30),
                recording_paused_until=now + timedelta(minutes=30),
            )
        )
        db.add(
            PrivacyPauseInterval(
                user_id=user_id,
                started_at=now - timedelta(minutes=30),
                ended_at=now + timedelta(minutes=30),
            )
        )
        db.commit()
        result = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now),
            reference_utc=now,
        )

    assert result.health.status == "PAUSED"
    assert result.health.status_reason == "PRIVACY_PAUSED"
    assert result.health.privacy_paused is True
    assert any(gap.reason == "PRIVACY_PAUSED" for gap in result.recent_gaps)


async def test_core003_permission_and_location_services_block_exactly(client):
    _, user_id = await _new_user(client, "core003-blocked")
    _set_timezone(user_id, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _add_receipt(
        user_id,
        client_uuid="blocked-receipt",
        recorded_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=2),
    )

    with SessionLocal() as db:
        denied = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now, permission_state="DENIED"),
            reference_utc=now,
        )
        services_off = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now, location_services_state="OFF"),
            reference_utc=now,
        )

    assert denied.health.status == "BLOCKED"
    assert denied.health.status_reason == "PERMISSION_BLOCKED"
    assert services_off.health.status == "BLOCKED"
    assert services_off.health.status_reason == "LOCATION_SERVICES_OFF"


async def test_core003_backlog_capacity_and_recovery_are_deterministic(client):
    _, user_id = await _new_user(client, "core003-degraded")
    _set_timezone(user_id, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _add_receipt(
        user_id,
        client_uuid="degraded-receipt",
        recorded_at=now - timedelta(minutes=3),
        created_at=now - timedelta(minutes=2),
    )

    with SessionLocal() as db:
        capacity = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(
                now,
                native_queue_depth=850,
                capacity_pressure=True,
                dropped_sample_count=1,
            ),
            reference_utc=now,
        )
        backlog = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(
                now,
                sqlite_queue_depth=8,
                sqlite_oldest_pending_at=now - timedelta(hours=1),
                delivery_failure_count=4,
            ),
            reference_utc=now,
        )
        recovering = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(
                now,
                native_producer_state="STOPPED",
                recovery_pending=True,
            ),
            reference_utc=now,
        )

    assert capacity.health.status == "DEGRADED"
    assert capacity.health.status_reason == "QUEUE_CAPACITY_PRESSURE"
    assert capacity.today.has_capacity_pressure is True
    assert capacity.today.has_recorded_gap is True

    assert backlog.health.status == "DEGRADED"
    assert backlog.health.status_reason == "DELIVERY_BACKLOG"

    assert recovering.health.status == "RECOVERING"
    assert recovering.health.status_reason == "RECOVERY_PENDING"


async def test_core003_unavailable_or_stale_authority_never_turns_healthy(client):
    _, user_id = await _new_user(client, "core003-unknown")
    _set_timezone(user_id, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    _add_receipt(
        user_id,
        client_uuid="unknown-receipt",
        recorded_at=now - timedelta(minutes=2),
        created_at=now - timedelta(minutes=1),
    )

    with SessionLocal() as db:
        no_native = get_recording_health(
            db,
            user_id=user_id,
            reference_utc=now,
        )
        stale = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now - timedelta(minutes=10)),
            reference_utc=now,
        )

    assert no_native.health.status == "UNKNOWN"
    assert no_native.health.status_reason == "NATIVE_STATE_UNAVAILABLE"
    assert stale.health.status == "UNKNOWN"
    assert stale.health.status_reason == "CLIENT_STATE_STALE"

    with SessionLocal() as db:
        unknown_permission = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now, permission_state="UNKNOWN"),
            reference_utc=now,
        )
        unknown_runtime = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now, background_runtime_state="UNKNOWN"),
            reference_utc=now,
        )
        legacy_queue = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now, native_queue_schema_version=0),
            reference_utc=now,
        )
        missing_capacity = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now, native_queue_capacity=0),
            reference_utc=now,
        )

    for result in (
        unknown_permission,
        unknown_runtime,
        legacy_queue,
        missing_capacity,
    ):
        assert result.health.status == "UNKNOWN"
        assert result.health.status_reason == "NATIVE_STATE_UNAVAILABLE"


async def test_core003_sparse_observations_create_unknown_gap_without_route_fabrication(client):
    _, user_id = await _new_user(client, "core003-gaps")
    _set_timezone(user_id, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    for index, minute in enumerate((0, 10)):
        observed = datetime(2026, 10, 1, 2, minute, tzinfo=UTC)
        _add_receipt(
            user_id,
            client_uuid=f"gap-a-{index}",
            recorded_at=observed,
            created_at=observed + timedelta(seconds=5),
        )
    for index, minute in enumerate((0, 10)):
        observed = datetime(2026, 10, 1, 6, minute, tzinfo=UTC)
        _add_receipt(
            user_id,
            client_uuid=f"gap-b-{index}",
            recorded_at=observed,
            created_at=observed + timedelta(seconds=5),
        )

    with SessionLocal() as db:
        result = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(
                now,
                last_fix_at=now - timedelta(minutes=1),
            ),
            reference_utc=now,
        )

    assert result.today.trusted_location_sample_count == 4
    # Only the two 10-minute evidence intervals are counted as covered; the service does
    # not interpolate a four-hour raw route between sparse observations.
    assert result.today.covered_duration_seconds == 20 * 60
    unknown = [gap for gap in result.recent_gaps if gap.reason == "UNKNOWN"]
    assert len(unknown) == 1
    assert unknown[0].duration_seconds == 3 * 3600 + 50 * 60
    assert result.today.coverage_state == "GAPPED"


async def test_core003_privacy_interval_is_not_mislabeled_unknown(client):
    _, user_id = await _new_user(client, "core003-privacy-gap")
    _set_timezone(user_id, "UTC")
    now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    points = [
        datetime(2026, 10, 1, 2, 0, tzinfo=UTC),
        datetime(2026, 10, 1, 2, 10, tzinfo=UTC),
        datetime(2026, 10, 1, 6, 0, tzinfo=UTC),
        datetime(2026, 10, 1, 6, 10, tzinfo=UTC),
    ]
    for index, observed in enumerate(points):
        _add_receipt(
            user_id,
            client_uuid=f"privacy-gap-{index}",
            recorded_at=observed,
            created_at=observed + timedelta(seconds=5),
        )

    with SessionLocal() as db:
        db.add(
            PrivacyPauseInterval(
                user_id=user_id,
                started_at=datetime(2026, 10, 1, 2, 10, tzinfo=UTC),
                ended_at=datetime(2026, 10, 1, 6, 0, tzinfo=UTC),
            )
        )
        db.commit()
        result = get_recording_health(
            db,
            user_id=user_id,
            client_state=_client(now),
            reference_utc=now,
        )

    reasons = [gap.reason for gap in result.recent_gaps]
    assert reasons == ["PRIVACY_PAUSED"]
    assert result.today.known_gap_duration_seconds == 3 * 3600 + 50 * 60


async def test_core003_owner_local_day_and_dst_bounds(client):
    _, user_id = await _new_user(client, "core003-dst")
    _set_timezone(user_id, "America/New_York")

    with SessionLocal() as db:
        spring_start, spring_end = user_day_bounds_utc(db, user_id, date(2026, 3, 8))
        fall_start, fall_end = user_day_bounds_utc(db, user_id, date(2026, 11, 1))
        spring = get_recording_health(
            db,
            user_id=user_id,
            reference_utc=datetime(2026, 3, 8, 17, 0, tzinfo=UTC),
        )

    assert spring_end - spring_start == timedelta(hours=23)
    assert fall_end - fall_start == timedelta(hours=25)
    assert spring.today.local_day == date(2026, 3, 8)
    assert spring.today.timezone == "America/New_York"
    assert spring.today.coverage_state == "UNKNOWN"
    assert spring.today.covered_duration_seconds == 0
    assert spring.aggregates.evidence_days_7d == 0
    assert spring.aggregates.evidence_days_30d == 0
    assert spring.aggregates.gap_hours_7d is None
    assert spring.aggregates.gap_hours_30d is None
    assert spring.aggregates.bounded_gap_hours_7d == 0
    assert spring.aggregates.bounded_gap_hours_30d == 0


async def test_core003_api_is_owner_scoped_server_observed_and_rejects_raw_location(client):
    headers, _ = await _new_user(client, "core003-api")

    server_only = await client.get("/v1/recording/health", headers=headers)
    assert server_only.status_code == 200
    body = server_only.json()
    assert body["native_state_observed"] is False
    assert body["health"]["status"] == "UNKNOWN"
    assert body["health"]["permission_state"] is None
    assert body["health"]["native_producer_state"] is None

    malformed = await client.post(
        "/v1/recording/health",
        headers=headers,
        json={
            "observed_at": datetime.now(UTC).isoformat(),
            "platform": "android",
            "automatic_enabled": True,
            "permission_state": "BACKGROUND",
            "location_services_state": "ON",
            "background_runtime_state": "ELIGIBLE",
            "native_producer_state": "RUNNING",
            "latitude": 31.2304,
            "last_server_ack_at": datetime.now(UTC).isoformat(),
        },
    )
    assert malformed.status_code == 422

    caller_owner = await client.post(
        "/v1/recording/health",
        headers=headers,
        json={
            "observed_at": datetime.now(UTC).isoformat(),
            "platform": "android",
            "automatic_enabled": True,
            "permission_state": "BACKGROUND",
            "location_services_state": "ON",
            "background_runtime_state": "ELIGIBLE",
            "native_producer_state": "RUNNING",
            "user_id": str(uuid4()),
        },
    )
    assert caller_owner.status_code == 422
