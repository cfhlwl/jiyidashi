from __future__ import annotations

from app.main import app


def test_elder_find_things_adds_no_backend_authority() -> None:
    paths = set(app.openapi()["paths"])

    assert "/v1/memory/query" in paths
    assert not any(path.startswith("/v1/elder") for path in paths)
    query_methods = app.openapi()["paths"]["/v1/memory/query"]
    assert "post" in query_methods


def test_elder_find_things_does_not_add_parallel_find_or_query_endpoint() -> None:
    paths = set(app.openapi()["paths"])
    forbidden = {
        "/v1/elder/find-object",
        "/v1/elder/query",
        "/v1/elder/find-things",
    }
    assert paths.isdisjoint(forbidden)
