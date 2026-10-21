from __future__ import annotations

import sys
from uuid import UUID

import pytest

from app.core.db import SessionLocal
from app.maintenance.place_naming_backfill import (
    main,
    read_only_place_naming_inventory,
)
from app.models import Place


@pytest.mark.asyncio
async def test_inventory_is_read_only_redacted_and_does_not_relabel_places(
    client, monkeypatch, capsys,
):
    created = await client.post("/v1/auth/dev-token", json={"nickname": "inventory-owner"})
    assert created.status_code == 200
    owner = UUID(created.json()["user_id"])
    with SessionLocal() as db:
        unnamed = Place(
            user_id=owner,
            name="未命名地点",
            cluster_key="inventory-target",
            latitude=31.2304,
            longitude=121.4737,
            is_user_named=False,
        )
        named = Place(
            user_id=owner,
            name="家",
            user_name="家",
            cluster_key="inventory-user-named",
            latitude=31.2305,
            longitude=121.4738,
            is_user_named=True,
        )
        db.add_all([unnamed, named])
        db.commit()
        unnamed_id, named_id = unnamed.id, named.id

    before = read_only_place_naming_inventory()
    assert before.eligible_places >= 1
    assert before.eligible_owners >= 1
    assert isinstance(before.key_configured, bool)

    monkeypatch.setattr(sys, "argv", ["place_naming_backfill", "--status-only"])
    main()
    output = capsys.readouterr().out
    assert "mutation=NONE" in output
    assert "eligible_places=" in output
    assert "eligible_owners=" in output
    assert "web_key_set=" in output
    assert str(owner) not in output
    assert "31.2304" not in output
    assert "121.4737" not in output

    after = read_only_place_naming_inventory()
    assert before == after
    with SessionLocal() as db:
        unchanged = db.get(Place, unnamed_id)
        manually_named = db.get(Place, named_id)
        assert unchanged is not None
        assert unchanged.name == "未命名地点"
        assert unchanged.automatic_name is None
        assert manually_named is not None
        assert manually_named.user_name == "家"
        assert manually_named.automatic_name is None
        db.rollback()


def test_inventory_failure_is_redacted_and_never_falls_into_backfill(
    monkeypatch, capsys,
):
    import app.maintenance.place_naming_backfill as module

    def unavailable():
        raise RuntimeError("SECRET AMAP_SERVER_KEY sample-url?lat=12&lon=13")

    def must_not_sweep(**kwargs):
        raise AssertionError("status-only path must never run mutation code")

    monkeypatch.setattr(module, "read_only_place_naming_inventory", unavailable)
    monkeypatch.setattr(module, "sweep_unnamed_place_names", must_not_sweep)
    monkeypatch.setattr(sys, "argv", ["place_naming_backfill", "--status-only"])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    output = capsys.readouterr().out
    assert "CONFIG_OR_DATABASE_UNAVAILABLE" in output
    assert "SECRET" not in output
    assert "sample-url" not in output
