# [人工注释][S2-006~S2-014] PostgreSQL 专用集成验收：
# owner 派生锁必须串行化并发 batch，最终同 client_uuid/Visit/Place 都只能各有一份。
import os
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, Thread
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.maintenance.location_retention import (
    discover_location_maintenance_owner_ids,
    maintain_discovered_location_owner,
)
from app.models import (
    LocationDerivationState,
    LocationIngestReceipt,
    LocationPoint,
    Memory,
    ObjectItem,
    ObjectLocation,
    Place,
    User,
    Visit,
)
from app.schemas import LocationBatchRequest, LocationPointCreate
from app.services.data_deletion_service import delete_all_user_data
from app.services.location_service import _refresh_place_stats, ingest_location_batch
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
            select(func.count())
            .select_from(LocationIngestReceipt)
            .where(LocationIngestReceipt.user_id == user_id)
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



class _EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _verify_stale_maintenance_discovery_cannot_resurrect_after_data_delete() -> None:
    user_id = uuid4()
    request_id = uuid4()
    with SessionLocal() as seed:
        seed.add(User(id=user_id, nickname="location-maintenance-delete-race"))
        seed.flush()
        seed.add(
            LocationPoint(
                user_id=user_id,
                client_uuid=f"stale-maintenance-{uuid4()}",
                latitude=31.2,
                longitude=121.4,
                recorded_at=datetime.now(UTC) - timedelta(days=40),
            )
        )
        seed.commit()

    discovered = discover_location_maintenance_owner_ids()
    assert user_id in discovered

    with SessionLocal() as deleting:
        result = delete_all_user_data(
            deleting,
            user_id=user_id,
            request_id=request_id,
            storage=_EmptyStorage(),
        )
        assert result.completed is True
        assert result.status == DataDeletionStatus.COMPLETED

    # [人工注释][S2-014][S1-021] 这里故意继续使用删除前缓存的 owner_id。
    # maintenance 必须重新 admission + 复查 raw/state，而不是把 stale discovery 当真。
    maintained = maintain_discovered_location_owner(
        user_id,
        now=datetime.now(UTC) + timedelta(days=1),
    )
    assert maintained is None

    with SessionLocal() as verify:
        assert verify.get(LocationDerivationState, user_id) is None
        assert verify.scalar(
            select(func.count())
            .select_from(LocationPoint)
            .where(LocationPoint.user_id == user_id)
        ) == 0
        assert verify.scalar(
            select(func.count())
            .select_from(LocationIngestReceipt)
            .where(LocationIngestReceipt.user_id == user_id)
        ) == 0
        assert verify.scalar(
            select(func.count()).select_from(Visit).where(Visit.user_id == user_id)
        ) == 0
        assert verify.scalar(
            select(func.count()).select_from(Place).where(Place.user_id == user_id)
        ) == 0
        operation = verify.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        assert operation.status == DataDeletionStatus.COMPLETED

        user = verify.get(User, user_id)
        assert user is not None
        verify.delete(user)
        verify.commit()


def _verify_orphan_place_cleanup_serializes_with_new_reference(
    engine,
    *,
    reference_kind: str,
) -> None:
    user_id = uuid4()
    place_id = uuid4()
    object_id = uuid4()
    with Session(engine) as seed:
        seed.add(User(id=user_id, nickname=f"place-race-{reference_kind}"))
        seed.flush()
        seed.add(
            Place(
                id=place_id,
                user_id=user_id,
                name="未命名地点",
                cluster_key=f"race{str(place_id).replace('-', '')[:8]}",
                is_user_named=False,
            )
        )
        if reference_kind == "object":
            seed.add(
                ObjectItem(
                    id=object_id,
                    user_id=user_id,
                    name="并发测试物品",
                    normalized_name=f"race-{object_id}",
                )
            )
        seed.commit()

    reference_flushed = Event()
    allow_reference_commit = Event()
    cleanup_finished = Event()
    errors: list[BaseException] = []
    reference_id = uuid4()

    def create_reference() -> None:
        try:
            with Session(engine) as db:
                if reference_kind == "memory":
                    db.add(
                        Memory(
                            id=reference_id,
                            user_id=user_id,
                            content="并发创建的地点事实",
                            place_id=place_id,
                        )
                    )
                else:
                    db.add(
                        ObjectLocation(
                            id=reference_id,
                            object_id=object_id,
                            user_id=user_id,
                            location_text="并发地点",
                            place_id=place_id,
                        )
                    )
                # PostgreSQL FK validation now holds KEY SHARE on Place until commit.
                db.flush()
                reference_flushed.set()
                if not allow_reference_commit.wait(timeout=15):
                    raise AssertionError("reference transaction was not released")
                db.commit()
        except BaseException as exc:  # noqa: BLE001 - thread reports DB race assertions
            errors.append(exc)
            reference_flushed.set()
            allow_reference_commit.set()

    def cleanup_orphan() -> None:
        try:
            if not reference_flushed.wait(timeout=15):
                raise AssertionError("reference did not acquire Place FK lock")
            with Session(engine) as db:
                _refresh_place_stats(db, user_id)
                db.commit()
        except BaseException as exc:  # noqa: BLE001 - thread reports DB race assertions
            errors.append(exc)
        finally:
            cleanup_finished.set()

    reference_thread = Thread(
        target=create_reference,
        name=f"place-reference-{reference_kind}",
    )
    cleanup_thread = Thread(
        target=cleanup_orphan,
        name=f"place-cleanup-{reference_kind}",
    )
    reference_thread.start()
    assert reference_flushed.wait(timeout=15)
    cleanup_thread.start()

    # [人工注释][S2-008] cleanup 必须在 Place FOR UPDATE 上等待未提交的 FK KEY SHARE。
    # 若没有这把前置锁，它会先判“无引用”，随后 DELETE 在引用提交后把 place_id SET NULL。
    assert not cleanup_finished.wait(timeout=0.25)

    allow_reference_commit.set()
    reference_thread.join(timeout=15)
    cleanup_thread.join(timeout=15)
    assert not reference_thread.is_alive()
    assert not cleanup_thread.is_alive()
    if errors:
        raise errors[0]

    with Session(engine) as verify:
        assert verify.get(Place, place_id) is not None
        if reference_kind == "memory":
            reference = verify.get(Memory, reference_id)
        else:
            reference = verify.get(ObjectLocation, reference_id)
        assert reference is not None
        assert reference.place_id == place_id

        user = verify.get(User, user_id)
        assert user is not None
        verify.delete(user)
        verify.commit()


def main() -> None:
    _verify_stale_maintenance_discovery_cannot_resurrect_after_data_delete()

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
        _verify_orphan_place_cleanup_serializes_with_new_reference(
            engine,
            reference_kind="memory",
        )
        _verify_orphan_place_cleanup_serializes_with_new_reference(
            engine,
            reference_kind="object",
        )
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
