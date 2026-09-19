# [人工注释][S2-006~S2-014] PostgreSQL 专用集成验收：
# owner 派生锁必须串行化并发 batch，最终同 client_uuid/Visit/Place 都只能各有一份。
import os
from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import LocationPoint, Place, User, Visit
from app.schemas import LocationBatchRequest, LocationPointCreate
from app.services.location_service import ingest_location_batch
from app.services.privacy_service import lock_location_derivation_state


def _database_url() -> str:
    value = os.environ["DATABASE_URL"]
    if not value.startswith("postgresql"):
        raise RuntimeError("PostgreSQL integration check requires a PostgreSQL DATABASE_URL")
    return value


def _payload(prefix: str, started: datetime) -> LocationBatchRequest:
    return LocationBatchRequest(
        points=[
            LocationPointCreate(
                client_uuid=f"{prefix}-{index}",
                latitude=31.23040 + index * 0.00003,
                longitude=121.47370 + index * 0.00003,
                accuracy=10,
                speed=0.1,
                recorded_at=started + timedelta(minutes=index * 5),
            )
            for index in range(3)
        ]
    )


def _verify_shared_owner_lock(engine, user_id) -> None:
    result: list[str] = []

    def contender() -> None:
        with Session(engine) as db:
            db.execute(text("SET LOCAL lock_timeout = '500ms'"))
            try:
                lock_location_derivation_state(db, user_id)
            except OperationalError:
                db.rollback()
                result.append("blocked")
            else:
                db.rollback()
                result.append("not-blocked")

    with Session(engine) as holder:
        lock_location_derivation_state(holder, user_id)
        holder.flush()
        thread = Thread(target=contender, daemon=True)
        thread.start()
        thread.join(timeout=5)
        if thread.is_alive():
            raise AssertionError("location state lock contender did not finish")
        if result != ["blocked"]:
            raise AssertionError(f"owner location lock was not exclusive: {result}")
        holder.rollback()


def _verify_concurrent_replay(engine, user_id) -> None:
    payload = _payload("pg-replay", datetime.now(UTC) - timedelta(minutes=20))
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with Session(engine) as db:
                barrier.wait(timeout=5)
                ingest_location_batch(db, user_id=user_id, payload=payload)
        except BaseException as exc:  # pragma: no cover - CI diagnostic path
            errors.append(exc)

    threads = [Thread(target=worker, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    if any(thread.is_alive() for thread in threads):
        raise AssertionError("concurrent location workers did not finish")
    if errors:
        raise AssertionError(f"concurrent location ingest failed: {errors!r}")

    with Session(engine) as db:
        assert db.scalar(
            select(func.count()).select_from(LocationPoint).where(
                LocationPoint.user_id == user_id
            )
        ) == 3
        assert db.scalar(
            select(func.count()).select_from(Visit).where(Visit.user_id == user_id)
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(Place).where(Place.user_id == user_id)
        ) == 1


def _verify_owner_isolation(engine, user_a, user_b) -> None:
    payload = _payload("same-client", datetime.now(UTC) - timedelta(minutes=20))
    with Session(engine) as db:
        ingest_location_batch(db, user_id=user_a, payload=payload)
    with Session(engine) as db:
        ingest_location_batch(db, user_id=user_b, payload=payload)

    with Session(engine) as db:
        assert db.scalar(
            select(func.count()).select_from(LocationPoint).where(
                LocationPoint.user_id == user_a
            )
        ) == 3
        assert db.scalar(
            select(func.count()).select_from(LocationPoint).where(
                LocationPoint.user_id == user_b
            )
        ) == 3
        place_a = db.scalar(select(Place).where(Place.user_id == user_a))
        place_b = db.scalar(select(Place).where(Place.user_id == user_b))
        assert place_a is not None and place_b is not None
        assert place_a.id != place_b.id


def main() -> None:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    user_a = uuid4()
    user_b = uuid4()
    with Session(engine) as db:
        db.add_all(
            [
                User(id=user_a, nickname="Location PG A"),
                User(id=user_b, nickname="Location PG B"),
            ]
        )
        db.commit()

    try:
        with Session(engine) as db:
            lock_location_derivation_state(db, user_a)
            db.commit()
        _verify_shared_owner_lock(engine, user_a)
        _verify_concurrent_replay(engine, user_a)

        with Session(engine) as db:
            db.execute(
                text("DELETE FROM location_points WHERE user_id = :user_id"),
                {"user_id": user_a},
            )
            db.execute(
                text("DELETE FROM visits WHERE user_id = :user_id"),
                {"user_id": user_a},
            )
            db.execute(
                text("DELETE FROM places WHERE user_id = :user_id"),
                {"user_id": user_a},
            )
            db.execute(
                text(
                    "UPDATE location_derivation_states SET finalized_through = NULL "
                    "WHERE user_id = :user_id"
                ),
                {"user_id": user_a},
            )
            db.commit()

        _verify_owner_isolation(engine, user_a, user_b)
    finally:
        with Session(engine) as db:
            for user_id in (user_a, user_b):
                user = db.get(User, user_id)
                if user is not None:
                    db.delete(user)
            db.commit()
        engine.dispose()


if __name__ == "__main__":
    main()
