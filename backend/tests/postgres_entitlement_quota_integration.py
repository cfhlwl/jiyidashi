"""Real PostgreSQL BIZ entitlement/quota authority gate."""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock, Thread
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text

from app.auth_models import AuthIdentity, AuthProvider
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, engine
from app.entitlement_models import (
    AIQuotaPeriod,
    AIUsageEvent,
    PlanCode,
    QuotaDimension,
    UserEntitlement,
)
from app.media_models import MediaAsset, MediaKind
from app.models import User
from app.schemas import MediaUploadCreate, RegisterRequest
from app.services.account_deletion_service import delete_current_account
from app.services.auth_service import register_email_password
from app.services.ai_gateway import (
    AIEntitlementError,
    AIGateway,
    AIInferenceRequest,
    AIProviderError,
    DeterministicAIProvider,
)
from app.services.data_deletion_service import delete_all_user_data
from app.services.entitlement_service import EntitlementError
from app.services.media_service import start_media_upload
from app.services.object_storage import PresignedTransfer

DATABASE_URL = os.environ["DATABASE_URL"]


class SigningOnlyStorage:
    def sign_upload(self, object_key: str, content_type: str) -> PresignedTransfer:
        del object_key, content_type
        return PresignedTransfer(
            url="https://storage.invalid/upload",
            method="PUT",
            headers={},
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )


class EmptyStorage:
    def iter_object_keys(self, prefix: str):
        del prefix
        return iter(())

    def delete_object(self, object_key: str) -> None:
        del object_key


class FailingProvider:
    async def infer(self, request):
        del request
        raise AIProviderError("AI_PROVIDER_FAILED", retryable=True, status_code=503)

    async def infer_image(self, request):
        del request
        raise AIProviderError("AI_PROVIDER_FAILED", retryable=True, status_code=503)


def _alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True)


def _quota_catalog(storage_limit: int, ai_limit: int) -> dict[str, dict[str, int]]:
    return {
        plan: {
            QuotaDimension.STORAGE_BYTES.value: storage_limit,
            QuotaDimension.AI_PROVIDER_REQUESTS.value: ai_limit,
        }
        for plan in ("FREE", "PERSONAL", "FAMILY", "PREMIUM")
    }


def _seed_user(plan: PlanCode = PlanCode.FREE) -> UUID:
    user_id = uuid4()
    now = datetime.now(UTC)
    with SessionLocal() as db:
        db.add(User(id=user_id, nickname=f"biz-{plan.value.lower()}"))
        db.flush()
        db.add(
            UserEntitlement(
                user_id=user_id,
                plan_code=plan.value,
                revision=0,
                effective_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    return user_id


def _cleanup_user(user_id: UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(User).where(User.id == user_id))
        db.commit()


def _prove_migration_backfill() -> None:
    _alembic("downgrade", "0025_security_alerting")
    legacy_user = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (
                    id, nickname, timezone, locale, elder_mode_enabled, created_at, updated_at
                ) VALUES (
                    :id, 'pre-0026-user', 'UTC', 'zh-CN', false,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"id": legacy_user},
        )

    _alembic("upgrade", "head")
    with SessionLocal() as db:
        row = db.get(UserEntitlement, legacy_user)
        assert row is not None
        assert row.plan_code == PlanCode.LEGACY_FULL.value
        assert row.revision == 0
        db.delete(db.get(User, legacy_user))
        db.commit()


def _prove_registration_default_free_concurrency() -> None:
    email = f"biz011-register-{uuid4()}@example.com"
    start = Barrier(2)
    lock = Lock()
    successes: list[UUID] = []
    conflicts: list[str] = []
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        db = SessionLocal()
        try:
            start.wait(timeout=15)
            user = register_email_password(
                db,
                RegisterRequest(
                    email=email,
                    password="correct-horse-battery-staple",
                    nickname=f"BIZ011 concurrent {index}",
                    timezone="Asia/Shanghai",
                    locale="zh-CN",
                ),
                client_ip=f"198.51.100.{10 + index}",
            )
            with lock:
                successes.append(user.id)
        except HTTPException as exc:
            if exc.status_code == 409 and exc.detail == "AUTH_IDENTITY_EXISTS":
                with lock:
                    conflicts.append(str(exc.detail))
            else:
                with lock:
                    errors.append(exc)
        except BaseException as exc:  # noqa: BLE001
            db.rollback()
            with lock:
                errors.append(exc)
        finally:
            db.close()

    first = Thread(target=worker, args=(1,), name="biz011-register-a")
    second = Thread(target=worker, args=(2,), name="biz011-register-b")
    first.start()
    second.start()
    first.join(timeout=30)
    second.join(timeout=30)
    assert not first.is_alive() and not second.is_alive()
    if errors:
        raise errors[0]
    assert len(successes) == 1, successes
    assert conflicts == ["AUTH_IDENTITY_EXISTS"], conflicts

    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.email == email)))
        assert len(users) == 1
        user = users[0]
        assert db.scalar(
            select(func.count(AuthIdentity.id)).where(
                AuthIdentity.user_id == user.id,
                AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
                AuthIdentity.subject == email,
            )
        ) == 1
        row = db.get(UserEntitlement, user.id)
        assert row is not None
        assert row.plan_code == PlanCode.FREE.value
        assert row.revision == 0
        assert row.expires_at is None
        db.delete(user)
        db.commit()


def _prove_storage_race(settings) -> None:
    user_id = _seed_user(PlanCode.PERSONAL)
    start = Barrier(2)
    lock = Lock()
    successes: list[UUID] = []
    denials: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        db = SessionLocal()
        client_upload_id = uuid4()
        try:
            start.wait(timeout=15)
            result = start_media_upload(
                db,
                user_id,
                MediaUploadCreate(
                    client_upload_id=client_upload_id,
                    kind=MediaKind.IMAGE,
                    content_type="image/jpeg",
                    size_bytes=6,
                    original_filename="quota.jpg",
                ),
                SigningOnlyStorage(),
            )
            db.commit()
            with lock:
                successes.append(result.asset.client_upload_id)
        except EntitlementError as exc:
            db.rollback()
            with lock:
                denials.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            db.rollback()
            with lock:
                errors.append(exc)
        finally:
            db.close()

    first = Thread(target=worker, name="storage-quota-a")
    second = Thread(target=worker, name="storage-quota-b")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive() and not second.is_alive()
    if errors:
        raise errors[0]
    assert len(successes) == 1, successes
    assert denials == ["ENTITLEMENT_QUOTA_EXCEEDED"], denials

    with SessionLocal() as db:
        rows = list(db.scalars(select(MediaAsset).where(MediaAsset.user_id == user_id)))
        assert len(rows) == 1
        assert sum(row.size_bytes for row in rows) == 6

        replay = start_media_upload(
            db,
            user_id,
            MediaUploadCreate(
                client_upload_id=successes[0],
                kind=MediaKind.IMAGE,
                content_type="image/jpeg",
                size_bytes=6,
                original_filename="quota.jpg",
            ),
            SigningOnlyStorage(),
        )
        assert replay.asset.id == rows[0].id
        db.commit()
        assert db.scalar(
            select(func.count(MediaAsset.id)).where(MediaAsset.user_id == user_id)
        ) == 1

    _cleanup_user(user_id)


def _ai_request() -> AIInferenceRequest:
    return AIInferenceRequest(
        purpose="biz.quota",
        system_instruction="Return one deterministic inference.",
        input_text="quota test",
        max_output_tokens=32,
    )


def _prove_ai_last_slot_race(settings: Settings) -> None:
    user_id = _seed_user(PlanCode.PERSONAL)
    provider = DeterministicAIProvider()
    start = Barrier(2)
    lock = Lock()
    successes: list[str] = []
    denials: list[str] = []
    errors: list[BaseException] = []

    def worker() -> None:
        db = SessionLocal()
        gateway = AIGateway(settings, provider)
        try:
            start.wait(timeout=15)
            result = asyncio.run(
                gateway.infer(
                    _ai_request(),
                    db=db,
                    actor_user_id=user_id,
                )
            )
            with lock:
                successes.append(result.provenance.gateway_request_id)
        except AIEntitlementError as exc:
            with lock:
                denials.append(exc.code)
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)
        finally:
            db.close()

    first = Thread(target=worker, name="ai-quota-a")
    second = Thread(target=worker, name="ai-quota-b")
    first.start()
    second.start()
    first.join(timeout=20)
    second.join(timeout=20)
    assert not first.is_alive() and not second.is_alive()
    if errors:
        raise errors[0]

    assert len(successes) == 1
    assert denials == ["ENTITLEMENT_QUOTA_EXCEEDED"]
    assert len(provider.requests) == 1

    with SessionLocal() as db:
        period = db.scalar(select(AIQuotaPeriod).where(AIQuotaPeriod.user_id == user_id))
        assert period is not None
        assert period.provider_requests == 1
        assert db.scalar(
            select(func.count(AIUsageEvent.id)).where(AIUsageEvent.user_id == user_id)
        ) == 1

    _cleanup_user(user_id)


def _prove_provider_failure_remains_charged(settings: Settings) -> None:
    user_id = _seed_user(PlanCode.PERSONAL)
    with SessionLocal() as db:
        gateway = AIGateway(settings, FailingProvider())
        try:
            asyncio.run(
                gateway.infer(
                    _ai_request(),
                    db=db,
                    actor_user_id=user_id,
                )
            )
        except AIProviderError as exc:
            assert exc.code == "AI_PROVIDER_FAILED"
        else:
            raise AssertionError("provider failure did not propagate")

    with SessionLocal() as db:
        period = db.scalar(select(AIQuotaPeriod).where(AIQuotaPeriod.user_id == user_id))
        assert period is not None
        assert period.provider_requests == 1
        assert db.scalar(
            select(func.count(AIUsageEvent.id)).where(AIUsageEvent.user_id == user_id)
        ) == 1
    _cleanup_user(user_id)


def _seed_usage(user_id: UUID) -> None:
    now = datetime.now(UTC)
    period_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    period_end = (
        datetime(now.year + 1, 1, 1, tzinfo=UTC)
        if now.month == 12
        else datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    )
    with SessionLocal() as db:
        period = AIQuotaPeriod(
            user_id=user_id,
            period_start=period_start,
            period_end=period_end,
            provider_requests=1,
            input_tokens=2,
            output_tokens=3,
        )
        db.add(period)
        db.flush()
        db.add(
            AIUsageEvent(
                user_id=user_id,
                gateway_request_id=uuid4(),
                period_id=period.id,
                purpose="biz.lifecycle",
                provider_invocation_reserved=True,
            )
        )
        db.commit()


def _prove_deletion_lifecycle() -> None:
    data_user = _seed_user(PlanCode.LEGACY_FULL)
    _seed_usage(data_user)
    with SessionLocal() as db:
        result = delete_all_user_data(
            db,
            user_id=data_user,
            request_id=uuid4(),
            storage=EmptyStorage(),
        )
        assert result.completed is True
    with SessionLocal() as db:
        assert db.get(UserEntitlement, data_user) is not None
        assert db.scalar(
            select(func.count(AIQuotaPeriod.id)).where(AIQuotaPeriod.user_id == data_user)
        ) == 1
        assert db.scalar(
            select(func.count(AIUsageEvent.id)).where(AIUsageEvent.user_id == data_user)
        ) == 1
    _cleanup_user(data_user)

    account_user = _seed_user(PlanCode.LEGACY_FULL)
    _seed_usage(account_user)
    with SessionLocal() as db:
        result = delete_current_account(
            db,
            user_id=account_user,
            request_id=uuid4(),
            storage=EmptyStorage(),
            local_cleanup_ready=True,
        )
        assert result.completed is True
    with SessionLocal() as db:
        assert db.get(User, account_user) is None
        assert db.get(UserEntitlement, account_user) is None
        assert db.scalar(
            select(func.count(AIQuotaPeriod.id)).where(
                AIQuotaPeriod.user_id == account_user
            )
        ) == 0
        assert db.scalar(
            select(func.count(AIUsageEvent.id)).where(
                AIUsageEvent.user_id == account_user
            )
        ) == 0


def main() -> None:
    _prove_migration_backfill()

    global_settings = get_settings()
    old_catalog = dict(global_settings.entitlement_quota_catalog)
    global_settings.entitlement_quota_catalog = _quota_catalog(
        storage_limit=10,
        ai_limit=1,
    )
    gateway_settings = Settings(
        app_env="test",
        ai_provider="disabled",
        entitlement_quota_catalog=_quota_catalog(storage_limit=10, ai_limit=1),
    )
    try:
        _prove_registration_default_free_concurrency()
        _prove_storage_race(global_settings)
        _prove_ai_last_slot_race(gateway_settings)
        _prove_provider_failure_remains_charged(gateway_settings)
        _prove_deletion_lifecycle()
    finally:
        global_settings.entitlement_quota_catalog = old_catalog

    print("PostgreSQL Entitlement & Quota concurrency PASS")


if __name__ == "__main__":
    main()
