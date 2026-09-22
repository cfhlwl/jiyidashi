"""PostgreSQL integration coverage for S1-022 account-deletion gates."""

from threading import Barrier, Event, Thread
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthProvider
from app.core.db import (
    USER_DATA_ADMISSION_INFO_KEY,
    SessionLocal,
    UserDataAdmission,
    UserDataRequestStale,
)
from app.data_deletion_models import DataDeletionOperation
from app.deps import get_current_user_id
from app.embedding_models import MemoryEmbedding
from app.embedding_policy import MEMORY_EMBEDDING_DIMENSIONS, MEMORY_EMBEDDING_MODEL
from app.memory_feedback_models import MemoryFeedback, MemoryFeedbackAction
from app.models import Memory, User
from app.services.account_deletion_service import (
    AccountDeletionError,
    _begin_or_load_account_deletion,
    delete_current_account,
    lock_external_data_delete_entry,
)
from app.services.auth_service import (
    _lock_login_user_for_authentication,
    lock_login_for_token_issue,
)
from app.services.data_deletion_service import _begin_or_load_operation


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        return iter(())

    def delete_object(self, object_key: str) -> None:
        return None


def _admit_existing_user_request(db, user_id) -> None:
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


def _assert_login_serializes_with_account_delete_gate() -> None:
    user_id = uuid4()
    gate_request = uuid4()

    with SessionLocal() as seed:
        seed.add(User(id=user_id, nickname="account-delete-login-race"))
        seed.commit()

    login_locked = Event()
    allow_login_commit = Event()
    deletion_finished = Event()
    errors: list[BaseException] = []

    def login_transaction() -> None:
        login_db = SessionLocal()
        try:
            # Password-auth phase may commit its own metadata, then token issuance must
            # reacquire KEY SHARE and hold it through response construction.
            locked_user = _lock_login_user_for_authentication(
                login_db,
                user_id,
            )
            assert locked_user.id == user_id
            login_db.commit()
            final_user, deleting = lock_login_for_token_issue(login_db, user_id)
            assert final_user.id == user_id
            assert deleting is False
            login_locked.set()
            if not allow_login_commit.wait(timeout=15):
                raise AssertionError("login token-issuance transaction was not released")
            login_db.rollback()
        except BaseException as exc:  # noqa: BLE001 - thread reports assertion failures
            errors.append(exc)
            login_locked.set()
            allow_login_commit.set()
        finally:
            login_db.close()

    def start_account_delete_gate() -> None:
        try:
            if not login_locked.wait(timeout=15):
                raise AssertionError("login did not acquire User KEY SHARE")
            with SessionLocal() as deleting:
                operation = _begin_or_load_account_deletion(
                    deleting,
                    user_id=user_id,
                    request_id=gate_request,
                )
                assert operation is not None
        except BaseException as exc:  # noqa: BLE001 - thread reports assertion failures
            errors.append(exc)
        finally:
            deletion_finished.set()

    login_thread = Thread(target=login_transaction, name="login-key-share")
    delete_thread = Thread(target=start_account_delete_gate, name="account-delete-gate")
    login_thread.start()
    delete_thread.start()

    assert login_locked.wait(timeout=15)
    # [人工注释][S1-022] login helper 持有 KEY SHARE 时，Account Delete 的 User FOR UPDATE
    # 不允许越过它建立 gate；这把“登录成功”和“注销开始”的顺序交给数据库串行化。
    assert not deletion_finished.wait(timeout=0.25)

    allow_login_commit.set()
    login_thread.join(timeout=15)
    delete_thread.join(timeout=15)
    assert not login_thread.is_alive()
    assert not delete_thread.is_alive()
    if errors:
        raise errors[0]

    with SessionLocal() as recovery_login:
        # [人工注释][S1-022-FIX-001] gate 已提交后仍允许重新认证拿恢复 token；
        # 但同一 user_id 进入任何普通 user-data dependency 时必须继续 423。
        recovered_user = _lock_login_user_for_authentication(recovery_login, user_id)
        assert recovered_user.id == user_id
        recovery_login.commit()

    with SessionLocal() as blocked_data_api:
        try:
            get_current_user_id(user_id, blocked_data_api)
            raise AssertionError("ordinary user API passed during Account Delete")
        except HTTPException as exc:
            assert exc.status_code == 423
            assert exc.detail == "ACCOUNT_DELETION_IN_PROGRESS"
            blocked_data_api.rollback()

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


def _assert_data_delete_entry_serializes_with_account_gate() -> None:
    user_id = uuid4()
    data_request = uuid4()
    account_request = uuid4()

    with SessionLocal() as seed:
        seed.add(User(id=user_id, nickname="account-delete-data-race"))
        seed.commit()

    data_locked = Event()
    allow_data_operation = Event()
    account_finished = Event()
    errors: list[BaseException] = []
    joined_data_request: list[object] = []

    def external_data_delete_entry() -> None:
        data_db = SessionLocal()
        try:
            lock_external_data_delete_entry(data_db, user_id=user_id)
            data_locked.set()
            if not allow_data_operation.wait(timeout=15):
                raise AssertionError("external Data Delete was not released")
            operation = _begin_or_load_operation(data_db, user_id, data_request)
            assert operation.request_id == data_request
        except BaseException as exc:  # noqa: BLE001 - thread reports assertion failures
            errors.append(exc)
            data_locked.set()
            allow_data_operation.set()
        finally:
            data_db.close()

    def start_account_gate() -> None:
        try:
            if not data_locked.wait(timeout=15):
                raise AssertionError("Data Delete did not acquire User FOR UPDATE")
            with SessionLocal() as account_db:
                operation = _begin_or_load_account_deletion(
                    account_db,
                    user_id=user_id,
                    request_id=account_request,
                )
                assert operation is not None
                joined_data_request.append(operation.data_deletion_request_id)
        except BaseException as exc:  # noqa: BLE001 - thread reports assertion failures
            errors.append(exc)
        finally:
            account_finished.set()

    data_thread = Thread(target=external_data_delete_entry, name="data-delete-entry")
    account_thread = Thread(target=start_account_gate, name="account-delete-entry")
    data_thread.start()
    account_thread.start()

    assert data_locked.wait(timeout=15)
    # [人工注释][S1-022] 外部 Data Delete 已完成“无 account gate”检查但尚未建立
    # S1-021 operation 时，Account Delete 不能插队建立自己的 canonical data request。
    assert not account_finished.wait(timeout=0.25)

    allow_data_operation.set()
    data_thread.join(timeout=15)
    account_thread.join(timeout=15)
    assert not data_thread.is_alive()
    assert not account_thread.is_alive()
    if errors:
        raise errors[0]
    assert joined_data_request == [data_request]

    with SessionLocal() as blocked_data:
        try:
            lock_external_data_delete_entry(blocked_data, user_id=user_id)
            raise AssertionError("external Data Delete passed after account gate")
        except AccountDeletionError as exc:
            assert exc.status_code == 423
            assert exc.code == "ACCOUNT_DELETION_IN_PROGRESS"
            blocked_data.rollback()

    with SessionLocal() as cleanup:
        cleanup.delete(cleanup.get(User, user_id))
        cleanup.commit()


def _assert_concurrent_account_delete_attempts_converge() -> None:
    user_id = uuid4()
    first_request = uuid4()
    second_request = uuid4()
    start = Barrier(2)
    results = []
    errors: list[BaseException] = []

    with SessionLocal() as seed:
        seed.add(User(id=user_id, nickname="account-delete-concurrent"))
        seed.flush()
        seed.add(
            AuthIdentity(
                user_id=user_id,
                provider=AuthProvider.EMAIL_PASSWORD,
                subject=f"{uuid4()}@example.test",
                secret_hash="integration-only",
            )
        )
        seed.commit()

    def worker(request_id) -> None:
        try:
            start.wait(timeout=15)
            with SessionLocal() as db:
                result = delete_current_account(
                    db,
                    user_id=user_id,
                    request_id=request_id,
                    storage=EmptyStorage(),
                    local_cleanup_ready=True,
                )
                results.append(result)
        except BaseException as exc:  # noqa: BLE001 - thread reports assertion failures
            errors.append(exc)

    first = Thread(target=worker, args=(first_request,), name="account-delete-first")
    second = Thread(target=worker, args=(second_request,), name="account-delete-second")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive()
    assert not second.is_alive()
    if errors:
        raise errors[0]

    # [人工注释][S1-022] 并发重复注销不要求调用方共享 request_id；
    # 两个请求都必须收敛到完成，且最终 canonical intent 只能是两者中先建立 gate 的一个。
    assert len(results) == 2
    assert all(result.completed for result in results)
    canonical_ids = {result.request_id for result in results}
    assert len(canonical_ids) == 1
    assert canonical_ids.issubset({first_request, second_request})

    with SessionLocal() as verify:
        assert db_count(verify, User, User.id == user_id) == 0
        assert db_count(verify, AuthIdentity, AuthIdentity.user_id == user_id) == 0
        assert db_count(
            verify,
            AccountDeletionOperation,
            AccountDeletionOperation.user_id == user_id,
        ) == 0
        assert db_count(
            verify,
            DataDeletionOperation,
            DataDeletionOperation.user_id == user_id,
        ) == 0


def main() -> None:
    _assert_login_serializes_with_account_delete_gate()
    _assert_data_delete_entry_serializes_with_account_gate()
    _assert_concurrent_account_delete_attempts_converge()
    owner_id = uuid4()
    other_id = uuid4()
    first_request = uuid4()
    second_request = uuid4()
    identity_id = uuid4()
    owner_memory_id = uuid4()
    other_memory_id = uuid4()

    with SessionLocal() as seed:
        seed.add_all(
            [
                User(id=owner_id, nickname="account-delete-pg-owner"),
                User(id=other_id, nickname="account-delete-pg-other"),
            ]
        )
        seed.flush()
        seed.add_all(
            [
                AuthIdentity(
                    id=identity_id,
                    user_id=owner_id,
                    provider=AuthProvider.EMAIL_PASSWORD,
                    subject=f"{uuid4()}@example.test",
                    secret_hash="integration-only",
                ),
                Memory(
                    id=owner_memory_id,
                    user_id=owner_id,
                    content="delete me",
                ),
                Memory(
                    id=other_memory_id,
                    user_id=other_id,
                    content="keep other user",
                ),
            ]
        )
        seed.flush()
        seed.add_all(
            [
                MemoryEmbedding(
                    memory_id=owner_memory_id,
                    user_id=owner_id,
                    memory_revision=0,
                    content_fingerprint="a" * 64,
                    provider="fixture",
                    model=MEMORY_EMBEDDING_MODEL,
                    dimensions=MEMORY_EMBEDDING_DIMENSIONS,
                    embedding=[0.01] * MEMORY_EMBEDDING_DIMENSIONS,
                ),
                MemoryEmbedding(
                    memory_id=other_memory_id,
                    user_id=other_id,
                    memory_revision=0,
                    content_fingerprint="b" * 64,
                    provider="fixture",
                    model=MEMORY_EMBEDDING_MODEL,
                    dimensions=MEMORY_EMBEDDING_DIMENSIONS,
                    embedding=[0.02] * MEMORY_EMBEDDING_DIMENSIONS,
                ),
            ]
        )
        seed.add_all(
            [
                MemoryFeedback(
                    user_id=owner_id,
                    memory_id=owner_memory_id,
                    client_uuid=uuid4(),
                    memory_revision=0,
                    action=MemoryFeedbackAction.CONFIRM.value,
                ),
                MemoryFeedback(
                    user_id=other_id,
                    memory_id=other_memory_id,
                    client_uuid=uuid4(),
                    memory_revision=0,
                    action=MemoryFeedbackAction.CONFIRM.value,
                ),
            ]
        )
        seed.commit()

    stale = SessionLocal()
    try:
        _admit_existing_user_request(stale, owner_id)
        # Release the admission-time KEY SHARE while preserving Session.info, matching a
        # real request that crossed a rollback boundary before trying a later commit.
        stale.rollback()

        with SessionLocal() as deleting:
            operation = _begin_or_load_account_deletion(
                deleting,
                user_id=owner_id,
                request_id=first_request,
            )
            assert operation is not None
            operation_id = operation.id

        with SessionLocal() as joining:
            joined = _begin_or_load_account_deletion(
                joining,
                user_id=owner_id,
                request_id=second_request,
            )
            assert joined is not None
            assert joined.id == operation_id
            assert joined.request_id == first_request

        # [人工注释][S1-022] 即使 S1-021 还没开始，AccountDeletionOperation 本身就必须
        # 让早先准入的事务 fail closed，封住“注销 gate 已建立但新数据又写回”的窗口。
        stale.add(Memory(user_id=owner_id, content="must not commit after account gate"))
        try:
            stale.commit()
            raise AssertionError("stale request committed after account deletion gate")
        except UserDataRequestStale:
            stale.rollback()
    finally:
        stale.close()

    with SessionLocal() as deleting:
        result = delete_current_account(
            deleting,
            user_id=owner_id,
            request_id=second_request,
            storage=EmptyStorage(),
            local_cleanup_ready=True,
        )
        assert result.completed is True
        assert result.request_id == first_request

    with SessionLocal() as verify:
        assert db_count(verify, User, User.id == owner_id) == 0
        assert db_count(verify, AuthIdentity, AuthIdentity.user_id == owner_id) == 0
        assert db_count(
            verify,
            AccountDeletionOperation,
            AccountDeletionOperation.user_id == owner_id,
        ) == 0
        assert db_count(
            verify,
            DataDeletionOperation,
            DataDeletionOperation.user_id == owner_id,
        ) == 0
        assert db_count(
            verify,
            MemoryEmbedding,
            MemoryEmbedding.user_id == owner_id,
        ) == 0
        assert db_count(
            verify,
            MemoryFeedback,
            MemoryFeedback.user_id == owner_id,
        ) == 0
        # Owner isolation: another account and its derived index/audit are untouched.
        assert db_count(
            verify,
            MemoryFeedback,
            MemoryFeedback.user_id == other_id,
        ) == 1
        assert verify.get(User, other_id) is not None
        assert verify.get(Memory, other_memory_id) is not None
        assert verify.get(MemoryEmbedding, other_memory_id) is not None
        verify.delete(verify.get(User, other_id))
        verify.commit()


def db_count(db, model, predicate) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(predicate)) or 0)


if __name__ == "__main__":
    main()
