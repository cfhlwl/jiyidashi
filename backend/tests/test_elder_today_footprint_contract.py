from __future__ import annotations

from app.main import app


def test_elder_today_footprint_adds_no_backend_authority() -> None:
    paths = set(app.openapi()["paths"])
    assert "/v1/today/footprint" in paths
    assert not any(path.startswith("/v1/elder") for path in paths)
    # Family Today Footprint is a pre-existing, separately authorized surface.
    # S4-014 must not add a new Elder bypass or parallel self endpoint.
    assert "get" in app.openapi()["paths"]["/v1/today/footprint"]
