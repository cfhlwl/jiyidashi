"""PostgreSQL integration coverage for the durable user-data deletion state machine."""

from collections.abc import Iterator
from datetime import UTC, datetime
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    SessionLocal,
    UserDataAdmission,
    UserDataRequestStale,
)
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.idempotency_models import ClientMutation
from app.models import FamilyMember, LocationPoint, Memory, MemoryEdit, PrivacyState, User
from app.services.data_deletion_service import delete_all_user_data


class EmptyStorage:
    def iter_object_keys(self, prefix: str) -> Iterator[str]:
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _admit_existing_user_request(db, user_id) -> None:
    # Mirror get_current_user_id() without HTTP credentials so this integration can hold
    # one real PostgreSQL Session across the deliberate rollback boundary.
    existing = db.scalar(
        select(User.id).where(User.id == user_id).with_for_update(read=True, key_share=True)
    )
    assert existing == user_id
    generation = int(
        db.scalar(
            select(func.count(DataDeletionOperation.id)).where(
                DataDeletionOperation.user_id == user_id
            )
        )
        or 0
    )
    db.info[USER_DATA_ADMISSION_INFO_KEY] = UserDataAdmission(
        user_id=user_id,
        deletion_generation=generation,
    )


def _assert_old_location_request_cannot_resume_after_completed_delete() -> None:
    # [人工注释][S1-021-FIX-001] 两个真实线程 + 两个独立 PostgreSQL Session：
    # 旧 Location 准入 -> 唯一键失败 rollback -> 暂停；Data Delete 完成后再恢复旧请求。
    # 最终 stale commit 必须被 generation gate 拒绝，且 LocationPoint 必须保持 0。
    user_id = uuid4()
    existing_id = uuid4()
    collision_uuid = f"collision-{uuid4()}"

    with SessionLocal() as seed:
        seed.add(User(id=user_id, nickname="delete-race-owner"))
        seed.flush()
        seed.add(
            LocationPoint(
                id=existing_id,
                user_id=user_id,
                client_uuid=collision_uuid,
                latitude=1.0,
                longitude=2.0,
                recorded_at=datetime.now(UTC),
            )
        )
        seed.commit()

    rolled_back = Event()
    delete_completed = Event()
    errors: list[BaseException] = []

    def old_location_request() -> None:
        old_request = SessionLocal()
        try:
            _admit_existing_user_request(old_request, user_id)
            old_request.add(
                LocationPoint(
                    user_id=user_id,
                    client_uuid=collision_uuid,
                    latitude=3.0,
                    longitude=4.0,
                    recorded_at=datetime.now(UTC),
                )
            )
            try:
                old_request.commit()
                raise AssertionError("expected first Location unique-key collision")
            except IntegrityError:
                old_request.rollback()

            rolled_back.set()
            if not delete_completed.wait(timeout=15):
                raise AssertionError("Data Delete did not complete after Location rollback")

            old_request.add(
                LocationPoint(
                    user_id=user_id,
                    client_uuid=collision_uuid,
                    latitude=5.0,
                    longitude=6.0,
                    recorded_at=datetime.now(UTC),
                )
            )
            try:
                old_request.commit()
                raise AssertionError("stale pre-delete request committed after COMPLETED")
            except UserDataRequestStale:
                old_request.rollback()
        except BaseException as exc:  # noqa: BLE001 - thread must report assertion failures
            errors.append(exc)
            rolled_back.set()
            delete_completed.set()
        finally:
            old_request.close()

    def destructive_delete() -> None:
        try:
            if not rolled_back.wait(timeout=15):
                raise AssertionError("Location request did not reach rollback boundary")
            with SessionLocal() as deleting:
                result = delete_all_user_data(
                    deleting,
                    user_id=user_id,
                    request_id=uuid4(),
                    storage=EmptyStorage(),
                )
                assert result.completed is True
                assert result.status == DataDeletionStatus.COMPLETED
        except BaseException as exc:  # noqa: BLE001 - thread must report assertion failures
            errors.append(exc)
        finally:
            delete_completed.set()

    old_thread = Thread(target=old_location_request, name="old-location-request")
    delete_thread = Thread(target=destructive_delete, name="data-delete")
    old_thread.start()
    delete_thread.start()
    old_thread.join(timeout=20)
    delete_thread.join(timeout=20)
    assert not old_thread.is_alive()
    assert not delete_thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as verify:
        remaining = int(
            verify.scalar(
                select(func.count(LocationPoint.id)).where(LocationPoint.user_id == user_id)
            )
            or 0
        )
        assert remaining == 0

    # A genuinely new request after COMPLETED observes the new generation and may write.
    with SessionLocal() as fresh:
        _admit_existing_user_request(fresh, user_id)
        fresh.add(
            LocationPoint(
                user_id=user_id,
                client_uuid=f"fresh-{uuid4()}",
                latitude=7.0,
                longitude=8.0,
                recorded_at=datetime.now(UTC),
            )
        )
        fresh.commit()

    with SessionLocal() as cleanup:
        assert (
            int(
                cleanup.scalar(
                    select(func.count(LocationPoint.id)).where(
                        LocationPoint.user_id == user_id
                    )
                )
                or 0
            )
            == 1
        )
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


def main() -> None:
    _assert_old_location_request_cannot_resume_after_completed_delete()

    request_id = uuid4()
    owner_id = uuid4()
    other_id = uuid4()
    memory_id = uuid4()
    other_memory_id = uuid4()
    memory_edit_id = uuid4()
    other_memory_edit_id = uuid4()
    family_id = uuid4()
    mutation_id = uuid4()

    with SessionLocal() as db:
        db.add_all(
            [
                User(id=owner_id, nickname="delete-pg-owner"),
                User(id=other_id, nickname="delete-pg-other"),
            ]
        )
        db.flush()
        db.add_all(
            [
                Memory(id=memory_id, user_id=owner_id, content="delete me"),
                Memory(id=other_memory_id, user_id=other_id, content="keep me"),
                MemoryEdit(
                    id=memory_edit_id,
                    memory_id=memory_id,
                    user_id=owner_id,
                    revision=1,
                    previous_content="old delete me",
                    new_content="delete me",
                    changed_title=False,
                    changed_content=True,
                ),
                MemoryEdit(
                    id=other_memory_edit_id,
                    memory_id=other_memory_id,
                    user_id=other_id,
                    revision=1,
                    previous_content="old keep me",
                    new_content="keep me",
                    changed_title=False,
                    changed_content=True,
                ),
                PrivacyState(user_id=owner_id),
                FamilyMember(
                    id=family_id,
                    owner_user_id=other_id,
                    member_user_id=owner_id,
                ),
                ClientMutation(
                    id=mutation_id,
                    user_id=owner_id,
                    operation_type="memory.create",
                    client_uuid=uuid4(),
                    request_fingerprint="b" * 64,
                    resource_type="memory",
                    resource_id=memory_id,
                ),
            ]
        )
        db.commit()

    storage = EmptyStorage()
    with SessionLocal() as db:
        result = delete_all_user_data(
            db,
            user_id=owner_id,
            request_id=request_id,
            storage=storage,
        )
        assert result.completed is True
        assert result.status == DataDeletionStatus.COMPLETED

    with SessionLocal() as db:
        # [人工注释][S1-021] PostgreSQL 实库验证 owner isolation：
        # 当前用户应用数据清空；账号 User 和另一用户数据继续存在。
        assert db.get(User, owner_id) is not None
        assert db.get(Memory, memory_id) is None
        assert db.get(MemoryEdit, memory_edit_id) is None
        assert db.get(PrivacyState, owner_id) is None
        assert db.get(FamilyMember, family_id) is None
        assert db.get(ClientMutation, mutation_id) is None
        assert db.get(User, other_id) is not None
        assert db.get(Memory, other_memory_id) is not None
        assert db.get(MemoryEdit, other_memory_edit_id) is not None
        operation = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == owner_id,
                DataDeletionOperation.request_id == request_id,
            )
        )
        assert operation is not None
        assert operation.status == DataDeletionStatus.COMPLETED

        # Cleanup belongs only to this integration fixture, after preservation was proven.
        db.delete(db.get(User, owner_id))
        db.delete(db.get(User, other_id))
        db.commit()


if __name__ == "__main__":
    main()
