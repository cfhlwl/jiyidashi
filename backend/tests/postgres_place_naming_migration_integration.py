"""Seeded PostgreSQL regression for the 0010 -> 0011 Place naming backfill."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def main() -> None:
    # [人工注释][S2-009][S2-010] 空库 upgrade 只能证明 DDL 可执行，不能证明 legacy
    # Place 会被正确分类。这里真实回到 0010、写三类旧数据，再执行正式 0011 migration。
    _alembic("downgrade", "0010_location_visit")

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    user_id = uuid4()
    user_named_id = uuid4()
    automatic_id = uuid4()
    unnamed_id = uuid4()
    now = datetime.now(UTC)

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users
                    (id, nickname, phone, email, timezone, locale, created_at, updated_at)
                VALUES
                    (:id, :nickname, NULL, NULL, :timezone, :locale, :created_at, :updated_at)
                """
            ),
            {
                "id": user_id,
                "nickname": "place-migration-seed",
                "timezone": "Asia/Shanghai",
                "locale": "zh-CN",
                "created_at": now,
                "updated_at": now,
            },
        )
        for place_id, name, is_user_named in (
            (user_named_id, "家", True),
            (automatic_id, "咖啡店", False),
            (unnamed_id, "未命名地点", False),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO places
                        (
                            id, user_id, name, cluster_key,
                            latitude, longitude, address, category,
                            first_visited_at, last_visited_at,
                            visit_count, is_user_named, created_at
                        )
                    VALUES
                        (
                            :id, :user_id, :name, NULL,
                            NULL, NULL, NULL, NULL,
                            NULL, NULL,
                            0, :is_user_named, :created_at
                        )
                    """
                ),
                {
                    "id": place_id,
                    "user_id": user_id,
                    "name": name,
                    "is_user_named": is_user_named,
                    "created_at": now,
                },
            )

    _alembic("upgrade", "head")

    with engine.begin() as connection:
        rows = {
            row.id: row
            for row in connection.execute(
                text(
                    """
                    SELECT
                        id,
                        name,
                        automatic_name,
                        automatic_name_source,
                        user_name,
                        name_revision,
                        is_user_named
                    FROM places
                    WHERE user_id = :user_id
                    """
                ),
                {"user_id": user_id},
            ).mappings()
        }

        user_named = rows[user_named_id]
        assert user_named.name == "家"
        assert user_named.user_name == "家"
        assert user_named.automatic_name is None
        assert user_named.automatic_name_source is None
        assert user_named.name_revision == 0
        assert user_named.is_user_named is True

        automatic = rows[automatic_id]
        assert automatic.name == "咖啡店"
        assert automatic.user_name is None
        assert automatic.automatic_name == "咖啡店"
        assert automatic.automatic_name_source == "LEGACY"
        assert automatic.name_revision == 0
        assert automatic.is_user_named is False

        unnamed = rows[unnamed_id]
        assert unnamed.name == "未命名地点"
        assert unnamed.user_name is None
        assert unnamed.automatic_name is None
        assert unnamed.automatic_name_source is None
        assert unnamed.name_revision == 0
        assert unnamed.is_user_named is False

        # 删除 seed，后续 PostgreSQL gates 继续在正常 head schema 上运行。
        connection.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id})

    engine.dispose()
    print("PostgreSQL 0010->0011 Place naming backfill PASS")


if __name__ == "__main__":
    main()
