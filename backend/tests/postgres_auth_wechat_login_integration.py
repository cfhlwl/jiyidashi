"""Real PostgreSQL AUTH-04 WeChat identity, recovery, and rollback gate."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from app.account_deletion_models import AccountDeletionOperation
from app.auth_models import AuthIdentity, AuthProvider, AuthSession, WechatLoginExchange
from app.core.config import get_settings
from app.core.db import SessionLocal, engine
from app.models import User
from app.services import wechat_login_service
from app.services.auth_session_service import PublicAuthError
from app.services.wechat_auth_provider import VerifiedWechatResult
from app.services.wechat_login_service import WechatLoginError, exchange_wechat_credential

DATABASE_URL = os.environ["DATABASE_URL"]
settings = get_settings()
settings.auth_rate_limit_enabled = False
settings.auth_wechat_app_id = "pg-wechat-app"
settings.auth_wechat_subject_scope = "pg-wechat-scope"
settings.auth_wechat_fingerprint_secret = "auth-04-postgres-test-key"
settings.auth_wechat_global_concurrency = 8
settings.auth_wechat_permit_lease_seconds = 30


class FakeProvider:
    available = True

    def __init__(self, outcomes: dict[str, VerifiedWechatResult]):
        self.outcomes = outcomes
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def exchange_credential(self, *, credential: str, request_id: UUID):
        with self._lock:
            self.calls.append(credential)
        with SessionLocal() as db:
            assert db.in_transaction() is False
        return self.outcomes[credential]


def _require_real_postgresql() -> None:
    if not DATABASE_URL.startswith("postgresql"):
        raise RuntimeError("AUTH-04 gate requires PostgreSQL DATABASE_URL")
    if engine.dialect.name != "postgresql":
        raise RuntimeError(f"expected PostgreSQL engine, got {engine.dialect.name}")


def _verified(*, openid: str, unionid: str) -> VerifiedWechatResult:
    return VerifiedWechatResult(
        app_id=settings.auth_wechat_app_id,
        scope=settings.auth_wechat_subject_scope,
        openid=openid,
        unionid=unionid,
        verified_at=datetime.now(UTC),
    )


def _exchange(
    *, provider: FakeProvider, credential: str, device_id: str, request_id: UUID | None = None
):
    request_id = request_id or uuid4()
    with SessionLocal() as db:
        try:
            result = exchange_wechat_credential(
                db,
                credential=credential,
                request_id=request_id,
                device_id=device_id,
                client_platform="postgres-integration",
                device_name="AUTH-04 PostgreSQL",
                client_ip=f"198.51.100.{uuid4().int % 200 + 1}",
                provider=provider,
                settings=settings,
            )
            return ("ok", result, request_id)
        except WechatLoginError as exc:
            return (exc.code, None, request_id)


def _cleanup(*, request_ids: set[UUID], user_ids: set[UUID]) -> None:
    with SessionLocal() as db:
        if request_ids:
            db.execute(
                delete(WechatLoginExchange).where(WechatLoginExchange.request_id.in_(request_ids))
            )
        if user_ids:
            db.execute(
                delete(AccountDeletionOperation).where(
                    AccountDeletionOperation.user_id.in_(user_ids)
                )
            )
            db.execute(delete(AuthSession).where(AuthSession.user_id.in_(user_ids)))
            db.execute(delete(AuthIdentity).where(AuthIdentity.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))
        db.commit()


def _prove_same_identity_concurrency(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    provider = FakeProvider(
        {
            "same-unionid-a": _verified(openid="same-openid-a", unionid="same-unionid"),
            "same-unionid-b": _verified(openid="same-openid-b", unionid="same-unionid"),
        }
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda credential: _exchange(
                    provider=provider,
                    credential=credential,
                    device_id=f"pg-wechat-race-{uuid4()}",
                ),
                ("same-unionid-a", "same-unionid-b"),
            )
        )
    assert all(result[0] == "ok" for result in results), results
    request_ids.update(result[2] for result in results)
    with SessionLocal() as db:
        identities = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.WECHAT,
                    AuthIdentity.subject.in_(
                        {
                            "unionid:pg-wechat-scope:same-unionid",
                            "openid:pg-wechat-app:same-openid-a",
                            "openid:pg-wechat-app:same-openid-b",
                        }
                    ),
                )
            )
        )
        assert len({identity.user_id for identity in identities}) == 1
        assert len(identities) == 3
        user_ids.add(identities[0].user_id)
    assert sorted(provider.calls) == ["same-unionid-a", "same-unionid-b"]


def _prove_alias_conflict(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    provider = FakeProvider(
        {"alias-conflict": _verified(openid="conflict-openid", unionid="conflict-unionid")}
    )
    with SessionLocal() as db:
        owner_a, owner_b = User(nickname="pg-wechat-owner-a"), User(nickname="pg-wechat-owner-b")
        db.add_all((owner_a, owner_b))
        db.flush()
        db.add_all(
            (
                AuthIdentity(
                    user_id=owner_a.id,
                    provider=AuthProvider.WECHAT,
                    subject="openid:pg-wechat-app:conflict-openid",
                    verified_at=datetime.now(UTC),
                ),
                AuthIdentity(
                    user_id=owner_b.id,
                    provider=AuthProvider.WECHAT,
                    subject="unionid:pg-wechat-scope:conflict-unionid",
                    verified_at=datetime.now(UTC),
                ),
            )
        )
        db.commit()
        user_ids.update((owner_a.id, owner_b.id))
    result = _exchange(
        provider=provider, credential="alias-conflict", device_id=f"pg-conflict-{uuid4()}"
    )
    request_ids.add(result[2])
    assert result[0] == "AUTH_IDENTITY_CONFLICT", result
    assert provider.calls == ["alias-conflict"]


def _prove_disabled_and_deletion(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    provider = FakeProvider(
        {
            "disabled": _verified(openid="disabled-openid", unionid="disabled-unionid"),
            "deletion": _verified(openid="deletion-openid", unionid="deletion-unionid"),
        }
    )
    with SessionLocal() as db:
        disabled = User(nickname="pg-wechat-disabled", auth_disabled_at=datetime.now(UTC))
        deleting = User(nickname="pg-wechat-deleting")
        db.add_all((disabled, deleting))
        db.flush()
        db.add_all(
            (
                AuthIdentity(
                    user_id=disabled.id,
                    provider=AuthProvider.WECHAT,
                    subject="unionid:pg-wechat-scope:disabled-unionid",
                    verified_at=datetime.now(UTC),
                ),
                AuthIdentity(
                    user_id=deleting.id,
                    provider=AuthProvider.WECHAT,
                    subject="unionid:pg-wechat-scope:deletion-unionid",
                    verified_at=datetime.now(UTC),
                ),
                AccountDeletionOperation(
                    user_id=deleting.id,
                    request_id=uuid4(),
                    data_deletion_request_id=uuid4(),
                ),
            )
        )
        db.commit()
        user_ids.update((disabled.id, deleting.id))
    disabled_result = _exchange(
        provider=provider, credential="disabled", device_id=f"pg-disabled-{uuid4()}"
    )
    deleting_result = _exchange(
        provider=provider, credential="deletion", device_id=f"pg-deletion-{uuid4()}"
    )
    request_ids.update((disabled_result[2], deleting_result[2]))
    assert disabled_result[0] == "AUTH_ACCOUNT_UNAVAILABLE", disabled_result
    assert deleting_result[0] == "ok", deleting_result
    assert deleting_result[1].account_deletion_in_progress is True
    user_ids.add(deleting_result[1].tokens.user_id)


def _prove_response_loss_recovery(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    provider = FakeProvider(
        {"recovery": _verified(openid="recovery-openid", unionid="recovery-unionid")}
    )
    device_id = f"pg-recovery-{uuid4()}"
    first = _exchange(provider=provider, credential="recovery", device_id=device_id)
    request_ids.add(first[2])
    assert first[0] == "ok", first
    user_ids.add(first[1].tokens.user_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        recovered = list(
            executor.map(
                lambda _: _exchange(
                    provider=provider,
                    credential="recovery",
                    device_id=device_id,
                    request_id=first[2],
                ),
                range(2),
            )
        )
    request_ids.update(result[2] for result in recovered)
    assert sorted(result[0] for result in recovered) == [
        "AUTH_WECHAT_CREDENTIAL_REPLAYED",
        "ok",
    ], recovered
    assert provider.calls == ["recovery"]
    with SessionLocal() as db:
        row = db.scalar(
            select(WechatLoginExchange).where(WechatLoginExchange.request_id == first[2])
        )
        assert row is not None and row.recovery_count == 1
        assert row.replacement_session_id is not None
        assert (
            db.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == first[1].tokens.user_id,
                    AuthSession.device_id == device_id,
                    AuthSession.revoked_at.is_(None),
                )
            )
            == 1
        )


def _prove_session_rollback(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    provider = FakeProvider(
        {"rollback": _verified(openid="rollback-openid", unionid="rollback-unionid")}
    )
    original = wechat_login_service.issue_authenticated_session_in_transaction

    def fail_session(*args, **kwargs):
        raise PublicAuthError("AUTH_SESSION_ISSUE_FAILED", 503)

    wechat_login_service.issue_authenticated_session_in_transaction = fail_session
    try:
        result = _exchange(
            provider=provider, credential="rollback", device_id=f"pg-rollback-{uuid4()}"
        )
    finally:
        wechat_login_service.issue_authenticated_session_in_transaction = original
    request_ids.add(result[2])
    assert result[0] == "AUTH_SESSION_ISSUE_FAILED", result
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.WECHAT,
                    AuthIdentity.subject == "unionid:pg-wechat-scope:rollback-unionid",
                )
            )
            is None
        )
        assert (
            db.scalar(
                select(WechatLoginExchange).where(
                    WechatLoginExchange.request_id == result[2],
                    WechatLoginExchange.error_code == "AUTH_SESSION_ISSUE_FAILED",
                )
            )
            is not None
        )


def main() -> None:
    _require_real_postgresql()
    request_ids: set[UUID] = set()
    user_ids: set[UUID] = set()
    try:
        _prove_same_identity_concurrency(request_ids, user_ids)
        _prove_alias_conflict(request_ids, user_ids)
        _prove_disabled_and_deletion(request_ids, user_ids)
        _prove_response_loss_recovery(request_ids, user_ids)
        _prove_session_rollback(request_ids, user_ids)
    finally:
        _cleanup(request_ids=request_ids, user_ids=user_ids)
    print("PostgreSQL AUTH-04 WeChat login authority PASS")


if __name__ == "__main__":
    main()
