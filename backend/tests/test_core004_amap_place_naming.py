from __future__ import annotations

from uuid import UUID

import httpx
import pytest

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import Place
from app.services.place_naming_service import backfill_automatic_place_names_for_user
from app.services.place_resolver import (
    AMapPlaceResolver,
    PlaceLabelCandidate,
    PlaceResolverError,
)


class _DeterministicResolver:
    def __init__(self, candidate: PlaceLabelCandidate | None):
        self.candidate = candidate
        self.calls: list[tuple[float, float]] = []

    def resolve(self, *, latitude: float, longitude: float) -> PlaceLabelCandidate | None:
        self.calls.append((latitude, longitude))
        return self.candidate


async def _new_user(client, nickname: str) -> UUID:
    response = await client.post("/v1/auth/dev-token", json={"nickname": nickname})
    assert response.status_code == 200
    return UUID(response.json()["user_id"])


def _amap_settings(**overrides) -> Settings:
    return Settings(
        place_resolver_provider="amap",
        amap_web_service_key="server-only-test-key",
        **overrides,
    )


def test_amap_resolver_prefers_nearest_poi_and_caches_without_exposing_mobile_sdk():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.params["key"] == "server-only-test-key"
        if request.url.path == "/v3/assistant/coordinate/convert":
            assert request.url.params["locations"] == "121.473700,31.230400"
            assert request.url.params["coordsys"] == "gps"
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "info": "OK",
                    "locations": "121.478223,31.228457",
                },
            )

        assert request.url.path == "/v3/geocode/regeo"
        assert request.url.params["location"] == "121.478223,31.228457"
        assert request.url.params["extensions"] == "all"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "info": "OK",
                "regeocode": {
                    "formatted_address": "上海市黄浦区测试路1号",
                    "pois": [
                        {"name": "较远咖啡店", "distance": "88", "type": "餐饮服务;咖啡厅"},
                        {"name": "人民广场", "distance": "12", "type": "风景名胜;广场"},
                    ],
                    "aois": [{"name": "人民广场区域", "distance": "4"}],
                },
            },
        )

    resolver = AMapPlaceResolver(
        _amap_settings(place_naming_cache_ttl_seconds=3600),
        transport=httpx.MockTransport(handler),
    )
    first = resolver.resolve(latitude=31.2304, longitude=121.4737)
    second = resolver.resolve(latitude=31.2304, longitude=121.4737)

    assert first == second
    assert first is not None
    assert first.label == "人民广场"
    assert first.source == "AMAP_POI"
    assert first.address == "上海市黄浦区测试路1号"
    assert first.category == "风景名胜;广场"
    assert calls == 2


@pytest.mark.parametrize(
    ("payload", "expected_label", "expected_source"),
    [
        (
            {
                "status": "1",
                "regeocode": {
                    "formatted_address": "北京市朝阳区测试地址",
                    "pois": [],
                    "aois": [{"name": "测试园区", "distance": "3"}],
                },
            },
            "测试园区",
            "AMAP_AOI",
        ),
        (
            {
                "status": "1",
                "regeocode": {
                    "formatted_address": "北京市朝阳区测试地址",
                    "pois": [],
                    "aois": [],
                },
            },
            "北京市朝阳区测试地址",
            "AMAP_ADDRESS",
        ),
    ],
)
def test_amap_resolver_aoi_then_address_fallback(payload, expected_label, expected_source):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/assistant/coordinate/convert":
            return httpx.Response(
                200,
                json={
                    "status": "1",
                    "locations": "116.406243,39.901403",
                },
            )
        return httpx.Response(200, json=payload)

    resolver = AMapPlaceResolver(
        _amap_settings(),
        transport=httpx.MockTransport(handler),
    )

    candidate = resolver.resolve(latitude=39.9, longitude=116.4)

    assert candidate is not None
    assert candidate.label == expected_label
    assert candidate.source == expected_source


def test_amap_provider_failure_is_bounded_and_backed_off():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"status": "0", "info": "INVALID_USER_KEY"},
        )

    resolver = AMapPlaceResolver(
        _amap_settings(place_naming_failure_backoff_seconds=300),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        PlaceResolverError,
        match="AMAP_COORDINATE_CONVERT_FAILED",
    ):
        resolver.resolve(latitude=39.9, longitude=116.4)
    with pytest.raises(
        PlaceResolverError,
        match="AMAP_COORDINATE_CONVERT_FAILED",
    ):
        resolver.resolve(latitude=39.9, longitude=116.4)

    assert calls == 1


@pytest.mark.asyncio
async def test_backfill_is_owner_scoped_bounded_and_never_overwrites_user_name(client):
    user_a = await _new_user(client, "core004-amap-a")
    user_b = await _new_user(client, "core004-amap-b")

    with SessionLocal() as db:
        automatic_target = Place(
            user_id=user_a,
            name="未命名地点",
            cluster_key="target-a",
            latitude=31.2304,
            longitude=121.4737,
            is_user_named=False,
        )
        manually_named = Place(
            user_id=user_a,
            name="家",
            user_name="家",
            cluster_key="manual-a",
            latitude=31.2200,
            longitude=121.4800,
            is_user_named=True,
        )
        foreign = Place(
            user_id=user_b,
            name="未命名地点",
            cluster_key="foreign-b",
            latitude=39.9042,
            longitude=116.4074,
            is_user_named=False,
        )
        db.add_all([automatic_target, manually_named, foreign])
        db.commit()
        automatic_target_id = automatic_target.id
        manually_named_id = manually_named.id
        foreign_id = foreign.id

    resolver = _DeterministicResolver(
        PlaceLabelCandidate(
            label="人民广场",
            source="AMAP_POI",
            address="上海市黄浦区人民广场",
            category="风景名胜",
        )
    )
    result = backfill_automatic_place_names_for_user(
        user_a,
        resolver=resolver,
        settings=Settings(place_naming_backfill_batch_size=20),
    )

    assert result.attempted == 1
    assert result.resolved == 1
    assert result.provider_failures == 0
    assert resolver.calls == [(31.2304, 121.4737)]

    with SessionLocal() as db:
        automatic_target = db.get(Place, automatic_target_id)
        manually_named = db.get(Place, manually_named_id)
        foreign = db.get(Place, foreign_id)
        assert automatic_target is not None
        assert automatic_target.name == "人民广场"
        assert automatic_target.automatic_name == "人民广场"
        assert automatic_target.automatic_name_source == "AMAP_POI"
        assert automatic_target.address == "上海市黄浦区人民广场"
        assert automatic_target.category == "风景名胜"

        assert manually_named is not None
        assert manually_named.name == "家"
        assert manually_named.user_name == "家"
        assert manually_named.automatic_name is None

        assert foreign is not None
        assert foreign.name == "未命名地点"
        assert foreign.automatic_name is None
