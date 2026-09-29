from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.entitlement_models import CapabilityCode, PlanCode


class QuotaRead(BaseModel):
    used: int
    limit: int | None


class AIQuotaRead(QuotaRead):
    period_start: datetime
    period_end: datetime


class EntitlementRead(BaseModel):
    plan_code: PlanCode
    capabilities: list[CapabilityCode]
    storage: QuotaRead
    ai_requests: AIQuotaRead
