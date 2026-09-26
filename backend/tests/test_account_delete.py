from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthRateLimitBucket
from app.core.db import SessionLocal
from app.data_deletion_models import DataDeletionOperation, DataDeletionStatus
from app.main import app
from app.models import Memory, User
from app.person_memory_models import PersonMemoryLink, PersonMemoryRelationKind
from app.person_models import Person, PersonAlias
from app.services import account_deletion_service
from app.services.object_storage import ObjectStorageError, get_object_storage


class AccountDeleteStorage:
    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.fail_once: set[str] = set()

    def iter_object_keys(self, prefix: str) -> Iterator[str]:
        yield from sorted(key for key in self.objects if key.startswith(prefix))

    def delete_object(self, object_key: str) -> None:
        if object_key in self.fail_once:
            self.fail_once.remove(object_key)
            raise ObjectStorageError("synthetic account-delete storage failure")
        self.objects.discard(object_key)


@pytest.fixture
def account_delete_storage():
    storage = AccountDeleteStorage()
    app.dependency_overrides[get_object_storage] = lambda: storage
    yield storage
    app.dependency_overrides.pop(get_object_storage, None)


@pytest.fixture(autouse=True)
def _isolate_account_delete_auth_rate_limits(client):
    # [人工注释][S1-022][TEST] 显式依赖 client，确保 FastAPI lifespan/create_schema
    # 先建立 SQLite 表；随后再隔离本文件正式 register/login 产生的持久限流 bucket。
    # AuthRateLimitBucket 是跨请求持久状态；若不在测试边界清理，会污染后续无关认证测试并触发 429。
    with SessionLocal() as db:
        db.query(AuthRateLimitBucket).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(AuthRateLimitBucket).delete()
        db.commit()


async def _register(
    client,
    *,
    email: str,
    password: str = "Delete-Me-123!",
    nickname: str = "Delete Owner",
) -> tuple[dict[str, str], UUID]:
    response = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "nickname": nickname,
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    return (
        {"Authorization": f"Bearer {payload['access_token']}"},
        UUID(payload["user_id"]),
    )


@pytest.mark.asyncio
async def test_account_delete_requires_distinct_exact_confirmation(
    client,
    account_delete_storage,
):
    headers, user_id = await _register(
        client,
        email=f"confirm-{uuid4()}@example.com",
    )
    rejected = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "confirmation": "DELETE_MY_DATA",
            "local_cleanup_ready": False,
        },
    )
    assert rejected.status_code == 422
    with SessionLocal() as db:
        assert db.get(User, user_id) is not None
        assert db.scalar(
            select(AccountDeletionOperation.id).where(
                AccountDeletionOperation.user_id == user_id
            )
        ) is None


@pytest.mark.asyncio
async def test_prepare_gate_survives_restart_before_local_cleanup(
    client,
    account_delete_storage: AccountDeleteStorage,
):
    email = f"prepare-recovery-{uuid4()}@example.com"
    password = "Delete-Me-123!"
    headers, user_id = await _register(client, email=email, password=password)
    with SessionLocal() as db:
        memory = Memory(user_id=user_id, content="must remain until local cleanup ready")
        db.add(memory)
        db.commit()
        memory_id = memory.id

    request_id = uuid4()
    prepared = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(request_id),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": False,
        },
    )
    assert prepared.status_code == 202
    assert prepared.json()["completed"] is False
    assert prepared.json()["data_deletion_status"] is None

    with SessionLocal() as db:
        assert db.get(User, user_id) is not None
        assert db.get(Memory, memory_id) is not None
        assert db.scalar(
            select(AccountDeletionOperation.id).where(
                AccountDeletionOperation.user_id == user_id
            )
        ) is not None
        # [人工注释][S1-022-FIX-002] PREPARE 只建立 durable account gate；
        # 官方客户端尚未确认本机 purge 完成前，S1-021 甚至不能开始。
        assert db.scalar(
            select(DataDeletionOperation.id).where(
                DataDeletionOperation.user_id == user_id
            )
        ) is None

    blocked = await client.get("/v1/user", headers=headers)
    assert blocked.status_code == 423
    assert blocked.json()["detail"] == "ACCOUNT_DELETION_IN_PROGRESS"

    recovery_login = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert recovery_login.status_code == 200
    assert recovery_login.json()["account_deletion_in_progress"] is True
    recovery_headers = {
        "Authorization": f"Bearer {recovery_login.json()['access_token']}"
    }

    completed = await client.post(
        "/v1/account/delete",
        headers=recovery_headers,
        json={
            "request_id": str(uuid4()),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["completed"] is True
    assert completed.json()["request_id"] == str(request_id)
    with SessionLocal() as db:
        assert db.get(User, user_id) is None
        assert db.get(Memory, memory_id) is None


@pytest.mark.asyncio
async def test_account_delete_removes_identity_invalidates_old_token_and_allows_fresh_reregister(
    client,
    account_delete_storage,
):
    email = f"delete-{uuid4()}@example.com"
    password = "Delete-Me-123!"
    headers, user_id = await _register(client, email=email, password=password)
    with SessionLocal() as db:
        memory = Memory(user_id=user_id, content="must disappear with account")
        person = Person(
            user_id=user_id,
            display_name="注销联系人",
            relationship_label="朋友",
            note="account-delete private person",
        )
        db.add_all([memory, person])
        db.flush()
        alias = PersonAlias(
            user_id=user_id,
            person_id=person.id,
            alias="联系人别名",
            normalized_alias="联系人别名",
        )
        db.add(alias)
        db.flush()
        link = PersonMemoryLink(
            user_id=user_id,
            person_id=person.id,
            memory_id=memory.id,
            relation_kind=PersonMemoryRelationKind.RELATED,
            revision=0,
        )
        db.add(link)
        db.commit()
        memory_id = memory.id
        person_id = person.id
        alias_id = alias.id
        link_id = link.id

    request_id = uuid4()
    deleted = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(request_id),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert deleted.status_code == 200
    assert deleted.json()["completed"] is True
    assert deleted.json()["request_id"] == str(request_id)
    assert deleted.json()["data_deletion_status"] == "COMPLETED"

    with SessionLocal() as db:
        assert db.get(User, user_id) is None
        assert db.get(Memory, memory_id) is None
        assert db.get(Person, person_id) is None
        assert db.get(PersonAlias, alias_id) is None
        assert db.get(PersonMemoryLink, link_id) is None
        assert db.scalar(
            select(AuthIdentity.id).where(AuthIdentity.user_id == user_id)
        ) is None
        assert db.scalar(
            select(AccountDeletionOperation.id).where(
                AccountDeletionOperation.user_id == user_id
            )
        ) is None
        assert db.scalar(
            select(DataDeletionOperation.id).where(
                DataDeletionOperation.user_id == user_id
            )
        ) is None

    # [人工注释][S1-022] JWT 本身是无状态的；删除后的旧 token 必须因 User 已不存在
    # 被普通 API 的权威 User lookup 拒绝，不能继续读取旧账号空间。
    old_token = await client.get("/v1/user", headers=headers)
    assert old_token.status_code == 404
    assert old_token.json()["detail"] == "USER_NOT_FOUND"

    old_login = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert old_login.status_code == 401
    assert old_login.json()["detail"] == "INVALID_CREDENTIALS"

    # 完成响应若在网络途中丢失，旧 token 重放注销仍把 User absence 当作幂等完成。
    replay = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["completed"] is True

    # 不保存永久 tombstone：用户以后可用相同邮箱明确创建一个全新的账号。
    fresh = await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "nickname": "Fresh Account",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )
    assert fresh.status_code == 201
    assert UUID(fresh.json()["user_id"]) != user_id


@pytest.mark.asyncio
async def test_storage_failure_keeps_identity_locked_and_different_request_resumes(
    client,
    account_delete_storage: AccountDeleteStorage,
):
    email = f"retry-{uuid4()}@example.com"
    password = "Delete-Me-123!"
    headers, user_id = await _register(client, email=email, password=password)
    orphan = f"media/{user_id}/late-object"
    account_delete_storage.objects.add(orphan)
    account_delete_storage.fail_once.add(orphan)

    first_request = uuid4()
    failed = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(first_request),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == "DATA_DELETION_STORAGE_UNAVAILABLE"

    with SessionLocal() as db:
        assert db.get(User, user_id) is not None
        assert db.scalar(
            select(AuthIdentity.id).where(AuthIdentity.user_id == user_id)
        ) is not None
        account_op = db.scalar(
            select(AccountDeletionOperation).where(
                AccountDeletionOperation.user_id == user_id
            )
        )
        assert account_op is not None
        assert account_op.request_id == first_request
        data_op = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id
                == account_op.data_deletion_request_id,
            )
        )
        assert data_op is not None
        assert data_op.status == DataDeletionStatus.STORAGE_FAILED
        # Test-only convergence: remote DELETE may have failed before removing the object.
        # Remove that synthetic remote object so the retry's authoritative LIST is empty;
        # then fast-forward the already-recorded quiet window. A still-live key would
        # correctly restart quiet and must not be hidden by this test.
        account_delete_storage.objects.discard(orphan)
        data_op.storage_quiet_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    blocked_api = await client.get("/v1/user", headers=headers)
    assert blocked_api.status_code == 423
    assert blocked_api.json()["detail"] == "ACCOUNT_DELETION_IN_PROGRESS"

    # [人工注释][S1-022-FIX-001] 客户端重启后原 token 已丢失，因此删除中的账号
    # 必须允许密码重新认证拿恢复 token；这个 token 的普通 API 仍被 account gate 锁住。
    recovery_login = await client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert recovery_login.status_code == 200
    assert recovery_login.json()["account_deletion_in_progress"] is True
    recovery_headers = {
        "Authorization": f"Bearer {recovery_login.json()['access_token']}"
    }
    recovery_api = await client.get("/v1/user", headers=recovery_headers)
    assert recovery_api.status_code == 423
    assert recovery_api.json()["detail"] == "ACCOUNT_DELETION_IN_PROGRESS"

    # [人工注释][S1-022] Account gate 已存在时，外部 Data Delete 不能再创建第二条
    # request；唯一允许推进 S1-021 的入口是 Account Delete orchestrator。
    competing_data_request = uuid4()
    blocked_data_delete = await client.post(
        "/v1/data/delete",
        headers=headers,
        json={
            "request_id": str(competing_data_request),
            "confirmation": "DELETE_MY_DATA",
        },
    )
    assert blocked_data_delete.status_code == 423
    assert blocked_data_delete.json()["detail"] == "ACCOUNT_DELETION_IN_PROGRESS"
    with SessionLocal() as db:
        assert db.scalar(
            select(DataDeletionOperation.id).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == competing_data_request,
            )
        ) is None

    # 客户端重启后即使丢了首次 request_id，也 join 同一 operation，而不是永远 409。
    resumed = await client.post(
        "/v1/account/delete",
        headers=recovery_headers,
        json={
            "request_id": str(uuid4()),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert resumed.status_code == 200
    assert resumed.json()["completed"] is True
    assert resumed.json()["request_id"] == str(first_request)
    with SessionLocal() as db:
        assert db.get(User, user_id) is None
        assert db.scalar(
            select(AuthIdentity.id).where(AuthIdentity.user_id == user_id)
        ) is None


@pytest.mark.asyncio
async def test_account_delete_reuses_preexisting_active_data_delete(
    client,
    account_delete_storage: AccountDeleteStorage,
):
    headers, user_id = await _register(
        client,
        email=f"join-data-{uuid4()}@example.com",
    )
    data_request_id = uuid4()
    with SessionLocal() as db:
        db.add(
            DataDeletionOperation(
                user_id=user_id,
                request_id=data_request_id,
                status=DataDeletionStatus.STORAGE_FAILED,
            )
        )
        db.commit()

    response = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["completed"] is True
    with SessionLocal() as db:
        assert db.get(User, user_id) is None



@pytest.mark.asyncio
async def test_account_delete_never_reuses_historical_completed_data_request_id(
    client,
    account_delete_storage: AccountDeleteStorage,
):
    headers, user_id = await _register(
        client,
        email=f"historical-data-id-{uuid4()}@example.com",
    )
    reused_client_request = uuid4()
    with SessionLocal() as db:
        db.add(
            DataDeletionOperation(
                user_id=user_id,
                request_id=reused_client_request,
                status=DataDeletionStatus.COMPLETED,
                deleted_counts={},
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()

    # 新数据/对象是在历史 Data Delete 完成后才出现。若 M 错误复用 account request_id，
    # delete_all_user_data 会直接命中旧 COMPLETED receipt，下面这个 blob 将永久残留。
    orphan = f"media/{user_id}/created-after-old-data-delete"
    account_delete_storage.objects.add(orphan)

    first = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(reused_client_request),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert first.status_code == 202
    assert orphan not in account_delete_storage.objects

    with SessionLocal() as db:
        account_op = db.scalar(
            select(AccountDeletionOperation).where(
                AccountDeletionOperation.user_id == user_id
            )
        )
        assert account_op is not None
        assert account_op.data_deletion_request_id != reused_client_request
        fresh_data_op = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id,
                DataDeletionOperation.request_id == account_op.data_deletion_request_id,
            )
        )
        assert fresh_data_op is not None
        assert fresh_data_op.status == DataDeletionStatus.WAITING_STORAGE_QUIET
        fresh_data_op.storage_quiet_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    completed = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["completed"] is True
    with SessionLocal() as db:
        assert db.get(User, user_id) is None


@pytest.mark.asyncio
async def test_final_identity_transaction_rolls_back_and_can_resume(
    client,
    account_delete_storage: AccountDeleteStorage,
    monkeypatch,
):
    email = f"finalize-retry-{uuid4()}@example.com"
    headers, user_id = await _register(client, email=email)
    request_id = uuid4()

    original = account_deletion_service._delete_auth_identities

    def fail_after_identity_delete(db, target_user_id):
        original(db, target_user_id)
        raise RuntimeError("synthetic account finalize failure")

    monkeypatch.setattr(
        account_deletion_service,
        "_delete_auth_identities",
        fail_after_identity_delete,
    )
    failed = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(request_id),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert failed.status_code == 503
    assert failed.json()["detail"] == "ACCOUNT_DELETION_DATABASE_FAILED"

    with SessionLocal() as db:
        # [人工注释][S1-022] 最终身份事务失败后必须整体 rollback：
        # 身份/User/gate/已完成 S1-021 receipt 全都保留，才能用同一 durable intent 恢复。
        assert db.get(User, user_id) is not None
        assert db.scalar(
            select(AuthIdentity.id).where(AuthIdentity.user_id == user_id)
        ) is not None
        assert db.scalar(
            select(AccountDeletionOperation.id).where(
                AccountDeletionOperation.user_id == user_id
            )
        ) is not None
        data_op = db.scalar(
            select(DataDeletionOperation).where(
                DataDeletionOperation.user_id == user_id
            )
        )
        assert data_op is not None
        assert data_op.status == DataDeletionStatus.COMPLETED

    monkeypatch.setattr(
        account_deletion_service,
        "_delete_auth_identities",
        original,
    )
    completed = await client.post(
        "/v1/account/delete",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "confirmation": "DELETE_MY_ACCOUNT",
            "local_cleanup_ready": True,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["completed"] is True
    assert completed.json()["request_id"] == str(request_id)
    with SessionLocal() as db:
        assert db.get(User, user_id) is None
        assert db.scalar(
            select(AuthIdentity.id).where(AuthIdentity.user_id == user_id)
        ) is None
