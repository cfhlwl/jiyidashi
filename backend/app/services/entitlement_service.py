from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.entitlement_models import (
    AIQuotaPeriod,
    AIUsageEvent,
    CapabilityCode,
    PlanCode,
    QuotaDimension,
    UserEntitlement,
)
from app.media_models import MediaAsset, MediaStatus
from app.services.runtime_policy_service import (
    RuntimeQuotaPolicyUnavailable,
    quota_limits_for_plan,
)

_POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807
_PROVIDER_REQUEST_ID_MAX_LENGTH = 255


class EntitlementError(RuntimeError):
    def __init__(self, code: str, status_code: int = 403):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ResolvedEntitlement:
    plan_code: PlanCode
    capabilities: frozenset[CapabilityCode]
    quota_limits: dict[QuotaDimension, int | None]


@dataclass(frozen=True)
class EntitlementSnapshot:
    plan_code: PlanCode
    capabilities: tuple[CapabilityCode, ...]
    storage_used_bytes: int
    storage_limit_bytes: int | None
    ai_requests_used: int
    ai_requests_limit: int | None
    ai_period_start: datetime
    ai_period_end: datetime


_ALL_CAPABILITIES = frozenset(CapabilityCode)
_PLAN_CAPABILITIES: dict[PlanCode, frozenset[CapabilityCode]] = {
    PlanCode.FREE: frozenset(
        {
            CapabilityCode.CORE_MEMORY,
            CapabilityCode.BASIC_SEARCH,
        }
    ),
    PlanCode.PERSONAL: frozenset(
        {
            CapabilityCode.CORE_MEMORY,
            CapabilityCode.BASIC_SEARCH,
            CapabilityCode.EXTENDED_HISTORY,
            CapabilityCode.IMAGE_MEDIA,
            CapabilityCode.VOICE_MEDIA,
            CapabilityCode.AI_INFERENCE,
            CapabilityCode.ANNUAL_MEMOIR,
        }
    ),
    PlanCode.FAMILY: frozenset(
        {
            CapabilityCode.CORE_MEMORY,
            CapabilityCode.BASIC_SEARCH,
            CapabilityCode.EXTENDED_HISTORY,
            CapabilityCode.IMAGE_MEDIA,
            CapabilityCode.VOICE_MEDIA,
            CapabilityCode.AI_INFERENCE,
            CapabilityCode.FAMILY_FEATURES,
            CapabilityCode.ELDER_MODE,
            CapabilityCode.ARRIVAL_REMINDER,
            CapabilityCode.ANNUAL_MEMOIR,
        }
    ),
    PlanCode.PREMIUM: _ALL_CAPABILITIES,
    PlanCode.LEGACY_FULL: _ALL_CAPABILITIES,
}

def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)



def create_legacy_full_entitlement(
    db: Session,
    *,
    user_id: UUID,
    now: datetime | None = None,
) -> UserEntitlement:
    observed_at = _as_utc(now or datetime.now(UTC))
    row = UserEntitlement(
        user_id=user_id,
        plan_code=PlanCode.LEGACY_FULL.value,
        revision=0,
        effective_at=observed_at,
        expires_at=None,
        created_at=observed_at,
        updated_at=observed_at,
    )
    db.add(row)
    return row


def _resolve_plan(
    db: Session,
    *,
    user_id: UUID,
    now: datetime,
    for_update: bool,
) -> tuple[PlanCode, frozenset[CapabilityCode]]:
    query = select(UserEntitlement).where(UserEntitlement.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    assignment = db.scalar(query)
    if assignment is None:
        raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)

    try:
        plan_code = PlanCode(assignment.plan_code)
    except ValueError as exc:
        raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503) from exc

    if _as_utc(assignment.effective_at) > now:
        raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)
    if assignment.expires_at is not None and _as_utc(assignment.expires_at) <= now:
        raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)
    return plan_code, _PLAN_CAPABILITIES[plan_code]


def resolve_entitlement(
    db: Session,
    *,
    user_id: UUID,
    settings: Settings | None = None,
    now: datetime | None = None,
    for_update: bool = False,
) -> ResolvedEntitlement:
    observed_at = _as_utc(now or datetime.now(UTC))
    plan_code, capabilities = _resolve_plan(
        db,
        user_id=user_id,
        now=observed_at,
        for_update=for_update,
    )
    try:
        quota_limits = quota_limits_for_plan(
            db,
            plan_code=plan_code,
            settings=settings or get_settings(),
        )
    except RuntimeQuotaPolicyUnavailable as exc:
        raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503) from exc
    return ResolvedEntitlement(
        plan_code=plan_code,
        capabilities=capabilities,
        quota_limits=quota_limits,
    )


def require_capability(
    db: Session,
    *,
    user_id: UUID,
    capability: CapabilityCode,
    settings: Settings | None = None,
) -> ResolvedEntitlement:
    observed_at = datetime.now(UTC)
    plan_code, capabilities = _resolve_plan(
        db,
        user_id=user_id,
        now=observed_at,
        for_update=True,
    )
    if capability not in capabilities:
        raise EntitlementError("ENTITLEMENT_CAPABILITY_REQUIRED", 403)
    try:
        quota_limits = quota_limits_for_plan(
            db,
            plan_code=plan_code,
            settings=settings or get_settings(),
        )
    except RuntimeQuotaPolicyUnavailable as exc:
        raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503) from exc
    return ResolvedEntitlement(
        plan_code=plan_code,
        capabilities=capabilities,
        quota_limits=quota_limits,
    )


def lock_entitlement_subject(db: Session, *, user_id: UUID) -> None:
    """Serialize one user's commercial authority without upgrading the request User lock."""

    entitlement_user_id = db.scalar(
        select(UserEntitlement.user_id)
        .where(UserEntitlement.user_id == user_id)
        .with_for_update()
    )
    if entitlement_user_id is None:
        raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)


def storage_usage_bytes(db: Session, *, user_id: UUID) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(MediaAsset.size_bytes), 0)).where(
            MediaAsset.user_id == user_id,
            MediaAsset.status.in_((MediaStatus.PENDING, MediaStatus.READY)),
        )
    )
    return int(value or 0)


def _utc_month_bounds(now: datetime) -> tuple[datetime, datetime]:
    observed = _as_utc(now)
    start = datetime(observed.year, observed.month, 1, tzinfo=UTC)
    if observed.month == 12:
        end = datetime(observed.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(observed.year, observed.month + 1, 1, tzinfo=UTC)
    return start, end


def _load_or_create_ai_period(
    db: Session,
    *,
    user_id: UUID,
    now: datetime,
) -> AIQuotaPeriod:
    period_start, period_end = _utc_month_bounds(now)
    period = db.scalar(
        select(AIQuotaPeriod)
        .where(
            AIQuotaPeriod.user_id == user_id,
            AIQuotaPeriod.period_start == period_start,
            AIQuotaPeriod.period_end == period_end,
        )
        .with_for_update()
    )
    if period is None:
        period = AIQuotaPeriod(
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
            provider_requests=0,
            input_tokens=0,
            output_tokens=0,
        )
        db.add(period)
        db.flush()
    return period


def reserve_ai_provider_request(
    bind: Engine,
    *,
    user_id: UUID,
    gateway_request_id: UUID,
    purpose: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> AIUsageEvent:
    """Reserve one provider invocation in an isolated short transaction."""

    observed_at = _as_utc(now or datetime.now(UTC))
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        lock_entitlement_subject(db, user_id=user_id)
        entitlement = require_capability(
            db,
            user_id=user_id,
            capability=CapabilityCode.AI_INFERENCE,
            settings=settings,
        )

        existing = db.scalar(
            select(AIUsageEvent).where(
                AIUsageEvent.user_id == user_id,
                AIUsageEvent.gateway_request_id == gateway_request_id,
            )
        )
        if existing is not None:
            if existing.purpose != purpose:
                db.rollback()
                raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)
            db.commit()
            return existing

        period = _load_or_create_ai_period(db, user_id=user_id, now=observed_at)
        limit = entitlement.quota_limits[QuotaDimension.AI_PROVIDER_REQUESTS]
        if limit is not None and period.provider_requests >= limit:
            db.rollback()
            raise EntitlementError("ENTITLEMENT_QUOTA_EXCEEDED", 429)
        if period.provider_requests >= _POSTGRES_BIGINT_MAX:
            db.rollback()
            raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)

        period.provider_requests += 1
        period.updated_at = observed_at
        event = AIUsageEvent(
            user_id=user_id,
            gateway_request_id=gateway_request_id,
            period_id=period.id,
            purpose=purpose,
            provider_invocation_reserved=True,
            created_at=observed_at,
        )
        db.add(event)
        db.commit()
        return event


def finalize_ai_usage(
    bind: Engine,
    *,
    user_id: UUID,
    gateway_request_id: UUID,
    provider_request_id: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    now: datetime | None = None,
) -> None:
    """Finalize safe usage metadata without touching the caller's business transaction."""

    observed_at = _as_utc(now or datetime.now(UTC))
    with Session(bind=bind, autoflush=False, expire_on_commit=False) as db:
        event = db.scalar(
            select(AIUsageEvent)
            .where(
                AIUsageEvent.user_id == user_id,
                AIUsageEvent.gateway_request_id == gateway_request_id,
            )
            .with_for_update()
        )
        if event is None:
            db.rollback()
            raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)
        if event.finalized_at is not None:
            db.commit()
            return

        period = db.scalar(
            select(AIQuotaPeriod)
            .where(AIQuotaPeriod.id == event.period_id)
            .with_for_update()
        )
        if period is None:
            db.rollback()
            raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)

        safe_input = 0 if input_tokens is None else input_tokens
        safe_output = 0 if output_tokens is None else output_tokens
        if (
            not isinstance(safe_input, int)
            or isinstance(safe_input, bool)
            or not isinstance(safe_output, int)
            or isinstance(safe_output, bool)
            or safe_input < 0
            or safe_output < 0
            or safe_input > _POSTGRES_BIGINT_MAX
            or safe_output > _POSTGRES_BIGINT_MAX
            or period.input_tokens > _POSTGRES_BIGINT_MAX - safe_input
            or period.output_tokens > _POSTGRES_BIGINT_MAX - safe_output
        ):
            db.rollback()
            raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)
        if provider_request_id is not None and (
            not isinstance(provider_request_id, str)
            or not provider_request_id.strip()
            or len(provider_request_id.strip()) > _PROVIDER_REQUEST_ID_MAX_LENGTH
        ):
            db.rollback()
            raise EntitlementError("ENTITLEMENT_STATE_UNAVAILABLE", 503)

        event.provider_request_id = (
            None if provider_request_id is None else provider_request_id.strip()
        )
        event.input_tokens = input_tokens
        event.output_tokens = output_tokens
        event.finalized_at = observed_at
        period.input_tokens += safe_input
        period.output_tokens += safe_output
        period.updated_at = observed_at
        db.commit()


def entitlement_snapshot(
    db: Session,
    *,
    user_id: UUID,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> EntitlementSnapshot:
    observed_at = _as_utc(now or datetime.now(UTC))
    entitlement = resolve_entitlement(
        db,
        user_id=user_id,
        settings=settings,
        now=observed_at,
    )
    period_start, period_end = _utc_month_bounds(observed_at)
    period = db.scalar(
        select(AIQuotaPeriod).where(
            AIQuotaPeriod.user_id == user_id,
            AIQuotaPeriod.period_start == period_start,
            AIQuotaPeriod.period_end == period_end,
        )
    )
    return EntitlementSnapshot(
        plan_code=entitlement.plan_code,
        capabilities=tuple(sorted(entitlement.capabilities, key=lambda item: item.value)),
        storage_used_bytes=storage_usage_bytes(db, user_id=user_id),
        storage_limit_bytes=entitlement.quota_limits[QuotaDimension.STORAGE_BYTES],
        ai_requests_used=0 if period is None else period.provider_requests,
        ai_requests_limit=entitlement.quota_limits[QuotaDimension.AI_PROVIDER_REQUESTS],
        ai_period_start=period_start,
        ai_period_end=period_end,
    )
