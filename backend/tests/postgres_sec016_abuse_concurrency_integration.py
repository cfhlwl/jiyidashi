"""Real PostgreSQL SEC-016 abuse/concurrency authority gate."""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock, Thread
from time import monotonic, sleep
from uuid import UUID, uuid4

from sqlalchemy import delete, inspect, select, text

from app.abuse_models import ConcurrencyGuard, WorkPermit
from app.auth_models import AuthRateLimitBucket
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import User
from app.services import auth_rate_limit
from app.services.auth_rate_limit import (
    ApiRouteClass,
    consume_authenticated_api_attempt,
)
from app.services.concurrency_guard import (
    ConcurrencyRejected,
    claim_argon2_permit,
    claim_image_preprocess_permit,
    claim_provider_permit,
    maintain_permit_lease,
    release_permit,
    renew_permit,
)

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def _seed_user(label: str) -> UUID:
    user_id = uuid4()
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"sec016-{label}"))
        db.commit()
    return user_id


def _cleanup(*user_ids: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(WorkPermit))
        db.execute(delete(ConcurrencyGuard))
        db.execute(
            delete(AuthRateLimitBucket).where(
                AuthRateLimitBucket.scope.like("api_%")
            )
        )
        for user_id in user_ids:
            db.execute(delete(User).where(User.id == user_id))
        db.commit()


def _prove_migration_roundtrip() -> None:
    _alembic("downgrade", "0030_provider_configuration")
    inspector = inspect(engine)
    assert not inspector.has_table("work_permits")
    assert not inspector.has_table("concurrency_guards")
    _alembic("upgrade", "head")
    inspector = inspect(engine)
    assert inspector.has_table("work_permits")
    assert inspector.has_table("concurrency_guards")


def _provider_settings(*, global_limit: int, user_limit: int):
    return get_settings().model_copy(
        update={
            "provider_ai_global_concurrency": global_limit,
            "provider_ai_user_concurrency": user_limit,
            "provider_permit_lease_seconds": 5,
        }
    )


def _race_claim(
    user_ids: tuple[UUID, UUID],
    *,
    global_limit: int,
    user_limit: int,
) -> tuple[list, list[str]]:
    settings = _provider_settings(
        global_limit=global_limit,
        user_limit=user_limit,
    )
    barrier = Barrier(2)
    lock = Lock()
    permits = []
    denials: list[str] = []
    errors: list[BaseException] = []

    def worker(user_id: UUID) -> None:
        try:
            barrier.wait(timeout=10)
            permit = claim_provider_permit(
                engine,
                service_class="AI",
                user_id=user_id,
                settings=settings,
            )
            with lock:
                permits.append(permit)
        except ConcurrencyRejected as exc:
            with lock:
                denials.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [
        Thread(target=worker, args=(user_ids[0],), name="sec016-race-a"),
        Thread(target=worker, args=(user_ids[1],), name="sec016-race-b"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]
    return permits, denials


def _prove_provider_races(user_a: UUID, user_b: UUID) -> None:
    permits, denials = _race_claim(
        (user_a, user_b),
        global_limit=1,
        user_limit=1,
    )
    assert len(permits) == 1
    assert denials == ["PROVIDER_CONCURRENCY_SATURATED"]
    assert release_permit(engine, permit=permits[0]) is True

    permits, denials = _race_claim(
        (user_a, user_a),
        global_limit=2,
        user_limit=1,
    )
    assert len(permits) == 1
    assert denials == ["PROVIDER_CONCURRENCY_SATURATED"]
    assert release_permit(engine, permit=permits[0]) is True

    settings = _provider_settings(global_limit=2, user_limit=1)
    first = claim_provider_permit(
        engine,
        service_class="AI",
        user_id=user_a,
        settings=settings,
    )
    second = claim_provider_permit(
        engine,
        service_class="AI",
        user_id=user_b,
        settings=settings,
    )
    try:
        try:
            claim_provider_permit(
                engine,
                service_class="AI",
                user_id=uuid4(),
                settings=settings,
            )
        except ConcurrencyRejected as exc:
            assert exc.code == "PROVIDER_CONCURRENCY_SATURATED"
        else:
            raise AssertionError("global provider cap did not reject")
    finally:
        release_permit(engine, permit=first, settings=settings)
        release_permit(engine, permit=second, settings=settings)


def _prove_image_preprocess_cross_worker_budget(
    user_a: UUID,
    user_b: UUID,
) -> None:
    settings = get_settings().model_copy(
        update={
            "ai_image_preprocess_global_concurrency": 2,
            "ai_image_preprocess_user_concurrency": 1,
            "ai_image_preprocess_permit_lease_seconds": 5,
        }
    )
    barrier = Barrier(3)
    lock = Lock()
    permits = []
    denials: list[str] = []
    errors: list[BaseException] = []

    def worker(user_id: UUID) -> None:
        try:
            barrier.wait(timeout=10)
            permit = claim_image_preprocess_permit(
                engine,
                user_id=user_id,
                settings=settings,
            )
            with lock:
                permits.append(permit)
        except ConcurrencyRejected as exc:
            with lock:
                denials.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    users = (user_a, user_b, uuid4())
    threads = [
        Thread(target=worker, args=(user_id,), name=f"media-preprocess-{index}")
        for index, user_id in enumerate(users)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]

    assert len(permits) == 2
    assert denials == ["AI_IMAGE_PREPROCESS_SATURATED"]
    assert {permit.service_class for permit in permits} == {"AI_IMAGE_PREPROCESS"}
    for permit in permits:
        assert release_permit(engine, permit=permit, settings=settings) is True

    # OCR and Vision call the same helper/service class, so an occupied global slot
    # cannot be bypassed by changing inference surface.
    settings_one = settings.model_copy(
        update={
            "ai_image_preprocess_global_concurrency": 1,
            "ai_image_preprocess_user_concurrency": 1,
        }
    )
    occupied = claim_image_preprocess_permit(
        engine,
        user_id=user_a,
        settings=settings_one,
    )
    try:
        try:
            claim_image_preprocess_permit(
                engine,
                user_id=user_b,
                settings=settings_one,
            )
        except ConcurrencyRejected as exc:
            assert exc.code == "AI_IMAGE_PREPROCESS_SATURATED"
        else:
            raise AssertionError("shared image preprocessing cap did not reject")
    finally:
        assert release_permit(engine, permit=occupied, settings=settings_one) is True


def _preprocess_settings(*, global_limit: int, user_limit: int, lease_seconds: int):
    return get_settings().model_copy(
        update={
            "ai_image_preprocess_global_concurrency": global_limit,
            "ai_image_preprocess_user_concurrency": user_limit,
            "ai_image_preprocess_permit_lease_seconds": lease_seconds,
        }
    )


def _prove_preprocess_renewal_token_binding(user_a: UUID, user_b: UUID) -> None:
    settings = _preprocess_settings(global_limit=1, user_limit=1, lease_seconds=5)
    first = claim_image_preprocess_permit(
        engine,
        user_id=user_a,
        settings=settings,
    )
    forged = replace(first, token=first.token + "-forged")
    assert (
        renew_permit(
            engine,
            permit=forged,
            lease_seconds=5,
            settings=settings,
        )
        is None
    )

    with SessionLocal() as db:
        row = db.get(WorkPermit, first.permit_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert (
        renew_permit(
            engine,
            permit=first,
            lease_seconds=5,
            settings=settings,
        )
        is None
    )
    assert release_permit(engine, permit=first, settings=settings) is True

    replacement = claim_image_preprocess_permit(
        engine,
        user_id=user_b,
        settings=settings,
    )
    assert (
        renew_permit(
            engine,
            permit=first,
            lease_seconds=5,
            settings=settings,
        )
        is None
    )
    assert release_permit(engine, permit=replacement, settings=settings) is True


async def _prove_preprocess_heartbeat_lifecycle(
    user_a: UUID,
    user_b: UUID,
) -> None:
    settings = _preprocess_settings(global_limit=1, user_limit=1, lease_seconds=2)
    first = await asyncio.to_thread(
        claim_image_preprocess_permit,
        engine,
        user_id=user_a,
        settings=settings,
    )
    async with maintain_permit_lease(
        engine,
        permit=first,
        lease_seconds=2,
        settings=settings,
    ):
        # Hold real work beyond the original lease. Heartbeat renewals must keep
        # this slot authoritative across multiple PostgreSQL transactions.
        await asyncio.sleep(2.6)
        try:
            await asyncio.to_thread(
                claim_image_preprocess_permit,
                engine,
                user_id=user_b,
                settings=settings,
            )
        except ConcurrencyRejected as exc:
            assert exc.code == "AI_IMAGE_PREPROCESS_SATURATED"
        else:
            raise AssertionError("heartbeat lease allowed preprocessing oversubscription")

    second = await asyncio.to_thread(
        claim_image_preprocess_permit,
        engine,
        user_id=user_b,
        settings=settings,
    )
    assert release_permit(engine, permit=second, settings=settings) is True


def _prove_preprocess_renew_claim_serialization(
    user_a: UUID,
    user_b: UUID,
) -> None:
    settings = _preprocess_settings(global_limit=1, user_limit=1, lease_seconds=6)
    first = claim_image_preprocess_permit(
        engine,
        user_id=user_a,
        settings=settings,
    )

    trigger_name = "sec016_test_slow_preprocess_renew"
    function_name = "sec016_test_slow_preprocess_renew_fn"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"""
            CREATE OR REPLACE FUNCTION {function_name}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $func$
            BEGIN
                IF NEW.service_class = 'AI_IMAGE_PREPROCESS' THEN
                    PERFORM pg_sleep(4);
                END IF;
                RETURN NEW;
            END;
            $func$
            """
        )
        connection.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS {trigger_name} ON work_permits"
        )
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER {trigger_name}
            AFTER UPDATE OF expires_at ON work_permits
            FOR EACH ROW
            EXECUTE FUNCTION {function_name}()
            """
        )

    renew_result: list = []
    renew_errors: list[BaseException] = []

    def renew_worker() -> None:
        try:
            renewed = renew_permit(
                engine,
                permit=first,
                lease_seconds=6,
                settings=settings,
            )
            renew_result.append(renewed)
        except BaseException as exc:  # noqa: BLE001
            renew_errors.append(exc)

    try:
        # Start renewal while the original lease is live. The trigger holds the
        # transaction after UPDATE but before COMMIT while renew still owns the
        # global/user ConcurrencyGuard rows.
        sleep(2.5)
        thread = Thread(target=renew_worker, name="media-preprocess-renew-race")
        thread.start()
        sleep(3.8)
        assert datetime.now(UTC) > first.expires_at

        claim_started = monotonic()
        try:
            claim_image_preprocess_permit(
                engine,
                user_id=user_b,
                settings=settings,
            )
        except ConcurrencyRejected as exc:
            claim_elapsed = monotonic() - claim_started
            assert exc.code == "AI_IMAGE_PREPROCESS_SATURATED"
            # Admission must have waited for renewal's shared guard transaction.
            assert claim_elapsed >= 0.2
        else:
            raise AssertionError(
                "renew/admission serialization allowed two active preprocessing permits"
            )

        thread.join(timeout=15)
        assert not thread.is_alive()
        if renew_errors:
            raise renew_errors[0]
        assert len(renew_result) == 1
        assert renew_result[0] is not None

        with SessionLocal() as db:
            active = list(
                db.scalars(
                    select(WorkPermit).where(
                        WorkPermit.service_class == "AI_IMAGE_PREPROCESS",
                        WorkPermit.expires_at > datetime.now(UTC),
                    )
                )
            )
            assert len(active) == 1
            assert active[0].id == first.permit_id
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"DROP TRIGGER IF EXISTS {trigger_name} ON work_permits"
            )
            connection.exec_driver_sql(
                f"DROP FUNCTION IF EXISTS {function_name}()"
            )
        release_permit(engine, permit=first, settings=settings)


def _prove_stale_recovery_and_token_binding(user_id: UUID) -> None:
    settings = _provider_settings(global_limit=1, user_limit=1)
    first = claim_provider_permit(
        engine,
        service_class="AI",
        user_id=user_id,
        settings=settings,
    )
    forged = replace(first, token=first.token + "-forged")
    assert release_permit(engine, permit=forged, settings=settings) is False
    with SessionLocal() as db:
        assert db.get(WorkPermit, first.permit_id) is not None
        row = db.get(WorkPermit, first.permit_id)
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    second = claim_provider_permit(
        engine,
        service_class="AI",
        user_id=user_id,
        settings=settings,
    )
    assert second.permit_id != first.permit_id
    assert release_permit(engine, permit=first, settings=settings) is True
    assert release_permit(engine, permit=first, settings=settings) is False
    assert release_permit(engine, permit=second, settings=settings) is True


def _prove_live_permit_survives_owner_delete(user_id: UUID) -> None:
    settings = _provider_settings(global_limit=1, user_limit=1)
    permit = claim_provider_permit(
        engine,
        service_class="AI",
        user_id=user_id,
        settings=settings,
    )
    with SessionLocal() as db:
        db.execute(delete(User).where(User.id == user_id))
        db.commit()
    with SessionLocal() as db:
        row = db.get(WorkPermit, permit.permit_id)
        assert row is not None
        assert row.user_id is None
    try:
        claim_provider_permit(
            engine,
            service_class="AI",
            user_id=uuid4(),
            settings=settings,
        )
    except ConcurrencyRejected as exc:
        assert exc.code == "PROVIDER_CONCURRENCY_SATURATED"
    else:
        raise AssertionError("owner deletion released a live provider slot")
    assert release_permit(engine, permit=permit, settings=settings) is True


def _race_argon2_claim() -> tuple[list, list[str]]:
    settings = get_settings().model_copy(
        update={
            "argon2_global_concurrency": 1,
            "argon2_permit_lease_seconds": 5,
        }
    )
    barrier = Barrier(2)
    lock = Lock()
    permits = []
    denials: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            permit = claim_argon2_permit(engine, settings=settings)
            with lock:
                permits.append(permit)
        except ConcurrencyRejected as exc:
            with lock:
                denials.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    threads = [
        Thread(target=worker, name="sec016-argon2-a"),
        Thread(target=worker, name="sec016-argon2-b"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
        assert not thread.is_alive()
    if errors:
        raise errors[0]
    return permits, denials


def _prove_argon2_global_cap() -> None:
    permits, denials = _race_argon2_claim()
    assert len(permits) == 1
    assert denials == ["AUTH_PASSWORD_WORK_SATURATED"]
    assert release_permit(engine, permit=permits[0]) is True


def _prove_authenticated_rate_bucket_race(user_id: UUID) -> None:
    settings = auth_rate_limit.settings
    old = {
        "api_rate_limit_enabled": settings.api_rate_limit_enabled,
        "api_expensive_user_limit": settings.api_expensive_user_limit,
        "api_expensive_ip_limit": settings.api_expensive_ip_limit,
        "api_rate_window_seconds": settings.api_rate_window_seconds,
    }
    settings.api_rate_limit_enabled = True
    settings.api_expensive_user_limit = 10
    settings.api_expensive_ip_limit = 10
    settings.api_rate_window_seconds = 60

    barrier = Barrier(2)
    lock = Lock()
    errors: list[BaseException] = []
    raw_ip = "198.51.100.203"

    def worker() -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            consume_authenticated_api_attempt(
                db,
                user_id=user_id,
                client_ip=raw_ip,
                route_class=ApiRouteClass.EXPENSIVE_AI,
            )
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            db.close()

    try:
        first = Thread(target=worker, name="sec016-rate-a")
        second = Thread(target=worker, name="sec016-rate-b")
        first.start()
        second.start()
        first.join(timeout=20)
        second.join(timeout=20)
        assert not first.is_alive() and not second.is_alive()
        if errors:
            raise errors[0]

        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(AuthRateLimitBucket).where(
                        AuthRateLimitBucket.scope.in_(
                            (
                                "api_user:EXPENSIVE_AI",
                                "api_ip:EXPENSIVE_AI",
                            )
                        )
                    )
                )
            )
            assert len(rows) == 2
            assert {row.attempts for row in rows} == {2}
            assert all(raw_ip not in row.key for row in rows)
            assert all(str(user_id) not in row.key for row in rows)

        # Independent route classes must not share one bucket.
        with SessionLocal() as db:
            consume_authenticated_api_attempt(
                db,
                user_id=user_id,
                client_ip=raw_ip,
                route_class=ApiRouteClass.NORMAL_READ,
            )
        with SessionLocal() as db:
            scopes = set(
                db.scalars(
                    select(AuthRateLimitBucket.scope).where(
                        AuthRateLimitBucket.scope.like("api_%")
                    )
                )
            )
            assert "api_user:NORMAL_READ" in scopes
            assert "api_user:EXPENSIVE_AI" in scopes
    finally:
        for key, value in old.items():
            setattr(settings, key, value)


def main() -> None:
    _prove_migration_roundtrip()
    user_a = _seed_user("a")
    user_b = _seed_user("b")
    try:
        _prove_provider_races(user_a, user_b)
        _prove_image_preprocess_cross_worker_budget(user_a, user_b)
        _prove_preprocess_renewal_token_binding(user_a, user_b)
        asyncio.run(_prove_preprocess_heartbeat_lifecycle(user_a, user_b))
        _prove_preprocess_renew_claim_serialization(user_a, user_b)
        _prove_stale_recovery_and_token_binding(user_a)
        _prove_live_permit_survives_owner_delete(user_a)
        user_a = _seed_user("a-after-delete")
        _prove_argon2_global_cap()
        _prove_authenticated_rate_bucket_race(user_a)
    finally:
        _cleanup(user_a, user_b)
    print("PostgreSQL SEC-016 abuse/concurrency PASS")


if __name__ == "__main__":
    main()
