"""PostgreSQL integration gate for Stage 2Q mixed Timeline pagination."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Memory, Place, User, Visit
from app.services.timeline_service import list_timeline

USER_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
PLACE_ID = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1")
MEMORY_HIGH = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
MEMORY_LOW = UUID("22222222-2222-4222-8222-222222222222")
VISIT_HIGH = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
VISIT_LOW = UUID("11111111-1111-4111-8111-111111111111")


def main() -> None:
    tie_time = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
    with SessionLocal() as db:
        existing = db.get(User, USER_ID)
        if existing is not None:
            db.delete(existing)
            db.commit()

        db.add(User(id=USER_ID, nickname="timeline-pg", timezone="Asia/Shanghai"))
        # [人工注释][S2-011] 测试 seed 不依赖 ORM relationship 排序；先把 owner
        # 真正写入数据库，再创建带 FK 的 Place，避免把 seed 时序误当 Timeline 失败。
        db.flush()
        db.add(
            Place(
                id=PLACE_ID,
                user_id=USER_ID,
                name="PostgreSQL 地点",
            )
        )
        db.flush()
        db.add_all(
            [
                Memory(
                    id=MEMORY_HIGH,
                    user_id=USER_ID,
                    content="memory-high",
                    occurred_at=tie_time,
                ),
                Memory(
                    id=MEMORY_LOW,
                    user_id=USER_ID,
                    content="memory-low",
                    occurred_at=tie_time,
                ),
                Visit(
                    id=VISIT_HIGH,
                    user_id=USER_ID,
                    place_id=PLACE_ID,
                    arrived_at=tie_time,
                    finalized_at=tie_time,
                ),
                Visit(
                    id=VISIT_LOW,
                    user_id=USER_ID,
                    place_id=PLACE_ID,
                    arrived_at=tie_time,
                ),
            ]
        )
        db.commit()

    # [人工注释][S2-011] 四条记录时间完全相同，强制验证跨表 kind + UUID
    # tie-break 和 cursor SQL predicate 在真实 PostgreSQL 上不会重复/漏页。
    with SessionLocal() as db:
        first = list_timeline(
            db,
            user_id=USER_ID,
            day=date(2026, 9, 20),
            limit=2,
            cursor_value=None,
        )
        assert [(item.kind.value, item.id) for item in first.items] == [
            ("MEMORY", MEMORY_HIGH),
            ("MEMORY", MEMORY_LOW),
        ]
        assert first.next_cursor is not None

        second = list_timeline(
            db,
            user_id=USER_ID,
            day=date(2026, 9, 20),
            limit=2,
            cursor_value=first.next_cursor,
        )
        assert [(item.kind.value, item.id) for item in second.items] == [
            ("VISIT", VISIT_HIGH),
            ("VISIT", VISIT_LOW),
        ]
        assert second.next_cursor is None
        assert second.items[0].place_name == "PostgreSQL 地点"
        assert second.items[0].visit_finalized is True
        assert second.items[1].visit_finalized is False

        all_ids = [item.id for item in first.items + second.items]
        assert len(all_ids) == len(set(all_ids)) == 4

    with SessionLocal() as db:
        user = db.get(User, USER_ID)
        assert user is not None
        db.delete(user)
        db.commit()
        assert db.scalar(select(User.id).where(User.id == USER_ID)) is None

    print("PostgreSQL Timeline mixed pagination PASS")


if __name__ == "__main__":
    main()
