from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core import db as db_module
from app.core.config import Settings


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("db_pool_size", 0),
        ("db_max_overflow", -1),
        ("db_pool_timeout_seconds", 0),
        ("db_pool_recycle_seconds", 29),
    ],
)
def test_database_pool_settings_reject_unsafe_values(field: str, value: int):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_sqlite_application_engine_does_not_receive_postgres_pool_arguments(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    def fake_create_engine(database_url: str, **kwargs):
        captured["database_url"] = database_url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db_module, "create_engine", fake_create_engine)

    db_module.create_application_engine(
        "sqlite:///./runtime-guardrail.db",
        pool_size=3,
        max_overflow=1,
        pool_timeout_seconds=5,
        pool_recycle_seconds=300,
    )

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["connect_args"] == {"check_same_thread": False}
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "pool_timeout" not in kwargs
    assert "pool_recycle" not in kwargs


def test_postgres_application_engine_receives_canonical_pool_arguments(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    def fake_create_engine(database_url: str, **kwargs):
        captured["database_url"] = database_url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db_module, "create_engine", fake_create_engine)

    database_url = "postgresql+psycopg://user:password@postgres:5432/jiyi"
    db_module.create_application_engine(
        database_url,
        pool_size=3,
        max_overflow=1,
        pool_timeout_seconds=5,
        pool_recycle_seconds=300,
    )

    assert captured["database_url"] == database_url
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 1
    assert kwargs["pool_timeout"] == 5
    assert kwargs["pool_recycle"] == 300
    assert kwargs["pool_pre_ping"] is True
