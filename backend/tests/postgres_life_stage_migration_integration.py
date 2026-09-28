"""PostgreSQL downgrade/re-upgrade gate for V2-006 LifeStage migration."""

from __future__ import annotations

import os
import subprocess

from sqlalchemy import create_engine, inspect

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def main() -> None:
    _alembic("downgrade", "0023_life_event_foundation")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    inspector = inspect(engine)
    assert "life_stages" not in inspector.get_table_names()
    assert "life_stage_event_links" not in inspector.get_table_names()
    engine.dispose()

    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"life_stages", "life_stage_event_links"} <= tables

    stage_uniques = {
        item["name"] for item in inspector.get_unique_constraints("life_stages")
    }
    assert "uq_life_stages_id_user_id" in stage_uniques

    link_uniques = {
        item["name"]
        for item in inspector.get_unique_constraints("life_stage_event_links")
    }
    assert "uq_life_stage_event_links_stage_event" in link_uniques

    link_fks = {
        item["name"] for item in inspector.get_foreign_keys("life_stage_event_links")
    }
    assert "fk_life_stage_event_links_stage_owner" in link_fks
    assert "fk_life_stage_event_links_event_owner" in link_fks

    stage_indexes = {item["name"] for item in inspector.get_indexes("life_stages")}
    assert "ix_life_stages_user_started" in stage_indexes
    assert "ix_life_stages_user_kind" in stage_indexes

    engine.dispose()
    print("PostgreSQL 0024 LifeStage downgrade/re-upgrade PASS")


if __name__ == "__main__":
    main()
