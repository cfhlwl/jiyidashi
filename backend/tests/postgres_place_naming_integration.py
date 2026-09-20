"""PostgreSQL integration coverage for Stage 2Q Place naming serialization."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.idempotency_models import ClientMutation
from app.models import Place, PlaceNameCorrection, User
from app.services.place_naming_service import (
    PLACE_NAME_CORRECTION_OPERATION,
    PlaceNamingError,
    apply_automatic_place_label_candidate,
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


def _automatic_first_user_second(place_id: UUID) -> None:
    automatic_locked = Event()
    allow_automatic_commit = Event()
    user_finished = Event()
    errors: list[BaseException] = []

    def automatic_writer() -> None:
        try:
            with SessionLocal() as db:
                place = apply_automatic_place_label_candidate(
                    db,
                    user_id=USER_ID,
                    place_id=place_id,
                    label="自动候选-A",
                    source="POI_RACE_A",
                )
                assert place.name == "自动候选-A"
                automatic_locked.set()
                if not allow_automatic_commit.wait(timeout=15):
                    raise AssertionError("automatic transaction was not released")
                db.commit()
        except BaseException as exc:  # noqa: BLE001 - thread returns race assertion
            errors.append(exc)
            automatic_locked.set()
            allow_automatic_commit.set()

    def user_writer() -> None:
        try:
            if not automatic_locked.wait(timeout=15):
                raise AssertionError("automatic writer did not acquire Place lock")
            with SessionLocal() as db:
                place = correct_place_name(
                    db,
                    user_id=USER_ID,
                    place_id=place_id,
                    client_uuid=uuid4(),
                    name="用户地点-A",
                )
                assert place.name == "用户地点-A"
        except BaseException as exc:  # noqa: BLE001 - thread returns race assertion
            errors.append(exc)
        finally:
            user_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        automatic_future = executor.submit(automatic_writer)
        assert automatic_locked.wait(timeout=15)
        user_future = executor.submit(user_writer)

        # [人工注释][S2-009][S2-010] automatic 已持有 FOR UPDATE 时，
        # user correction 必须等待；automatic commit 后 USER 再成为最终展示 precedence。
        assert not user_finished.wait(timeout=0.25)
        allow_automatic_commit.set()
        automatic_future.result(timeout=20)
        user_future.result(timeout=20)

    if errors:
        raise errors[0]

    with SessionLocal() as db:
        place = db.get(Place, place_id)
        assert place is not None
        assert place.user_name == "用户地点-A"
        assert place.name == "用户地点-A"
        assert place.name_source == "USER"
        assert place.automatic_name == "自动候选-A"
        assert place.automatic_name_source == "POI_RACE_A"


def _user_first_automatic_second(place_id: UUID) -> None:
    user_locked = Event()
    automatic_started = Event()
    automatic_finished = Event()
    errors: list[BaseException] = []

    def automatic_writer() -> None:
        try:
            if not user_locked.wait(timeout=15):
                raise AssertionError("user writer did not acquire Place lock")
            automatic_started.set()
            with SessionLocal() as db:
                place = apply_automatic_place_label_candidate(
                    db,
                    user_id=USER_ID,
                    place_id=place_id,
                    label="自动候选-B",
                    source="ADDRESS_RACE_B",
                )
                db.commit()
                assert place.automatic_name == "自动候选-B"
        except BaseException as exc:  # noqa: BLE001 - thread returns race assertion
            errors.append(exc)
        finally:
            automatic_finished.set()

    def user_writer() -> None:
        try:
            with SessionLocal() as db:
                # 先用与生产逻辑相同的 Place FOR UPDATE 锁住行，再让 automatic writer
                # 发起竞争；correct_place_name 在同一 Session 上重入该锁并负责最终 commit。
                locked = db.scalar(
                    select(Place)
                    .where(Place.id == place_id, Place.user_id == USER_ID)
                    .with_for_update()
                )
                assert locked is not None
                user_locked.set()
                if not automatic_started.wait(timeout=15):
                    raise AssertionError("automatic writer did not start")
                assert not automatic_finished.wait(timeout=0.25)
                place = correct_place_name(
                    db,
                    user_id=USER_ID,
                    place_id=place_id,
                    client_uuid=uuid4(),
                    name="用户地点-B",
                )
                assert place.name == "用户地点-B"
        except BaseException as exc:  # noqa: BLE001 - thread returns race assertion
            errors.append(exc)
            user_locked.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        user_future = executor.submit(user_writer)
        automatic_future = executor.submit(automatic_writer)
        user_future.result(timeout=20)
        automatic_future.result(timeout=20)

    if errors:
        raise errors[0]

    with SessionLocal() as db:
        place = db.get(Place, place_id)
        assert place is not None
        # automatic 在 USER commit 后才拿到锁，但 _sync_display_name 仍必须保持 USER。
        assert place.user_name == "用户地点-B"
        assert place.name == "用户地点-B"
        assert place.name_source == "USER"
        assert place.automatic_name == "自动候选-B"
        assert place.automatic_name_source == "ADDRESS_RACE_B"


def main() -> None:
    place_serial = uuid4()
    place_replay = uuid4()
    place_auto_first = uuid4()
    place_user_first = uuid4()
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
                Place(
                    id=place_auto_first,
                    user_id=USER_ID,
                    name="未命名地点",
                    cluster_key=f"q{place_auto_first.hex[:10]}",
                ),
                Place(
                    id=place_user_first,
                    user_id=USER_ID,
                    name="未命名地点",
                    cluster_key=f"q{place_user_first.hex[:10]}",
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

    _automatic_first_user_second(place_auto_first)
    _user_first_automatic_second(place_user_first)

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
