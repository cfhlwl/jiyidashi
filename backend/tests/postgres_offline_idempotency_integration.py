from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.idempotency_models import ClientMutation
from app.models import Memory, MemorySource, MemoryType, SourceType, User
from app.schemas import MemoryCreate
from app.services.idempotency_service import execute_idempotent_mutation
from app.services.memory_service import create_user_memory, get_memory_for_user

USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CLIENT_UUID = UUID("99999999-9999-4999-8999-999999999999")
barrier = Barrier(2)


def _run_one() -> UUID:
    payload = MemoryCreate(
        memory_type=MemoryType.NOTE,
        content="PostgreSQL 并发离线重放只能创建一次",
        capture_source=SourceType.USER_TEXT.value,
    )
    with SessionLocal() as db:
        def create_resource(session):
            # 两个独立 Session 都先确认账本不存在，再同时继续创建，
            # 强制触发数据库唯一键竞争，证明去重不是单进程时序巧合。
            barrier.wait(timeout=10)
            return create_user_memory(session, USER_ID, payload)

        memory = execute_idempotent_mutation(
            db,
            user_id=USER_ID,
            operation_type="MEMORY_CREATE",
            client_uuid=CLIENT_UUID,
            fingerprint_payload=payload.model_dump(mode="json"),
            resource_type="MEMORY",
            create_resource=create_resource,
            resource_id=lambda item: item.id,
            load_resource=lambda session, resource_id: get_memory_for_user(
                session,
                USER_ID,
                resource_id,
            ),
        )
        return memory.id


def main() -> None:
    with SessionLocal() as db:
        db.query(ClientMutation).filter(ClientMutation.user_id == USER_ID).delete()
        db.query(MemorySource).filter(
            MemorySource.memory_id.in_(
                select(Memory.id).where(Memory.user_id == USER_ID)
            )
        ).delete(synchronize_session=False)
        db.query(Memory).filter(Memory.user_id == USER_ID).delete()
        db.query(User).filter(User.id == USER_ID).delete()
        db.add(User(id=USER_ID, nickname="offline-idempotency-ci"))
        db.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(_run_one)
        second_future = executor.submit(_run_one)
        first_id = first_future.result(timeout=20)
        second_id = second_future.result(timeout=20)

    assert first_id == second_id
    with SessionLocal() as db:
        memory_count = db.scalar(
            select(func.count(Memory.id)).where(Memory.user_id == USER_ID)
        )
        source_count = db.scalar(
            select(func.count(MemorySource.id))
            .join(Memory, Memory.id == MemorySource.memory_id)
            .where(Memory.user_id == USER_ID)
        )
        mutation_count = db.scalar(
            select(func.count(ClientMutation.id)).where(
                ClientMutation.user_id == USER_ID,
                ClientMutation.operation_type == "MEMORY_CREATE",
                ClientMutation.client_uuid == CLIENT_UUID,
            )
        )
        assert memory_count == 1
        assert source_count == 1
        assert mutation_count == 1

    print("PostgreSQL offline idempotency concurrency PASS")


if __name__ == "__main__":
    main()
