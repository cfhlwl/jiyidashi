"""PostgreSQL integration coverage for Stage 2Q Place naming serialization."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.idempotency_models import ClientMutation
from app.models import Place, PlaceNameCorrection, User
from app.services.place_naming_service import (
    PLACE_NAME_CORRECTION_OPERATION,
    PlaceNamingError,
    correct_place_name,
)

USER_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


def _correct(place_id: UUID, client_uuid: UUID, name: str, barrier: Barrier) -> str:
    barrier.wait(timeout=10)
    with SessionLocal() as db:
        place = correct_place_name(
            db,
            user_id=USER_ID,
            place_id=place_id,
            client_uuid=client_uuid,
            name=name,
        )
        return place.name


def main() -> None:
    place_serial = uuid4()
    place_replay = uuid4()
    with SessionLocal() as db:
        db.query(User).filter(User.id == USER_ID).delete()
        db.add(User(id=USER_ID, nickname="place-naming-pg"))
        db.flush()
        db.add_all(
            [
                Place(
                    id=place_serial,
                    user_id=USER_ID,
                    name="未命名地点",
                    cluster_key=f"q{place_serial.hex[:10]}",
                ),
                Place(
                    id=place_replay,
                    user_id=USER_ID,
                    name="未命名地点",
                    cluster_key=f"q{place_replay.hex[:10]}",
                ),
            ]
        )
        db.commit()

    # 两个不同纠正从同一时刻进入；Place FOR UPDATE 必须把 revision/history 串成 1、2。
    serial_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_correct, place_serial, uuid4(), "家", serial_barrier),
            executor.submit(_correct, place_serial, uuid4(), "办公室", serial_barrier),
        ]
        results = [future.result(timeout=20) for future in futures]
    assert set(results) == {"家", "办公室"}

    with SessionLocal() as db:
        place = db.get(Place, place_serial)
        assert place is not None
        assert place.user_name in {"家", "办公室"}
        assert place.name_revision == 2
        corrections = list(
            db.scalars(
                select(PlaceNameCorrection)
                .where(PlaceNameCorrection.place_id == place_serial)
                .order_by(PlaceNameCorrection.revision)
            )
        )
        assert [row.revision for row in corrections] == [1, 2]
        assert corrections[1].previous_user_name == corrections[0].new_user_name

    # 相同 client_uuid 的并发重放只能产生一个 ClientMutation 和一条纠正历史。
    replay_uuid = uuid4()
    replay_barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_correct, place_replay, replay_uuid, "常去的店", replay_barrier),
            executor.submit(_correct, place_replay, replay_uuid, "常去的店", replay_barrier),
        ]
        replay_results = [future.result(timeout=20) for future in futures]
    assert replay_results == ["常去的店", "常去的店"]

    with SessionLocal() as db:
        place = db.get(Place, place_replay)
        assert place is not None
        assert place.user_name == "常去的店"
        assert place.name_revision == 1
        assert db.scalar(
            select(func.count())
            .select_from(PlaceNameCorrection)
            .where(PlaceNameCorrection.place_id == place_replay)
        ) == 1
        assert db.scalar(
            select(func.count())
            .select_from(ClientMutation)
            .where(
                ClientMutation.user_id == USER_ID,
                ClientMutation.operation_type == PLACE_NAME_CORRECTION_OPERATION,
                ClientMutation.client_uuid == replay_uuid,
            )
        ) == 1

    with SessionLocal() as db:
        try:
            correct_place_name(
                db,
                user_id=USER_ID,
                place_id=place_replay,
                client_uuid=replay_uuid,
                name="复用 UUID 的不同请求",
            )
            raise AssertionError("expected Place correction idempotency conflict")
        except PlaceNamingError as exc:
            assert exc.code == "PLACE_NAME_CORRECTION_CONFLICT"
            assert exc.status_code == 409
            db.rollback()

    with SessionLocal() as db:
        user = db.get(User, USER_ID)
        assert user is not None
        db.delete(user)
        db.commit()

    print("PostgreSQL Place naming concurrency PASS")


if __name__ == "__main__":
    main()
