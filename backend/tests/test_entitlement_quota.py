from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.db import Base
from app.entitlement_models import (
    AIQuotaPeriod,
    AIUsageEvent,
    CapabilityCode,
    PlanCode,
    QuotaDimension,
    UserEntitlement,
)
from app.media_models import MediaAsset, MediaKind, MediaStatus
from app.models import User
from app.services.entitlement_service import (
    EntitlementError,
    entitlement_snapshot,
    finalize_ai_usage,
    require_capability,
    reserve_ai_provider_request,
    resolve_entitlement,
    storage_usage_bytes,
)


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            UserEntitlement.__table__,
            AIQuotaPeriod.__table__,
            AIUsageEvent.__table__,
            MediaAsset.__table__,
        ],
    )
    return engine


def _settings(**overrides) -> Settings:
    catalog = {
        plan: {
            QuotaDimension.STORAGE_BYTES.value: 100,
            QuotaDimension.AI_PROVIDER_REQUESTS.value: 2,
        }
        for plan in ("FREE", "PERSONAL", "FAMILY", "PREMIUM")
    }
    values = {
        "app_env": "test",
        "entitlement_quota_catalog": catalog,
    }
    values.update(overrides)
    return Settings(**values)


def _seed_entitlement(
    db: Session,
    *,
    plan_code: PlanCode,
) -> User:
    user = User(id=uuid4(), nickname=f"{plan_code.value}-user")
    db.add(user)
    db.flush()
    now = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)
    db.add(
        UserEntitlement(
            user_id=user.id,
            plan_code=plan_code.value,
            revision=0,
            effective_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return user


def test_plan_catalog_and_legacy_full_are_deterministic() -> None:
    engine = _engine()
    settings = _settings()
    expected = {
        PlanCode.FREE: {
            CapabilityCode.CORE_MEMORY,
            CapabilityCode.BASIC_SEARCH,
        },
        PlanCode.PERSONAL: {
            CapabilityCode.CORE_MEMORY,
            CapabilityCode.BASIC_SEARCH,
            CapabilityCode.EXTENDED_HISTORY,
            CapabilityCode.IMAGE_MEDIA,
            CapabilityCode.VOICE_MEDIA,
            CapabilityCode.AI_INFERENCE,
            CapabilityCode.ANNUAL_MEMOIR,
        },
        PlanCode.FAMILY: {
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
        },
        PlanCode.PREMIUM: set(CapabilityCode),
        PlanCode.LEGACY_FULL: set(CapabilityCode),
    }
    with Session(engine) as db:
        for plan_code, capabilities in expected.items():
            user = _seed_entitlement(db, plan_code=plan_code)
            resolved = resolve_entitlement(
                db,
                user_id=user.id,
                settings=settings,
                now=datetime(2026, 9, 29, 1, 0, tzinfo=UTC),
            )
            assert set(resolved.capabilities) == capabilities
            if plan_code == PlanCode.LEGACY_FULL:
                assert all(value is None for value in resolved.quota_limits.values())


def test_missing_or_unconfigured_entitlement_fails_closed() -> None:
    engine = _engine()
    user_id = uuid4()
    with Session(engine) as db:
        db.add(User(id=user_id, nickname="missing-entitlement"))
        db.commit()
        with pytest.raises(EntitlementError, match="ENTITLEMENT_STATE_UNAVAILABLE"):
            resolve_entitlement(db, user_id=user_id, settings=_settings())

        now = datetime(2026, 9, 29, 0, 0, tzinfo=UTC)
        db.add(
            UserEntitlement(
                user_id=user_id,
                plan_code=PlanCode.FREE.value,
                revision=0,
                effective_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
        with pytest.raises(EntitlementError, match="ENTITLEMENT_STATE_UNAVAILABLE"):
            resolve_entitlement(
                db,
                user_id=user_id,
                settings=Settings(app_env="test", entitlement_quota_catalog={}),
            )


def test_free_plan_denies_media_and_ai_capabilities() -> None:
    engine = _engine()
    with Session(engine) as db:
        user = _seed_entitlement(db, plan_code=PlanCode.FREE)
        for capability in (
            CapabilityCode.IMAGE_MEDIA,
            CapabilityCode.VOICE_MEDIA,
            CapabilityCode.AI_INFERENCE,
        ):
            with pytest.raises(
                EntitlementError,
                match="ENTITLEMENT_CAPABILITY_REQUIRED",
            ):
                require_capability(
                    db,
                    user_id=user.id,
                    capability=capability,
                    settings=_settings(),
                )
            db.rollback()


def test_storage_usage_counts_pending_and_ready_only() -> None:
    engine = _engine()
    with Session(engine) as db:
        user = _seed_entitlement(db, plan_code=PlanCode.FREE)
        for index, (status, size) in enumerate(
            ((MediaStatus.PENDING, 30), (MediaStatus.READY, 40))
        ):
            db.add(
                MediaAsset(
                    user_id=user.id,
                    client_upload_id=uuid4(),
                    kind=MediaKind.IMAGE,
                    status=status,
                    upload_object_key=f"staging/{user.id}/{index}",
                    object_key=f"final/{user.id}/{index}",
                    content_type="image/jpeg",
                    size_bytes=size,
                )
            )
        db.commit()
        assert storage_usage_bytes(db, user_id=user.id) == 70

        snapshot = entitlement_snapshot(
            db,
            user_id=user.id,
            settings=_settings(),
            now=datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
        )
        assert snapshot.storage_used_bytes == 70
        assert snapshot.storage_limit_bytes == 100


def test_ai_reservation_is_idempotent_and_exact_limit() -> None:
    engine = _engine()
    settings = _settings()
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    with Session(engine) as db:
        user = _seed_entitlement(db, plan_code=PlanCode.FREE)
        first_id = uuid4()
        first = reserve_ai_provider_request(
            db,
            user_id=user.id,
            gateway_request_id=first_id,
            purpose="unit.ai",
            settings=settings,
            now=now,
        )
        replay = reserve_ai_provider_request(
            db,
            user_id=user.id,
            gateway_request_id=first_id,
            purpose="unit.ai",
            settings=settings,
            now=now,
        )
        assert replay.id == first.id

        second_id = uuid4()
        reserve_ai_provider_request(
            db,
            user_id=user.id,
            gateway_request_id=second_id,
            purpose="unit.ai",
            settings=settings,
            now=now,
        )
        with pytest.raises(EntitlementError, match="ENTITLEMENT_QUOTA_EXCEEDED"):
            reserve_ai_provider_request(
                db,
                user_id=user.id,
                gateway_request_id=uuid4(),
                purpose="unit.ai",
                settings=settings,
                now=now,
            )

        period = db.scalar(select(AIQuotaPeriod).where(AIQuotaPeriod.user_id == user.id))
        assert period is not None
        assert period.provider_requests == 2
        assert len(
            list(db.scalars(select(AIUsageEvent).where(AIUsageEvent.user_id == user.id)))
        ) == 2


def test_ai_token_finalization_does_not_double_charge_request() -> None:
    engine = _engine()
    settings = _settings()
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    with Session(engine) as db:
        user = _seed_entitlement(db, plan_code=PlanCode.FREE)
        operation_id = uuid4()
        reserve_ai_provider_request(
            db,
            user_id=user.id,
            gateway_request_id=operation_id,
            purpose="unit.ai",
            settings=settings,
            now=now,
        )
        finalize_ai_usage(
            db,
            user_id=user.id,
            gateway_request_id=operation_id,
            provider_request_id="provider-1",
            input_tokens=7,
            output_tokens=3,
            now=now,
        )
        finalize_ai_usage(
            db,
            user_id=user.id,
            gateway_request_id=operation_id,
            provider_request_id="provider-1",
            input_tokens=7,
            output_tokens=3,
            now=now,
        )
        period = db.scalar(select(AIQuotaPeriod).where(AIQuotaPeriod.user_id == user.id))
        assert period is not None
        assert period.provider_requests == 1
        assert period.input_tokens == 7
        assert period.output_tokens == 3


@pytest.mark.asyncio
async def test_entitlement_me_for_new_dev_user_is_explicit_legacy_full(client) -> None:
    token = await client.post("/v1/auth/dev-token", json={"nickname": "entitlement-me"})
    assert token.status_code == 200
    response = await client.get(
        "/v1/entitlements/me",
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["plan_code"] == "LEGACY_FULL"
    assert body["storage"]["limit"] is None
    assert body["ai_requests"]["limit"] is None
    assert set(body["capabilities"]) == {item.value for item in CapabilityCode}
