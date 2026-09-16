# [人工注释][FND-024] PostgreSQL 专用集成验收：
# 验证 CURRENT partial unique index 与 FOR UPDATE 锁语义。
import os
from datetime import UTC, datetime, timedelta
from threading import Thread
from uuid import uuid4

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models import ObjectItem, ObjectLocation, ObjectLocationStatus, User


def _database_url() -> str:
    value = os.environ["DATABASE_URL"]
    if not value.startswith("postgresql"):
        raise RuntimeError("PostgreSQL integration check requires a PostgreSQL DATABASE_URL")
    return value


def _verify_unique_current(engine, user_id, object_id) -> None:
    with Session(engine) as db:
        first = ObjectLocation(
            object_id=object_id,
            user_id=user_id,
            location_text="第一条 CURRENT",
            recorded_at=datetime.now(UTC),
            status=ObjectLocationStatus.CURRENT,
        )
        db.add(first)
        db.commit()

        duplicate = ObjectLocation(
            object_id=object_id,
            user_id=user_id,
            location_text="第二条 CURRENT",
            recorded_at=datetime.now(UTC) + timedelta(seconds=1),
            status=ObjectLocationStatus.CURRENT,
        )
        db.add(duplicate)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL must reject a second CURRENT location for one object")


def _verify_for_update_lock(engine, object_id) -> None:
    result: list[str] = []

    def contender() -> None:
        with Session(engine) as db:
            db.execute(text("SET LOCAL lock_timeout = '500ms'"))
            try:
                db.scalar(
                    select(ObjectItem)
                    .where(ObjectItem.id == object_id)
                    .with_for_update()
                )
            except OperationalError:
                db.rollback()
                result.append("blocked")
            else:
                db.rollback()
                result.append("not-blocked")

    with Session(engine) as holder:
        with holder.begin():
            locked = holder.scalar(
                select(ObjectItem).where(ObjectItem.id == object_id).with_for_update()
            )
            assert locked is not None

            thread = Thread(target=contender, daemon=True)
            thread.start()
            thread.join(timeout=5)
            if thread.is_alive():
                raise AssertionError("FOR UPDATE contender did not respect PostgreSQL lock_timeout")
            if result != ["blocked"]:
                raise AssertionError(f"FOR UPDATE did not serialize the contender: {result}")


def _verify_stale_and_add_share_object_lock(engine, user_id, object_id) -> None:
    # [人工注释][S1-011] 真实 PostgreSQL 门禁：stale 事务持有 Object FOR UPDATE 时，
    # 代表 add 路径的同一 Object FOR UPDATE 必须被阻塞，确保失效水位与新位置写入严格串行。
    result: list[str] = []
    invalidated_at = datetime.now(UTC) + timedelta(seconds=2)

    def add_contender() -> None:
        with Session(engine) as db:
            db.execute(text("SET LOCAL lock_timeout = '500ms'"))
            try:
                db.scalar(
                    select(ObjectItem)
                    .where(ObjectItem.id == object_id)
                    .with_for_update()
                )
            except OperationalError:
                db.rollback()
                result.append("add-blocked-by-stale")
            else:
                db.rollback()
                result.append("add-not-blocked")

    with Session(engine) as stale_db:
        with stale_db.begin():
            locked = stale_db.scalar(
                select(ObjectItem)
                .where(ObjectItem.id == object_id)
                .with_for_update()
            )
            assert locked is not None

            current = stale_db.scalar(
                select(ObjectLocation).where(
                    ObjectLocation.object_id == object_id,
                    ObjectLocation.status == ObjectLocationStatus.CURRENT,
                )
            )
            assert current is not None
            current.status = ObjectLocationStatus.STALE
            stale_db.add(
                ObjectLocation(
                    object_id=object_id,
                    user_id=user_id,
                    location_text="用户已确认原位置失效",
                    recorded_at=invalidated_at,
                    status=ObjectLocationStatus.UNKNOWN,
                )
            )
            stale_db.flush()

            thread = Thread(target=add_contender, daemon=True)
            thread.start()
            thread.join(timeout=5)
            if thread.is_alive():
                raise AssertionError("stale/add lock contender did not finish")
            if result != ["add-blocked-by-stale"]:
                raise AssertionError(f"stale/add did not share Object lock: {result}")

    with Session(engine) as verify_db:
        current = verify_db.scalar(
            select(ObjectLocation).where(
                ObjectLocation.object_id == object_id,
                ObjectLocation.status == ObjectLocationStatus.CURRENT,
            )
        )
        watermark = verify_db.scalar(
            select(ObjectLocation)
            .where(
                ObjectLocation.object_id == object_id,
                ObjectLocation.status == ObjectLocationStatus.UNKNOWN,
            )
            .order_by(ObjectLocation.recorded_at.desc())
            .limit(1)
        )
        assert current is None
        assert watermark is not None
        assert watermark.recorded_at == invalidated_at


def main() -> None:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    user_id = uuid4()
    object_id = uuid4()

    with Session(engine) as db:
        # [人工注释][FND-024] 测试夹具按真实 FK 依赖顺序提交，避免 ORM 无 relationship 时乱序插入。
        db.add(User(id=user_id, nickname="PostgreSQL CI"))
        db.commit()
        db.add(
            ObjectItem(
                id=object_id,
                user_id=user_id,
                name="PostgreSQL 并发测试物品",
                normalized_name=f"postgres-ci-{object_id}",
            )
        )
        db.commit()

    try:
        _verify_unique_current(engine, user_id, object_id)
        _verify_for_update_lock(engine, object_id)
        _verify_stale_and_add_share_object_lock(engine, user_id, object_id)
    finally:
        with Session(engine) as db:
            user = db.get(User, user_id)
            if user is not None:
                db.delete(user)
                db.commit()
        engine.dispose()


if __name__ == "__main__":
    main()
