from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.models import (
    LocationIngestReceipt,
    Memory,
    PrivacyPauseInterval,
    Visit,
)
from app.schemas import (
    RecordingClientState,
    RecordingCoverageState,
    RecordingGapReason,
    RecordingGapState,
    RecordingGapSummary,
    RecordingHealthAggregates,
    RecordingHealthReason,
    RecordingHealthResponse,
    RecordingHealthSnapshot,
    RecordingHealthStatus,
    RecordingTodayCoverage,
)
from app.services import privacy_service
from app.services.time_service import (
    local_today,
    user_day_bounds_utc,
    user_timezone_name,
)

# CORE-003 V1 deterministic thresholds. These are product policy, not heuristics generated
# by the UI or an LLM. A green state requires fresh capture + fresh server ACK + a running
# eligible producer + drained bounded queues.
CLIENT_STATE_MAX_AGE = timedelta(minutes=5)
FUTURE_CLOCK_SKEW = timedelta(minutes=2)
RECENT_FIX_MAX_AGE = timedelta(minutes=45)
RECENT_ACK_MAX_AGE = timedelta(minutes=45)
QUEUE_OLD_MAX_AGE = timedelta(minutes=20)
QUEUE_PRESSURE_RATIO = 0.80
DELIVERY_FAILURE_DEGRADED_AT = 3

# Coverage is deliberately conservative. We only bridge adjacent retained receipt timestamps
# when they are within the reviewed cadence window. Sparse points never imply a continuous route.
SAMPLE_CONTINUITY_MAX_GAP = timedelta(minutes=20)
RECORDED_GAP_MIN_DURATION = timedelta(minutes=20)
HEALTHY_DAY_MIN_COVERED = timedelta(hours=8)
HEALTHY_DAY_MIN_OBSERVED_SPAN = timedelta(hours=12)
HEALTHY_DAY_MAX_GAP = timedelta(hours=2)
RECENT_GAP_LIMIT = 8


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class _Interval:
    start: datetime
    end: datetime
    reason: RecordingGapReason | None = None

    @property
    def seconds(self) -> int:
        return max(0, int((self.end - self.start).total_seconds()))


@dataclass(frozen=True)
class _DayCoverageInternal:
    response: RecordingTodayCoverage
    all_gap_seconds: int


def _clip_interval(
    start: datetime,
    end: datetime,
    *,
    lower: datetime,
    upper: datetime,
    reason: RecordingGapReason | None = None,
) -> _Interval | None:
    left = max(_utc(start), lower)
    right = min(_utc(end), upper)
    if right <= left:
        return None
    return _Interval(left, right, reason)


def _merge_intervals(intervals: list[_Interval]) -> list[_Interval]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: (item.start, item.end))
    merged: list[_Interval] = []
    for current in ordered:
        if not merged or current.start > merged[-1].end:
            merged.append(_Interval(current.start, current.end))
            continue
        previous = merged[-1]
        merged[-1] = _Interval(previous.start, max(previous.end, current.end))
    return merged


def _union_seconds(intervals: list[_Interval]) -> int:
    return sum(item.seconds for item in _merge_intervals(intervals))


def _server_last_activity(
    db: Session,
    *,
    user_id: UUID,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    last_fix, last_ack = db.execute(
        select(
            func.max(LocationIngestReceipt.recorded_at),
            func.max(LocationIngestReceipt.created_at),
        ).where(LocationIngestReceipt.user_id == user_id)
    ).one()
    last_visit = db.scalar(
        select(func.max(func.coalesce(Visit.left_at, Visit.arrived_at))).where(
            Visit.user_id == user_id
        )
    )
    return (
        None if last_fix is None else _utc(last_fix),
        None if last_ack is None else _utc(last_ack),
        None if last_visit is None else _utc(last_visit),
    )


def _day_bounds_for_timezone(
    timezone: str,
    day: date,
) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _privacy_intervals(
    db: Session,
    *,
    user_id: UUID,
    start_utc: datetime,
    end_utc: datetime,
    now: datetime,
    rows_override: list[tuple[datetime, datetime | None]] | None = None,
) -> list[_Interval]:
    if rows_override is None:
        rows = db.execute(
            select(PrivacyPauseInterval.started_at, PrivacyPauseInterval.ended_at)
            .where(
                PrivacyPauseInterval.user_id == user_id,
                PrivacyPauseInterval.started_at < end_utc,
                or_(
                    PrivacyPauseInterval.ended_at.is_(None),
                    PrivacyPauseInterval.ended_at > start_utc,
                ),
            )
            .order_by(PrivacyPauseInterval.started_at.asc())
        ).all()
    else:
        rows = rows_override

    intervals: list[_Interval] = []
    for started_at, ended_at in rows:
        started = _utc(started_at)
        end = now if ended_at is None else _utc(ended_at)
        clipped = _clip_interval(
            started,
            end,
            lower=start_utc,
            upper=end_utc,
            reason=RecordingGapReason.PRIVACY_PAUSED,
        )
        if clipped is not None:
            intervals.append(clipped)
    return intervals


def _visit_overlaps(start_utc: datetime, end_utc: datetime, row: tuple) -> bool:
    arrived_at, left_at, source_ended_at = row
    arrived = _utc(arrived_at)
    proven_end = left_at or source_ended_at
    if proven_end is None:
        return start_utc <= arrived < end_utc
    return arrived < end_utc and _utc(proven_end) >= start_utc


def _day_coverage(
    db: Session,
    *,
    user_id: UUID,
    day: date,
    now: datetime,
    timezone_override: str | None = None,
    receipt_times_override: list[datetime] | None = None,
    visit_rows_override: list[tuple] | None = None,
    privacy_rows_override: list[tuple[datetime, datetime | None]] | None = None,
    memory_count_override: int | None = None,
) -> _DayCoverageInternal:
    timezone = timezone_override or user_timezone_name(db, user_id)
    start_utc, end_utc = _day_bounds_for_timezone(timezone, day)
    effective_end = min(end_utc, now)

    if receipt_times_override is None:
        receipt_times = [
            _utc(value)
            for value in db.scalars(
                select(LocationIngestReceipt.recorded_at)
                .where(
                    LocationIngestReceipt.user_id == user_id,
                    LocationIngestReceipt.recorded_at >= start_utc,
                    LocationIngestReceipt.recorded_at < end_utc,
                )
                .order_by(LocationIngestReceipt.recorded_at.asc())
            )
        ]
    else:
        receipt_times = sorted(
            _utc(value)
            for value in receipt_times_override
            if start_utc <= _utc(value) < end_utc
        )

    if visit_rows_override is None:
        visit_rows = db.execute(
            select(
                Visit.arrived_at,
                Visit.left_at,
                Visit.source_ended_at,
            )
            .where(
                Visit.user_id == user_id,
                Visit.arrived_at < end_utc,
                or_(
                    Visit.left_at >= start_utc,
                    and_(
                        Visit.left_at.is_(None),
                        Visit.source_ended_at >= start_utc,
                    ),
                    and_(
                        Visit.left_at.is_(None),
                        Visit.source_ended_at.is_(None),
                        Visit.arrived_at >= start_utc,
                    ),
                ),
            )
            .order_by(Visit.arrived_at.asc())
        ).all()
    else:
        visit_rows = [
            row
            for row in visit_rows_override
            if _visit_overlaps(start_utc, end_utc, row)
        ]

    evidence_intervals: list[_Interval] = []
    observed_instants: list[datetime] = list(receipt_times)
    visit_count = 0
    for arrived_at, left_at, source_ended_at in visit_rows:
        visit_count += 1
        arrived = _utc(arrived_at)
        observed_instants.append(arrived)
        # Open/mutable visits do not prove continued presence up to "now". Only a real
        # left/source_ended boundary is eligible for covered-duration accounting.
        proven_end = left_at or source_ended_at
        if proven_end is not None:
            ended = _utc(proven_end)
            observed_instants.append(ended)
            clipped = _clip_interval(
                arrived,
                ended,
                lower=start_utc,
                upper=effective_end,
            )
            if clipped is not None:
                evidence_intervals.append(clipped)

    for previous, current in zip(receipt_times, receipt_times[1:]):
        if current <= previous:
            continue
        if current - previous <= SAMPLE_CONTINUITY_MAX_GAP:
            clipped = _clip_interval(
                previous,
                current,
                lower=start_utc,
                upper=effective_end,
            )
            if clipped is not None:
                evidence_intervals.append(clipped)

    merged_evidence = _merge_intervals(evidence_intervals)
    covered_seconds = sum(item.seconds for item in merged_evidence)

    privacy_gaps = _privacy_intervals(
        db,
        user_id=user_id,
        start_utc=start_utc,
        end_utc=effective_end,
        now=now,
        rows_override=privacy_rows_override,
    )

    # A long interval between two real observations is evidence of missing coverage, but
    # its cause stays UNKNOWN unless another authority proves it. Subtract intervals already
    # proven by Visit/sample continuity and explicit Privacy Pause so a deliberate pause is
    # never relabelled as an accidental failure.
    def subtract_masks(candidate: _Interval, masks: list[_Interval]) -> list[_Interval]:
        segments = [candidate]
        for mask in _merge_intervals(masks):
            next_segments: list[_Interval] = []
            for segment in segments:
                if mask.end <= segment.start or mask.start >= segment.end:
                    next_segments.append(segment)
                    continue
                if mask.start > segment.start:
                    next_segments.append(
                        _Interval(
                            segment.start,
                            min(mask.start, segment.end),
                            segment.reason,
                        )
                    )
                if mask.end < segment.end:
                    next_segments.append(
                        _Interval(
                            max(mask.end, segment.start),
                            segment.end,
                            segment.reason,
                        )
                    )
            segments = next_segments
            if not segments:
                break
        return [segment for segment in segments if segment.seconds > 0]

    unknown_gaps: list[_Interval] = []
    ordered_observations = sorted(set(observed_instants))
    for previous, current in zip(ordered_observations, ordered_observations[1:]):
        if current - previous < RECORDED_GAP_MIN_DURATION:
            continue
        candidate = _clip_interval(
            previous,
            current,
            lower=start_utc,
            upper=effective_end,
            reason=RecordingGapReason.UNKNOWN,
        )
        if candidate is None:
            continue
        for uncovered in subtract_masks(
            candidate,
            [*merged_evidence, *privacy_gaps],
        ):
            if uncovered.seconds >= int(RECORDED_GAP_MIN_DURATION.total_seconds()):
                unknown_gaps.append(uncovered)

    all_gaps = sorted(
        [*privacy_gaps, *unknown_gaps],
        key=lambda item: (item.start, item.end),
    )
    known_gap_seconds = _union_seconds(privacy_gaps)
    all_gap_seconds = _union_seconds(all_gaps)
    largest_known_gap_seconds = max(
        (item.seconds for item in privacy_gaps),
        default=0,
    )

    if memory_count_override is None:
        memory_count = db.scalar(
            select(func.count(Memory.id)).where(
                Memory.user_id == user_id,
                Memory.occurred_at >= start_utc,
                Memory.occurred_at < end_utc,
            )
        )
        memory_count_value = int(memory_count or 0)
    else:
        memory_count_value = memory_count_override

    observed_instants = [
        value for value in observed_instants if start_utc <= value <= effective_end
    ]
    # A finalized Visit crossing a local-day boundary is itself retained evidence for the
    # clipped day interval. Include those proven boundaries without exposing coordinates.
    for interval in merged_evidence:
        observed_instants.extend((interval.start, interval.end))
    first_observed = min(observed_instants, default=None)
    last_observed = max(observed_instants, default=None)

    day_elapsed = max(timedelta(0), effective_end - start_utc)
    observed_span = (
        timedelta(0)
        if first_observed is None or last_observed is None
        else last_observed - first_observed
    )
    largest_policy_gap = max((item.seconds for item in all_gaps), default=0)
    healthy_threshold = min(HEALTHY_DAY_MIN_COVERED, day_elapsed)
    healthy = (
        bool(observed_instants)
        and day_elapsed >= timedelta(hours=12)
        and covered_seconds >= int(healthy_threshold.total_seconds())
        and observed_span >= HEALTHY_DAY_MIN_OBSERVED_SPAN
        and largest_policy_gap <= int(HEALTHY_DAY_MAX_GAP.total_seconds())
        and not privacy_gaps
    )

    if not observed_instants:
        coverage_state = RecordingCoverageState.UNKNOWN
    elif all_gaps:
        coverage_state = RecordingCoverageState.GAPPED
    elif healthy:
        coverage_state = RecordingCoverageState.HEALTHY
    else:
        coverage_state = RecordingCoverageState.PARTIAL

    recent_gaps = [
        RecordingGapSummary(
            reason=item.reason or RecordingGapReason.UNKNOWN,
            started_at=item.start,
            ended_at=item.end,
            duration_seconds=item.seconds,
        )
        for item in all_gaps[-RECENT_GAP_LIMIT:]
    ]

    return _DayCoverageInternal(
        response=RecordingTodayCoverage(
            local_day=day,
            timezone=timezone,
            first_observed_at=first_observed,
            last_observed_at=last_observed,
            trusted_location_sample_count=len(receipt_times),
            visit_count=visit_count,
            memory_count=memory_count_value,
            covered_duration_seconds=covered_seconds,
            known_gap_duration_seconds=known_gap_seconds,
            largest_known_gap_seconds=largest_known_gap_seconds,
            coverage_state=coverage_state,
            has_capacity_pressure=False,
            has_recorded_gap=bool(all_gaps),
            recent_gaps=recent_gaps,
        ),
        all_gap_seconds=all_gap_seconds,
    )


def _historical_aggregates(
    db: Session,
    *,
    user_id: UUID,
    today: date,
    now: datetime,
    current_capacity_pressure: bool | None,
    current_permission_block: bool | None,
) -> RecordingHealthAggregates:
    # One bounded 30-day evidence window avoids per-day SQL amplification.
    timezone = user_timezone_name(db, user_id)
    history_start, _ = _day_bounds_for_timezone(
        timezone,
        today - timedelta(days=30),
    )
    history_end, _ = _day_bounds_for_timezone(timezone, today)

    receipt_times = [
        _utc(value)
        for value in db.scalars(
            select(LocationIngestReceipt.recorded_at)
            .where(
                LocationIngestReceipt.user_id == user_id,
                LocationIngestReceipt.recorded_at >= history_start,
                LocationIngestReceipt.recorded_at < history_end,
            )
            .order_by(LocationIngestReceipt.recorded_at.asc())
        )
    ]
    visit_rows = [
        (
            _utc(arrived),
            None if left is None else _utc(left),
            None if source_end is None else _utc(source_end),
        )
        for arrived, left, source_end in db.execute(
            select(Visit.arrived_at, Visit.left_at, Visit.source_ended_at)
            .where(
                Visit.user_id == user_id,
                Visit.arrived_at < history_end,
                or_(
                    Visit.left_at >= history_start,
                    and_(
                        Visit.left_at.is_(None),
                        Visit.source_ended_at >= history_start,
                    ),
                    and_(
                        Visit.left_at.is_(None),
                        Visit.source_ended_at.is_(None),
                        Visit.arrived_at >= history_start,
                    ),
                ),
            )
            .order_by(Visit.arrived_at.asc())
        ).all()
    ]
    privacy_rows = [
        (_utc(started), None if ended is None else _utc(ended))
        for started, ended in db.execute(
            select(PrivacyPauseInterval.started_at, PrivacyPauseInterval.ended_at)
            .where(
                PrivacyPauseInterval.user_id == user_id,
                PrivacyPauseInterval.started_at < history_end,
                or_(
                    PrivacyPauseInterval.ended_at.is_(None),
                    PrivacyPauseInterval.ended_at > history_start,
                ),
            )
            .order_by(PrivacyPauseInterval.started_at.asc())
        ).all()
    ]
    memory_times = [
        _utc(value)
        for value in db.scalars(
            select(Memory.occurred_at).where(
                Memory.user_id == user_id,
                Memory.occurred_at >= history_start,
                Memory.occurred_at < history_end,
            )
        )
    ]

    days: list[_DayCoverageInternal] = []
    for offset in range(1, 31):
        day = today - timedelta(days=offset)
        start_utc, end_utc = _day_bounds_for_timezone(timezone, day)
        day_receipts = [
            value for value in receipt_times if start_utc <= value < end_utc
        ]
        day_visits = [
            row for row in visit_rows if _visit_overlaps(start_utc, end_utc, row)
        ]
        day_privacy = [
            row
            for row in privacy_rows
            if row[0] < end_utc and (row[1] is None or row[1] > start_utc)
        ]
        day_memory_count = sum(
            1 for value in memory_times if start_utc <= value < end_utc
        )
        days.append(
            _day_coverage(
                db,
                user_id=user_id,
                day=day,
                now=now,
                timezone_override=timezone,
                receipt_times_override=day_receipts,
                visit_rows_override=day_visits,
                privacy_rows_override=day_privacy,
                memory_count_override=day_memory_count,
            )
        )

    def healthy_count(window: int) -> int:
        return sum(
            1
            for item in days[:window]
            if item.response.coverage_state == RecordingCoverageState.HEALTHY
        )

    def gap_hours(window: int) -> float:
        seconds = sum(item.all_gap_seconds for item in days[:window])
        return round(seconds / 3600.0, 2)

    # Capacity/permission history is not persisted in CORE-001. Exposing a made-up zero
    # would be false precision, so V1 keeps those historical counters unavailable.
    return RecordingHealthAggregates(
        healthy_days_7d=healthy_count(7),
        healthy_days_30d=healthy_count(30),
        gap_hours_7d=gap_hours(7),
        gap_hours_30d=gap_hours(30),
        days_with_capacity_pressure=None,
        days_with_permission_block=None,
        current_capacity_pressure=current_capacity_pressure,
        current_permission_block=current_permission_block,
    )


def _derive_status(
    *,
    now: datetime,
    privacy_paused: bool,
    client: RecordingClientState | None,
    server_last_fix: datetime | None,
    server_last_ack: datetime | None,
    today_coverage: RecordingTodayCoverage,
) -> tuple[RecordingHealthStatus, RecordingHealthReason, RecordingGapState]:
    if privacy_paused:
        return (
            RecordingHealthStatus.PAUSED,
            RecordingHealthReason.PRIVACY_PAUSED,
            RecordingGapState.KNOWN,
        )

    if client is None:
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NATIVE_STATE_UNAVAILABLE,
            RecordingGapState.UNKNOWN,
        )

    observed_at = _utc(client.observed_at)
    if observed_at > now + FUTURE_CLOCK_SKEW or now - observed_at > CLIENT_STATE_MAX_AGE:
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.CLIENT_STATE_STALE,
            RecordingGapState.UNKNOWN,
        )

    if client.automatic_enabled is False:
        return (
            RecordingHealthStatus.BLOCKED,
            RecordingHealthReason.AUTOMATIC_DISABLED,
            RecordingGapState.KNOWN,
        )

    if client.location_services_state == "UNKNOWN":
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NATIVE_STATE_UNAVAILABLE,
            RecordingGapState.UNKNOWN,
        )
    if client.location_services_state == "OFF":
        return (
            RecordingHealthStatus.BLOCKED,
            RecordingHealthReason.LOCATION_SERVICES_OFF,
            RecordingGapState.KNOWN,
        )

    if client.permission_state == "UNKNOWN":
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NATIVE_STATE_UNAVAILABLE,
            RecordingGapState.UNKNOWN,
        )
    if client.permission_state in {
        "DENIED",
        "RESTRICTED",
        "NOT_DETERMINED",
        "FOREGROUND",
    }:
        return (
            RecordingHealthStatus.BLOCKED,
            RecordingHealthReason.PERMISSION_BLOCKED,
            RecordingGapState.KNOWN,
        )

    if client.background_runtime_state == "UNKNOWN":
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NATIVE_STATE_UNAVAILABLE,
            RecordingGapState.UNKNOWN,
        )
    if client.background_runtime_state == "RESTRICTED":
        return (
            RecordingHealthStatus.BLOCKED,
            RecordingHealthReason.PLATFORM_RESTRICTED,
            RecordingGapState.KNOWN,
        )

    if client.native_queue_schema_version < 2:
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NATIVE_STATE_UNAVAILABLE,
            RecordingGapState.UNKNOWN,
        )

    if client.recovery_pending:
        return (
            RecordingHealthStatus.RECOVERING,
            RecordingHealthReason.RECOVERY_PENDING,
            RecordingGapState.KNOWN,
        )

    if (
        client.capacity_pressure
        or client.native_queue_corrupt
        or client.native_queue_storage_unavailable
        or client.dropped_sample_count > 0
    ):
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.QUEUE_CAPACITY_PRESSURE,
            RecordingGapState.KNOWN,
        )

    if client.native_producer_state == "UNKNOWN":
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NATIVE_STATE_UNAVAILABLE,
            RecordingGapState.UNKNOWN,
        )
    if client.native_producer_state != "RUNNING":
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.PRODUCER_NOT_RUNNING,
            RecordingGapState.KNOWN,
        )

    total_depth = client.native_queue_depth + client.sqlite_queue_depth
    capacity = client.native_queue_capacity
    if capacity > 0 and client.native_queue_depth / capacity >= QUEUE_PRESSURE_RATIO:
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.QUEUE_BACKLOG,
            RecordingGapState.KNOWN,
        )

    oldest_pending = client.native_oldest_pending_at or client.sqlite_oldest_pending_at
    if oldest_pending is not None and now - _utc(oldest_pending) > QUEUE_OLD_MAX_AGE:
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.DELIVERY_BACKLOG,
            RecordingGapState.KNOWN,
        )

    if (
        total_depth > 0
        and client.delivery_failure_count >= DELIVERY_FAILURE_DEGRADED_AT
    ):
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.DELIVERY_FAILURE,
            RecordingGapState.KNOWN,
        )

    last_fix = client.last_fix_at or server_last_fix
    if last_fix is None:
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NO_RECENT_FIX,
            RecordingGapState.UNKNOWN,
        )
    if now - _utc(last_fix) > RECENT_FIX_MAX_AGE:
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.NO_RECENT_FIX,
            RecordingGapState.KNOWN,
        )

    # ACK authority is server-owned. Client delivery state may describe attempts/backlog,
    # but it cannot mint a successful server receipt for a different/stale owner.
    last_ack = server_last_ack
    if last_ack is None:
        return (
            RecordingHealthStatus.UNKNOWN,
            RecordingHealthReason.NO_RECENT_ACK,
            RecordingGapState.UNKNOWN,
        )
    if now - _utc(last_ack) > RECENT_ACK_MAX_AGE:
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.DELIVERY_BACKLOG,
            RecordingGapState.KNOWN,
        )

    non_privacy_gap = any(
        gap.reason != RecordingGapReason.PRIVACY_PAUSED
        for gap in today_coverage.recent_gaps
    )
    if non_privacy_gap:
        return (
            RecordingHealthStatus.DEGRADED,
            RecordingHealthReason.RECORDED_GAP,
            RecordingGapState.KNOWN,
        )

    return (
        RecordingHealthStatus.HEALTHY,
        RecordingHealthReason.RECENT_CAPTURE_AND_ACK,
        RecordingGapState.NONE,
    )


def get_recording_health(
    db: Session,
    *,
    user_id: UUID,
    client_state: RecordingClientState | None = None,
    reference_utc: datetime | None = None,
) -> RecordingHealthResponse:
    now = _utc(reference_utc or datetime.now(UTC))
    today = local_today(db, user_id, reference_utc=now)
    coverage_internal = _day_coverage(
        db,
        user_id=user_id,
        day=today,
        now=now,
    )
    coverage = coverage_internal.response

    privacy = privacy_service.get_privacy_state(db, user_id)
    # Use the same request clock as local-day coverage so a request crossing local
    # midnight cannot derive privacy and coverage from two different instants.
    privacy_paused = (
        privacy.recording_paused_until is not None
        and _utc(privacy.recording_paused_until) > now
    )
    server_last_fix, server_last_ack, last_visit = _server_last_activity(
        db,
        user_id=user_id,
    )

    status, reason, gap_state = _derive_status(
        now=now,
        privacy_paused=privacy_paused,
        client=client_state,
        server_last_fix=server_last_fix,
        server_last_ack=server_last_ack,
        today_coverage=coverage,
    )

    if client_state is not None:
        coverage = coverage.model_copy(
            update={
                "has_capacity_pressure": client_state.capacity_pressure,
                "has_recorded_gap": (
                    coverage.has_recorded_gap
                    or client_state.dropped_sample_count > 0
                    or client_state.capacity_pressure
                ),
            }
        )

    last_fix = (
        client_state.last_fix_at
        if client_state is not None and client_state.last_fix_at is not None
        else server_last_fix
    )
    last_server_ack = server_last_ack

    snapshot = RecordingHealthSnapshot(
        status=status,
        status_reason=reason,
        automatic_enabled=None if client_state is None else client_state.automatic_enabled,
        privacy_paused=privacy_paused,
        permission_state=None if client_state is None else client_state.permission_state,
        location_services_state=(
            None if client_state is None else client_state.location_services_state
        ),
        background_runtime_state=(
            None if client_state is None else client_state.background_runtime_state
        ),
        battery_optimization_state=(
            None if client_state is None else client_state.battery_optimization_state
        ),
        native_producer_state=(
            None if client_state is None else client_state.native_producer_state
        ),
        native_queue_depth=0 if client_state is None else client_state.native_queue_depth,
        native_queue_capacity=(
            0 if client_state is None else client_state.native_queue_capacity
        ),
        native_oldest_pending_at=(
            None if client_state is None else client_state.native_oldest_pending_at
        ),
        sqlite_queue_depth=0 if client_state is None else client_state.sqlite_queue_depth,
        capacity_pressure=(
            False if client_state is None else client_state.capacity_pressure
        ),
        last_fix_at=None if last_fix is None else _utc(last_fix),
        last_enqueue_at=(
            None if client_state is None else client_state.last_enqueue_at
        ),
        last_handoff_at=(
            None if client_state is None else client_state.last_handoff_at
        ),
        last_upload_attempt_at=(
            None if client_state is None else client_state.last_upload_attempt_at
        ),
        last_upload_success_at=last_server_ack,
        last_server_ack_at=last_server_ack,
        last_visit_at=last_visit,
        delivery_failure_count=(
            0 if client_state is None else client_state.delivery_failure_count
        ),
        last_delivery_error_code=(
            None if client_state is None else client_state.last_delivery_error_code
        ),
        recovery_pending=(
            False if client_state is None else client_state.recovery_pending
        ),
        recording_gap_state=gap_state,
        updated_at=now,
    )

    current_permission_block = None
    if client_state is not None:
        current_permission_block = client_state.permission_state in {
            "DENIED",
            "RESTRICTED",
            "NOT_DETERMINED",
            "FOREGROUND",
        } or client_state.location_services_state == "OFF"

    aggregates = _historical_aggregates(
        db,
        user_id=user_id,
        today=today,
        now=now,
        current_capacity_pressure=(
            None if client_state is None else client_state.capacity_pressure
        ),
        current_permission_block=current_permission_block,
    )

    return RecordingHealthResponse(
        health=snapshot,
        today=coverage,
        aggregates=aggregates,
        recent_gaps=coverage.recent_gaps[-RECENT_GAP_LIMIT:],
        server_observed_at=now,
        native_state_observed=client_state is not None,
    )
