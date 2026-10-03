from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock
from time import monotonic
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class PlaceLabelCandidate:
    label: str
    source: str
    address: str | None = None
    category: str | None = None


class PlaceResolverError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class _CachedFailure:
    code: str


class PlaceResolver(Protocol):
    def resolve(self, *, latitude: float, longitude: float) -> PlaceLabelCandidate | None: ...


class DisabledPlaceResolver:
    def resolve(self, *, latitude: float, longitude: float) -> PlaceLabelCandidate | None:
        del latitude, longitude
        return None


def _text(value: object) -> str | None:
    # AMap can return [] for absent scalar fields. Normalize that vendor quirk here so
    # the naming service only sees ordinary candidate strings.
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _nearest_named(items: object) -> dict | None:
    if not isinstance(items, list):
        return None
    candidates: list[tuple[float, dict]] = []
    for item in items:
        if not isinstance(item, dict) or _text(item.get("name")) is None:
            continue
        raw_distance = item.get("distance")
        try:
            distance = float(raw_distance)
        except (TypeError, ValueError):
            distance = float("inf")
        candidates.append((distance, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


class AMapPlaceResolver:
    """Server-side AMap Web Service reverse geocoder with a bounded in-memory cache."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self._settings = settings
        self._transport = transport
        self._cache: OrderedDict[
            tuple[float, float],
            tuple[float, PlaceLabelCandidate | _CachedFailure | None],
        ] = OrderedDict()
        self._cache_lock = Lock()

    def _cache_key(self, latitude: float, longitude: float) -> tuple[float, float]:
        # AMap accepts at most six decimal places. Reuse the exact provider request
        # precision so equivalent Place centroids share the same result.
        return (round(latitude, 6), round(longitude, 6))

    def _cached(
        self,
        key: tuple[float, float],
    ) -> PlaceLabelCandidate | _CachedFailure | None | object:
        now = monotonic()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return _CACHE_MISS
            expires_at, value = entry
            if expires_at <= now:
                self._cache.pop(key, None)
                return _CACHE_MISS
            self._cache.move_to_end(key)
            return value

    def _store(
        self,
        key: tuple[float, float],
        value: PlaceLabelCandidate | _CachedFailure | None,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        with self._cache_lock:
            self._cache[key] = (
                monotonic()
                + (
                    self._settings.place_naming_cache_ttl_seconds
                    if ttl_seconds is None
                    else ttl_seconds
                ),
                value,
            )
            self._cache.move_to_end(key)
            while len(self._cache) > self._settings.place_naming_cache_max_entries:
                self._cache.popitem(last=False)

    def resolve(self, *, latitude: float, longitude: float) -> PlaceLabelCandidate | None:
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise PlaceResolverError("PLACE_RESOLVER_INVALID_COORDINATE")
        key = self._cache_key(latitude, longitude)
        cached = self._cached(key)
        if isinstance(cached, _CachedFailure):
            raise PlaceResolverError(cached.code)
        if cached is not _CACHE_MISS:
            return cached  # type: ignore[return-value]

        def fail(code: str, cause: Exception | None = None) -> None:
            self._store(
                key,
                _CachedFailure(code),
                ttl_seconds=self._settings.place_naming_failure_backoff_seconds,
            )
            if cause is None:
                raise PlaceResolverError(code)
            raise PlaceResolverError(code) from cause

        base_url = self._settings.amap_web_service_base_url.rstrip("/")
        try:
            with httpx.Client(
                timeout=self._settings.amap_timeout_seconds,
                transport=self._transport,
            ) as client:
                # Native iOS/Android producers provide GPS/WGS-84-style coordinates.
                # AMap Web Service uses GCJ-02, so conversion is centralized here rather
                # than duplicated in the platform clients.
                convert_response = client.get(
                    f"{base_url}/assistant/coordinate/convert",
                    params={
                        "key": self._settings.amap_web_service_key,
                        "locations": f"{longitude:.6f},{latitude:.6f}",
                        "coordsys": "gps",
                        "output": "JSON",
                    },
                )
                if convert_response.status_code < 200 or convert_response.status_code >= 300:
                    fail("AMAP_COORDINATE_CONVERT_FAILED")
                try:
                    convert_payload = convert_response.json()
                except ValueError as exc:
                    fail("AMAP_COORDINATE_CONVERT_INVALID_RESPONSE", exc)
                if (
                    not isinstance(convert_payload, dict)
                    or str(convert_payload.get("status")) != "1"
                ):
                    fail("AMAP_COORDINATE_CONVERT_FAILED")
                converted = _text(convert_payload.get("locations"))
                if converted is None:
                    fail("AMAP_COORDINATE_CONVERT_INVALID_RESPONSE")
                first_location = converted.split(";")[0]
                parts = [part.strip() for part in first_location.split(",")]
                if len(parts) != 2:
                    fail("AMAP_COORDINATE_CONVERT_INVALID_RESPONSE")
                try:
                    amap_longitude = float(parts[0])
                    amap_latitude = float(parts[1])
                except ValueError as exc:
                    fail("AMAP_COORDINATE_CONVERT_INVALID_RESPONSE", exc)
                if not (
                    -180 <= amap_longitude <= 180
                    and -90 <= amap_latitude <= 90
                ):
                    fail("AMAP_COORDINATE_CONVERT_INVALID_RESPONSE")

                response = client.get(
                    f"{base_url}/geocode/regeo",
                    params={
                        "key": self._settings.amap_web_service_key,
                        "location": f"{amap_longitude:.6f},{amap_latitude:.6f}",
                        "extensions": "all",
                        "radius": "1000",
                        "output": "JSON",
                    },
                )
        except httpx.TimeoutException as exc:
            fail("AMAP_TIMEOUT", exc)
        except httpx.RequestError as exc:
            fail("AMAP_UNAVAILABLE", exc)

        if response.status_code < 200 or response.status_code >= 300:
            fail("AMAP_FAILED")
        try:
            payload = response.json()
        except ValueError as exc:
            fail("AMAP_INVALID_RESPONSE", exc)
        if not isinstance(payload, dict) or str(payload.get("status")) != "1":
            fail("AMAP_FAILED")
        regeocode = payload.get("regeocode")
        if not isinstance(regeocode, dict):
            fail("AMAP_INVALID_RESPONSE")

        address = _text(regeocode.get("formatted_address"))
        poi = _nearest_named(regeocode.get("pois"))
        aoi = _nearest_named(regeocode.get("aois"))

        candidate: PlaceLabelCandidate | None
        if poi is not None:
            candidate = PlaceLabelCandidate(
                label=_text(poi.get("name")) or "",
                source="AMAP_POI",
                address=address,
                category=_text(poi.get("type")),
            )
        elif aoi is not None:
            candidate = PlaceLabelCandidate(
                label=_text(aoi.get("name")) or "",
                source="AMAP_AOI",
                address=address,
            )
        elif address is not None:
            candidate = PlaceLabelCandidate(
                label=address,
                source="AMAP_ADDRESS",
                address=address,
            )
        else:
            candidate = None

        self._store(key, candidate)
        return candidate


_CACHE_MISS = object()


@lru_cache
def get_place_resolver() -> PlaceResolver:
    settings = get_settings()
    if settings.place_resolver_provider == "disabled":
        return DisabledPlaceResolver()
    if settings.place_resolver_provider == "amap":
        return AMapPlaceResolver(settings)
    raise PlaceResolverError("PLACE_RESOLVER_UNAVAILABLE")
