"""PostgreSQL downgrade/re-upgrade gate for V2-005 LifeEvent migration."""

from __future__ import annotations

import os
import subprocess

from sqlalchemy import create_engine, inspect

DATABASE_URL = os.environ["DATABASE_URL"]


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def main() -> None:
    _alembic("downgrade", "0022_person_relationship_graph")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    inspector = inspect(engine)
    assert "life_events" not in inspector.get_table_names()
    assert "life_event_memory_links" not in inspector.get_table_names()
    engine.dispose()

    _alembic("upgrade", "head")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"life_events", "life_event_memory_links"} <= tables

    life_uniques = {item["name"] for item in inspector.get_unique_constraints("life_events")}
    assert "uq_life_events_id_user_id" in life_uniques

    link_uniques = {
        item["name"] for item in inspector.get_unique_constraints("life_event_memory_links")
    }
    assert "uq_life_event_memory_links_event_memory" in link_uniques

    life_fks = {item["name"] for item in inspector.get_foreign_keys("life_events")}
    assert "fk_life_events_place_owner" in life_fks

    link_fks = {
        item["name"] for item in inspector.get_foreign_keys("life_event_memory_links")
    }
    assert "fk_life_event_memory_links_event_owner" in link_fks
    assert "fk_life_event_memory_links_memory_owner" in link_fks

    life_indexes = {item["name"] for item in inspector.get_indexes("life_events")}
    assert "ix_life_events_user_started" in life_indexes
    assert "ix_life_events_user_kind" in life_indexes

    engine.dispose()
    print("PostgreSQL 0023 LifeEvent downgrade/re-upgrade PASS")


if __name__ == "__main__":
    main()
