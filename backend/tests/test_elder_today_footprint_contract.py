from __future__ import annotations

from app.main import app


def test_elder_today_footprint_adds_no_backend_authority() -> None:
    paths = set(app.openapi()["paths"])
    assert "/v1/today/footprint" in paths
    assert not any(path.startswith("/v1/elder") for path in paths)
    assert "/v1/family/members/{resource_owner_user_id}/today/footprint" not in paths
    assert "get" in app.openapi()["paths"]["/v1/today/footprint"]
