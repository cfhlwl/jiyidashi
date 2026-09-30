from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin_models import EntitlementQuotaPolicy
from app.core.config import Settings, get_settings
from app.entitlement_models import PlanCode, QuotaDimension

COMMERCIAL_PLAN_CODES = (
    PlanCode.FREE,
    PlanCode.PERSONAL,
    PlanCode.FAMILY,
    PlanCode.PREMIUM,
)
_REQUIRED_COMMERCIAL_QUOTAS = frozenset(
    {
        QuotaDimension.STORAGE_BYTES,
        QuotaDimension.AI_PROVIDER_REQUESTS,
    }
)


class RuntimeQuotaPolicyUnavailable(RuntimeError):
    pass


def _legacy_env_quota_catalog(
    settings: Settings,
    plan_code: PlanCode,
) -> dict[QuotaDimension, int | None]:
    raw = settings.entitlement_quota_catalog.get(plan_code.value)
    if not isinstance(raw, dict):
        raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")

    parsed: dict[QuotaDimension, int | None] = {}
    for dimension in QuotaDimension:
        value = raw.get(dimension.value)
        if value is None:
            parsed[dimension] = None
        elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            parsed[dimension] = value
        else:
            raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")

    if any(parsed[item] is None for item in _REQUIRED_COMMERCIAL_QUOTAS):
        raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")
    return parsed


def quota_policy_row_count(db: Session) -> int:
    return int(db.scalar(select(func.count(EntitlementQuotaPolicy.plan_code))) or 0)


def commercial_quota_catalog_initialized(db: Session) -> bool:
    count = quota_policy_row_count(db)
    if count == 0:
        return False
    if count != len(COMMERCIAL_PLAN_CODES):
        raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")

    plans = set(db.scalars(select(EntitlementQuotaPolicy.plan_code)))
    expected = {item.value for item in COMMERCIAL_PLAN_CODES}
    if plans != expected:
        raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")
    return True


def quota_limits_for_plan(
    db: Session,
    *,
    plan_code: PlanCode,
    settings: Settings | None = None,
) -> dict[QuotaDimension, int | None]:
    if plan_code == PlanCode.LEGACY_FULL:
        return {dimension: None for dimension in QuotaDimension}

    count = quota_policy_row_count(db)
    if count == 0:
        # ADMIN-001 migration bridge: until the first atomic DB catalog initialization,
        # preserve the reviewed pre-ADMIN server config. Once any DB policy exists,
        # DB becomes the sole runtime authority and partial/corrupt state fails closed.
        return _legacy_env_quota_catalog(settings or get_settings(), plan_code)

    if count != len(COMMERCIAL_PLAN_CODES):
        raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")

    row = db.get(EntitlementQuotaPolicy, plan_code.value)
    if row is None:
        raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")

    values = {
        QuotaDimension.STORAGE_BYTES: row.storage_bytes,
        QuotaDimension.AI_PROVIDER_REQUESTS: row.ai_provider_requests,
        QuotaDimension.AI_INPUT_TOKENS: row.ai_input_tokens,
        QuotaDimension.AI_OUTPUT_TOKENS: row.ai_output_tokens,
    }
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in values.values()
    ):
        raise RuntimeQuotaPolicyUnavailable("ENTITLEMENT_STATE_UNAVAILABLE")
    return values


def read_runtime_quota_rows(
    db: Session,
    *,
    for_update: bool = False,
) -> list[EntitlementQuotaPolicy]:
    query = select(EntitlementQuotaPolicy).order_by(EntitlementQuotaPolicy.plan_code.asc())
    if for_update:
        query = query.with_for_update()
    return list(db.scalars(query))
