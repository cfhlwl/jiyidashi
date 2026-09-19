from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import LocationDerivationState, LocationPoint, Place, Visit
from app.schemas import LocationBatchRequest, LocationPointCreate
from app.services.privacy_service import (
    ensure_utc,
    get_privacy_state,
    is_pause_active,
    lock_location_derivation_state,
    pause_intervals_for_range,
    timestamp_in_pause_intervals,
)

ALGORITHM_VERSION = "visit-seq-v1"
_EARTH_RADIUS_M = 6_371_008.8
_GEOHASH_ALPHABET = "0123456789bcdefghjkmnpqrstuvwxyz"


class LocationIngestError(RuntimeError):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class LocationIngestResult:
    accepted: int
    duplicates: int
    rejected_privacy: int
    rejected_finalized: int
    derived_visits: int
    raw_deleted: int
    finalized_through: datetime | None


@dataclass(frozen=True)
class _Point:
    client_uuid: str
    latitude: float
    longitude: float
    accuracy: float | None
    speed: float | None
    recorded_at: datetime


def _input_point(point: LocationPointCreate) -> _Point:
    return _Point(
        client_uuid=point.client_uuid,
        latitude=float(point.latitude),
        longitude=float(point.longitude),
        accuracy=None if point.accuracy is None else float(point.accuracy),
        speed=None if point.speed is None else float(point.speed),
        recorded_at=ensure_utc(point.recorded_at),
    )


def _stored_point(point: LocationPoint) -> _Point:
    return _Point(
        client_uuid=point.client_uuid,
        latitude=float(point.latitude),
        longitude=float(point.longitude),
        accuracy=None if point.accuracy is None else float(point.accuracy),
        speed=None if point.speed is None else float(point.speed),
        recorded_at=ensure_utc(point.recorded_at),
    )


def _signature(point: _Point) -> tuple[object, ...]:
    return (
        point.latitude,
        point.longitude,
        point.accuracy,
        point.speed,
        point.recorded_at,
    )


def _distance_m(point: _Point, latitude: float, longitude: float) -> float:
    lat1 = math.radians(point.latitude)
    lat2 = math.radians(latitude)
    d_lat = lat2 - lat1
    d_lon = math.radians(longitude - point.longitude)
    hav = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(hav)))


def _clusters(
    points: list[LocationPoint],
    *,
    radius_m: float,
    max_gap_seconds: int,
) -> list[list[_Point]]:
    ordered = sorted(
        (_stored_point(point) for point in points),
        key=lambda point: (point.recorded_at, point.client_uuid),
    )
    if not ordered:
        return []

    clusters: list[list[_Point]] = []
    current = [ordered[0]]
    sum_lat = ordered[0].latitude
    sum_lon = ordered[0].longitude

    for point in ordered[1:]:
        last = current[-1]
        gap = (point.recorded_at - last.recorded_at).total_seconds()
        centroid_lat = sum_lat / len(current)
        centroid_lon = sum_lon / len(current)
        if (
            0 <= gap <= max_gap_seconds
            and _distance_m(point, centroid_lat, centroid_lon) <= radius_m
        ):
            current.append(point)
            sum_lat += point.latitude
            sum_lon += point.longitude
            continue
        clusters.append(current)
        current = [point]
        sum_lat = point.latitude
        sum_lon = point.longitude

    clusters.append(current)
    return clusters


def _fingerprint(points: list[_Point]) -> str:
    payload = "\n".join(
        "|".join(
            (
                point.client_uuid,
                point.recorded_at.isoformat(timespec="microseconds"),
                f"{point.latitude:.8f}",
                f"{point.longitude:.8f}",
                "" if point.accuracy is None else f"{point.accuracy:.3f}",
                "" if point.speed is None else f"{point.speed:.3f}",
            )
        )
        for point in points
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _visit_key(fingerprint: str) -> str:
    return hashlib.sha256(f"{ALGORITHM_VERSION}:{fingerprint}".encode()).hexdigest()


def _geohash(latitude: float, longitude: float, precision: int) -> str:
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    result: list[str] = []
    bit = 0
    char_value = 0
    even = True
    while len(result) < precision:
        interval = lon_interval if even else lat_interval
        value = longitude if even else latitude
        midpoint = (interval[0] + interval[1]) / 2
        if value >= midpoint:
            char_value |= 1 << (4 - bit)
            interval[0] = midpoint
        else:
            interval[1] = midpoint
        even = not even
        if bit < 4:
            bit += 1
        else:
            result.append(_GEOHASH_ALPHABET[char_value])
            bit = 0
            char_value = 0
    return "".join(result)


def _place(
    db: Session,
    *,
    user_id: UUID,
    cluster_key: str,
    latitude: float,
    longitude: float,
) -> Place:
    place = db.scalar(
        select(Place).where(
            Place.user_id == user_id,
            Place.cluster_key == cluster_key,
        )
    )
    if place is not None:
        return place
    # [人工注释][S2-008] O 线不做 POI/AI 命名；空间桶只生成中性的未命名 Place。
    place = Place(
        user_id=user_id,
        name="未命名地点",
        cluster_key=cluster_key,
        latitude=latitude,
        longitude=longitude,
        is_user_named=False,
    )
    db.add(place)
    db.flush()
    return place


def _refresh_place_stats(db: Session, user_id: UUID) -> None:
    db.flush()
    stats = {
        row.place_id: row
        for row in db.execute(
            select(
                Visit.place_id.label("place_id"),
                func.min(Visit.arrived_at).label("first_visited_at"),
                func.max(func.coalesce(Visit.left_at, Visit.arrived_at)).label(
                    "last_visited_at"
                ),
                func.count(Visit.id).label("visit_count"),
                func.avg(Visit.centroid_latitude).label("latitude"),
                func.avg(Visit.centroid_longitude).label("longitude"),
            )
            .where(Visit.user_id == user_id)
            .group_by(Visit.place_id)
        )
    }
    for place in db.scalars(select(Place).where(Place.user_id == user_id)):
        row = stats.get(place.id)
        if row is None:
            place.first_visited_at = None
            place.last_visited_at = None
            place.visit_count = 0
            continue
        place.first_visited_at = row.first_visited_at
        place.last_visited_at = row.last_visited_at
        place.visit_count = int(row.visit_count)
        if not place.is_user_named and row.latitude is not None and row.longitude is not None:
            place.latitude = float(row.latitude)
            place.longitude = float(row.longitude)


def _rebuild(
    db: Session,
    *,
    user_id: UUID,
    state: LocationDerivationState,
    settings: Settings,
    now: datetime,
) -> tuple[int, int, datetime]:
    previous = ensure_utc(state.finalized_through) if state.finalized_through else None
    statement = select(LocationPoint).where(LocationPoint.user_id == user_id)
    if previous is not None:
        statement = statement.where(LocationPoint.recorded_at > previous)
    points = list(
        db.scalars(statement.order_by(LocationPoint.recorded_at, LocationPoint.client_uuid))
    )
    clusters = _clusters(
        points,
        radius_m=settings.location_visit_radius_m,
        max_gap_seconds=settings.location_visit_max_gap_seconds,
    )

    # [人工注释][S2-007][S2-014] durable 水位比 late-arrival 再留一个最大 cluster gap；
    # 若候选水位切进现有 cluster，则退到 cluster 起点前，下一轮仍能看到完整可变 Visit。
    candidate = now - timedelta(
        seconds=(
            settings.location_late_arrival_grace_seconds
            + settings.location_visit_max_gap_seconds
        )
    )
    if previous is not None and candidate < previous:
        candidate = previous
    safe_through = candidate
    for cluster in clusters:
        started = cluster[0].recorded_at
        ended = cluster[-1].recorded_at
        if started <= candidate < ended:
            safe_through = min(safe_through, started - timedelta(microseconds=1))
    if previous is not None and safe_through < previous:
        safe_through = previous

    mutable = {
        visit.derivation_key: visit
        for visit in db.scalars(
            select(Visit).where(
                Visit.user_id == user_id,
                Visit.derivation_key.is_not(None),
                Visit.finalized_at.is_(None),
            )
        )
        if visit.derivation_key is not None
    }
    desired: set[str] = set()
    desired_count = 0
    for cluster in clusters:
        started = cluster[0].recorded_at
        ended = cluster[-1].recorded_at
        duration = int((ended - started).total_seconds())
        if (
            len(cluster) < settings.location_visit_min_points
            or duration < settings.location_visit_min_duration_seconds
        ):
            continue
        fingerprint = _fingerprint(cluster)
        key = _visit_key(fingerprint)
        desired.add(key)
        desired_count += 1
        latitude = sum(point.latitude for point in cluster) / len(cluster)
        longitude = sum(point.longitude for point in cluster) / len(cluster)
        place = _place(
            db,
            user_id=user_id,
            cluster_key=_geohash(
                latitude,
                longitude,
                settings.location_place_geohash_precision,
            ),
            latitude=latitude,
            longitude=longitude,
        )
        visit = mutable.get(key)
        if visit is None:
            visit = Visit(user_id=user_id, place_id=place.id, derivation_key=key)
            db.add(visit)
        visit.place_id = place.id
        visit.arrived_at = started
        visit.left_at = ended
        visit.duration_seconds = duration
        visit.confidence = 0.85
        visit.source = "LOCATION_CLUSTER"
        visit.centroid_latitude = latitude
        visit.centroid_longitude = longitude
        visit.source_point_count = len(cluster)
        visit.source_started_at = started
        visit.source_ended_at = ended
        visit.source_fingerprint = fingerprint
        visit.algorithm_version = ALGORITHM_VERSION
        visit.finalized_at = now if ended <= safe_through else None

    for key, visit in mutable.items():
        if key not in desired:
            db.delete(visit)

    state.finalized_through = safe_through
    _refresh_place_stats(db, user_id)
    retention_cutoff = now - timedelta(days=settings.location_raw_retention_days)
    result = db.execute(
        delete(LocationPoint).where(
            LocationPoint.user_id == user_id,
            LocationPoint.recorded_at <= safe_through,
            LocationPoint.recorded_at < retention_cutoff,
        )
    )
    rowcount = getattr(result, "rowcount", 0)
    raw_deleted = rowcount if isinstance(rowcount, int) and rowcount > 0 else 0
    return desired_count, raw_deleted, safe_through


def ingest_location_batch(
    db: Session,
    *,
    user_id: UUID,
    payload: LocationBatchRequest,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> LocationIngestResult:
    settings = settings or get_settings()
    now = ensure_utc(now or datetime.now(UTC))
    state = lock_location_derivation_state(db, user_id)
    privacy = get_privacy_state(db, user_id)
    if is_pause_active(privacy.recording_paused_until):
        raise LocationIngestError("RECORDING_PAUSED", 409)

    normalized: dict[str, _Point] = {}
    duplicates = 0
    for raw in payload.points:
        point = _input_point(raw)
        prior = normalized.get(point.client_uuid)
        if prior is None:
            normalized[point.client_uuid] = point
        elif _signature(prior) != _signature(point):
            raise LocationIngestError("LOCATION_CLIENT_UUID_CONFLICT", 409)
        else:
            duplicates += 1

    existing = {
        row.client_uuid: row
        for row in db.scalars(
            select(LocationPoint).where(
                LocationPoint.user_id == user_id,
                LocationPoint.client_uuid.in_(normalized),
            )
        )
    }
    cutoff = now - timedelta(seconds=settings.location_late_arrival_grace_seconds)
    if state.finalized_through is not None:
        cutoff = max(cutoff, ensure_utc(state.finalized_through))

    candidates: list[_Point] = []
    rejected_finalized = 0
    for client_uuid, point in normalized.items():
        stored = existing.get(client_uuid)
        if stored is not None:
            if _signature(_stored_point(stored)) != _signature(point):
                raise LocationIngestError("LOCATION_CLIENT_UUID_CONFLICT", 409)
            duplicates += 1
            continue
        if point.recorded_at <= cutoff:
            rejected_finalized += 1
            continue
        candidates.append(point)

    intervals: list[tuple[datetime, datetime | None]] = []
    if candidates:
        intervals = pause_intervals_for_range(
            db,
            user_id,
            start=min(point.recorded_at for point in candidates),
            end=max(point.recorded_at for point in candidates),
        )

    rows: list[LocationPoint] = []
    rejected_privacy = 0
    for point in candidates:
        if timestamp_in_pause_intervals(point.recorded_at, intervals):
            rejected_privacy += 1
            continue
        rows.append(
            LocationPoint(
                user_id=user_id,
                client_uuid=point.client_uuid,
                latitude=point.latitude,
                longitude=point.longitude,
                accuracy=point.accuracy,
                speed=point.speed,
                recorded_at=point.recorded_at,
            )
        )
    if rows:
        db.add_all(rows)
        db.flush()

    derived_visits, raw_deleted, finalized_through = _rebuild(
        db,
        user_id=user_id,
        state=state,
        settings=settings,
        now=now,
    )
    db.commit()
    return LocationIngestResult(
        accepted=len(rows),
        duplicates=duplicates,
        rejected_privacy=rejected_privacy,
        rejected_finalized=rejected_finalized,
        derived_visits=derived_visits,
        raw_deleted=raw_deleted,
        finalized_through=ensure_utc(finalized_through),
    )
