"""PostgreSQL migration gate for S4-011 Elder Mode default FALSE."""

from __future__ import annotations

import os
import subprocess
from uuid import uuid4

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def main() -> None:
    _alembic("downgrade", "0018_arrival_home_reminder")

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    legacy_user_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (
                    id,
                    nickname,
                    timezone,
                    locale,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    'legacy-elder-default',
                    'Asia/Shanghai',
                    'zh-CN',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
                """
            ),
            {"id": legacy_user_id},
        )
    engine.dispose()

    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT elder_mode_enabled
                FROM users
                WHERE id = :id
                """
            ),
            {"id": legacy_user_id},
        ).one()
        assert row.elder_mode_enabled is False

        connection.execute(
            text("DELETE FROM users WHERE id = :id"),
            {"id": legacy_user_id},
        )
    engine.dispose()
    print("PostgreSQL Elder Mode migration default gate: PASS")


if __name__ == "__main__":
    main()
