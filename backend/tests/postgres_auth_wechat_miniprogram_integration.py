"""Real PostgreSQL AUTH-002 Mini Program identity and replay gate."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.auth_models import (
    AuthIdentity,
    AuthProvider,
    AuthSession,
    WechatMiniProgramExchange,
    WechatMiniProgramExchangeState,
)
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.entitlement_models import UserEntitlement
from app.models import User
from app.services.wechat_miniprogram_login_service import (
    WechatMiniProgramLoginError,
    exchange_wechat_miniprogram_code,
)
from app.services.wechat_miniprogram_provider import VerifiedWechatMiniProgramResult

DATABASE_URL = os.environ["DATABASE_URL"]
settings = get_settings()
settings.auth_rate_limit_enabled = False
settings.auth_wechat_miniprogram_app_id = "pg-mini-app"
settings.auth_wechat_miniprogram_fingerprint_secret = "auth-002-postgres-test-key"
settings.auth_wechat_miniprogram_global_concurrency = 8
settings.auth_wechat_miniprogram_permit_lease_seconds = 30


class FakeProvider:
    available = True

    def __init__(self, outcomes: dict[str, VerifiedWechatMiniProgramResult]):
        self.outcomes = outcomes
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def exchange_code(self, *, code: str, request_id: UUID):
        del request_id
        with self._lock:
            self.calls.append(code)
        return self.outcomes[code]


def _require_real_postgresql() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("AUTH-002 gate requires PostgreSQL DATABASE_URL")
    if engine.dialect.name != "postgresql":
        raise RuntimeError(f"expected PostgreSQL engine, got {engine.dialect.name}")


def _verified(openid: str) -> VerifiedWechatMiniProgramResult:
    return VerifiedWechatMiniProgramResult(
        app_id=settings.auth_wechat_miniprogram_app_id,
        openid=openid,
        unionid=None,
        verified_at=datetime.now(UTC),
    )


def _exchange(*, provider: FakeProvider, code: str, request_id: UUID, device_id: str):
    with SessionLocal() as db:
        try:
            result = exchange_wechat_miniprogram_code(
                db,
                code=code,
                request_id=request_id,
                device_id=device_id,
                client_platform="postgres-integration",
                device_name="AUTH-002 PostgreSQL",
                client_ip=f"198.51.100.{uuid4().int % 200 + 1}",
                provider=provider,
                settings=settings,
            )
            return ("ok", result)
        except WechatMiniProgramLoginError as exc:
            return (exc.code, None)


def _cleanup(*, request_ids: set[UUID], user_ids: set[UUID]) -> None:
    with SessionLocal() as db:
        db.execute(
            delete(WechatMiniProgramExchange).where(
                WechatMiniProgramExchange.request_id.in_(request_ids)
            )
        )
        if user_ids:
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
            db.execute(delete(AuthIdentity).where(AuthIdentity.user_id.in_(user_ids)))
            db.execute(
                delete(UserEntitlement).where(UserEntitlement.user_id.in_(user_ids))
            )
            db.execute(delete(User).where(User.id.in_(user_ids)))
        db.commit()


def test_postgresql_wechat_miniprogram_exchange_races_and_replay() -> None:
    """Exercise durable reservation, identity uniqueness, and terminal replay."""

    _require_real_postgresql()
    request_ids: set[UUID] = set()
    user_ids: set[UUID] = set()
    provider = FakeProvider(
        {
            "same-code": _verified("same-openid"),
            "owner-a": _verified("shared-openid"),
            "owner-b": _verified("shared-openid"),
        }
    )

    try:
        same_request = uuid4()
        request_ids.add(same_request)
        start = threading.Barrier(2)

        def same_code_attempt(_: int):
            start.wait(timeout=30)
            return _exchange(
                provider=provider,
                code="same-code",
                request_id=same_request,
                device_id=f"pg-mini-same-{uuid4()}",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            same_results = list(executor.map(same_code_attempt, range(2)))

        assert sum(result[0] == "ok" for result in same_results) == 1, same_results
        assert sum(
            result[0]
            in {
                "AUTH_WECHAT_MINIPROGRAM_TIMEOUT",
                "AUTH_WECHAT_MINIPROGRAM_CODE_REPLAYED",
            }
            for result in same_results
        ) == 1, same_results
        assert provider.calls.count("same-code") == 1

        with SessionLocal() as db:
            receipt = db.scalar(
                select(WechatMiniProgramExchange).where(
                    WechatMiniProgramExchange.request_id == same_request
                )
            )
            assert receipt is not None
            assert receipt.state == WechatMiniProgramExchangeState.COMPLETED
            assert receipt.resolved_user_id is not None
            user_ids.add(receipt.resolved_user_id)
            assert (
                db.scalar(
                    select(func.count(AuthIdentity.id)).where(
                        AuthIdentity.provider == AuthProvider.WECHAT_MINIPROGRAM,
                        AuthIdentity.subject == "openid:pg-mini-app:same-openid",
                    )
                )
                == 1
            )

        race_requests = {uuid4(), uuid4()}
        request_ids.update(race_requests)
        with ThreadPoolExecutor(max_workers=2) as executor:
            race_results = list(
                executor.map(
                    lambda pair: _exchange(
                        provider=provider,
                        code=pair[0],
                        request_id=pair[1],
                        device_id=f"pg-mini-owner-{uuid4()}",
                    ),
                    zip(("owner-a", "owner-b"), race_requests, strict=True),
                )
            )

        assert all(
            result[0] in {"ok", "AUTH_IDENTITY_CONFLICT"} for result in race_results
        ), race_results
        assert any(result[0] == "ok" for result in race_results), race_results
        assert provider.calls.count("owner-a") == 1
        assert provider.calls.count("owner-b") == 1

        with SessionLocal() as db:
            identities = list(
                db.scalars(
                    select(AuthIdentity).where(
                        AuthIdentity.provider == AuthProvider.WECHAT_MINIPROGRAM,
                        AuthIdentity.subject == "openid:pg-mini-app:shared-openid",
                    )
                )
            )
            assert len(identities) == 1
            user_ids.add(identities[0].user_id)
            assert (
                db.scalar(
                    select(func.count(User.id)).where(User.id.in_(set(user_ids)))
                )
                == len(user_ids)
            )
            assert (
                db.scalar(
                    select(func.count(WechatMiniProgramExchange.id)).where(
                        WechatMiniProgramExchange.request_id.in_(race_requests),
                        WechatMiniProgramExchange.state
                        == WechatMiniProgramExchangeState.PROVIDER_REJECTED,
                        WechatMiniProgramExchange.error_code == "AUTH_IDENTITY_CONFLICT",
                    )
                )
                == sum(result[0] == "AUTH_IDENTITY_CONFLICT" for result in race_results)
            )

        replay = _exchange(
            provider=provider,
            code="same-code",
            request_id=same_request,
            device_id=f"pg-mini-replay-{uuid4()}",
        )
        assert replay[0] == "AUTH_WECHAT_MINIPROGRAM_CODE_REPLAYED"
        assert provider.calls.count("same-code") == 1
    finally:
        _cleanup(request_ids=request_ids, user_ids=user_ids)


if __name__ == "__main__":
    test_postgresql_wechat_miniprogram_exchange_races_and_replay()
    print("AUTH-002 PostgreSQL Mini Program identity/replay gate: PASS")
