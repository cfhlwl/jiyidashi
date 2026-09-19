"""PostgreSQL lock coverage for Reminder <-> Memory deletion safety."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.db import SessionLocal
from app.models import Memory, Reminder, ReminderStatus, User
from app.schemas import ReminderCreate
from app.services.memory_service import get_memory_for_user, soft_delete_memory
from app.services.reminder_service import ReminderNotFound, create_reminder


def main() -> None:
    user_id = uuid4()
    memory_id = uuid4()
    reminder_id = uuid4()

    with SessionLocal() as seed:
        seed.add(User(id=user_id, nickname="reminder-lock-owner"))
        seed.flush()
        seed.add(Memory(id=memory_id, user_id=user_id, content="delete me safely"))
        seed.add(
            Reminder(
                id=reminder_id,
                user_id=user_id,
                memory_id=memory_id,
                title="existing pending reminder",
                remind_at=datetime.now(UTC) + timedelta(hours=1),
                status=ReminderStatus.PENDING,
            )
        )
        seed.commit()

    deleting = SessionLocal()
    creating = SessionLocal()
    try:
        # [人工注释][S1-025] 删除事务先拿 Memory FOR UPDATE 并保持未提交。
        # 另一 Session 的 create_reminder 必须尝试同一行锁，而不是绕过删除状态检查。
        memory = get_memory_for_user(
            deleting,
            user_id,
            memory_id,
            for_update=True,
        )
        assert memory is not None
        soft_delete_memory(deleting, memory)

        creating.execute(text("SET LOCAL lock_timeout = '150ms'"))
        try:
            create_reminder(
                creating,
                user_id=user_id,
                payload=ReminderCreate(
                    memory_id=memory_id,
                    title="must block while delete owns row",
                    remind_at=datetime.now(UTC) + timedelta(hours=2),
                ),
            )
            raise AssertionError("reminder create bypassed the Memory delete row lock")
        except OperationalError:
            # lock_timeout is expected proof that create_reminder reached FOR UPDATE.
            creating.rollback()

        deleting.commit()

        # 删除提交后，新的事务必须把该 Memory 当作不可提醒资源，而不是重新建 PENDING。
        try:
            create_reminder(
                creating,
                user_id=user_id,
                payload=ReminderCreate(
                    memory_id=memory_id,
                    title="must fail after delete",
                    remind_at=datetime.now(UTC) + timedelta(hours=3),
                ),
            )
            raise AssertionError("deleted Memory accepted a new reminder")
        except ReminderNotFound as exc:
            assert exc.code == "REMINDER_MEMORY_NOT_FOUND"
            creating.rollback()
    finally:
        deleting.close()
        creating.close()

    with SessionLocal() as verify:
        memory = verify.get(Memory, memory_id)
        reminder = verify.get(Reminder, reminder_id)
        assert memory is not None
        assert memory.is_deleted is True
        assert reminder is not None
        assert reminder.status == ReminderStatus.CANCELLED
        assert reminder.memory_id is None

        rows = verify.query(Reminder).filter(Reminder.user_id == user_id).all()
        assert [item.id for item in rows] == [reminder_id]

        verify.delete(verify.get(User, user_id))
        verify.commit()


if __name__ == "__main__":
    main()
