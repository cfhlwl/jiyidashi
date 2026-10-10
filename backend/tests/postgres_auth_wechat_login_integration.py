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
from app.entitlement_models import UserEntitlement
from app.models import User
from app.services import wechat_login_service
from app.services.auth_identity_service import create_user_for_verified_identity
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

    def __init__(
        self,
        outcomes: dict[str, VerifiedWechatResult],
        *,
        contested_window: threading.Barrier | None = None,
    ):
        self.outcomes = outcomes
        self.contested_window = contested_window
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def exchange_credential(self, *, credential: str, request_id: UUID):
        with self._lock:
            self.calls.append(credential)
        with SessionLocal() as db:
            assert db.in_transaction() is False
        if self.contested_window is not None:
            self.contested_window.wait(timeout=30)
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
    contested_window = threading.Barrier(2)
    provider = FakeProvider(
        {
            "same-unionid-a": _verified(openid="same-openid-a", unionid="same-unionid"),
            "same-unionid-b": _verified(openid="same-openid-b", unionid="same-unionid"),
        },
        contested_window=contested_window,
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
    assert all(result[0] in {"ok", "AUTH_IDENTITY_CONFLICT"} for result in results), results
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
        assert len(identities) in {2, 3}
        user_ids.add(identities[0].user_id)
        receipts = list(
            db.scalars(
                select(WechatLoginExchange).where(
                    WechatLoginExchange.request_id.in_(request_ids)
                )
            )
        )
        assert all(str(receipt.state) != "RESERVED" for receipt in receipts)
        assert all(
            str(receipt.state) in {"COMPLETED", "PROVIDER_REJECTED"}
            for receipt in receipts
        )
        assert sum(
            1
            for result in results
            if result[0] == "ok"
        ) == db.scalar(
            select(func.count(AuthSession.id)).where(
                AuthSession.user_id == identities[0].user_id,
                AuthSession.revoked_at.is_(None),
            )
        )
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
    with SessionLocal() as db:
        receipt = db.scalar(
            select(WechatLoginExchange).where(WechatLoginExchange.request_id == result[2])
        )
        assert receipt is not None
        assert str(receipt.state) == "PROVIDER_REJECTED"
        assert receipt.error_code == "AUTH_IDENTITY_CONFLICT"


def _prove_shared_openid_unique_constraint_race(
    request_ids: set[UUID], user_ids: set[UUID]
) -> None:
    """Prove PostgreSQL rejects one concurrent cross-owner alias bind.

    The resolver replacement is deliberately test-only. It stops after each
    request has queried its pre-existing unionid owner, then both sessions add
    the same openid and flush against the real PostgreSQL unique constraint.
    No IntegrityError is manufactured or caught by the test itself.
    """

    credentials = ("shared-openid-owner-a", "shared-openid-owner-b")
    devices = {
        credentials[0]: f"pg-wechat-shared-openid-a-{uuid4()}",
        credentials[1]: f"pg-wechat-shared-openid-b-{uuid4()}",
    }
    unionids = {
        credentials[0]: "shared-openid-unionid-a",
        credentials[1]: "shared-openid-unionid-b",
    }
    shared_openid_subject = "openid:pg-wechat-app:shared-openid"
    union_subjects = {
        credential: f"unionid:pg-wechat-scope:{unionid}"
        for credential, unionid in unionids.items()
    }

    with SessionLocal() as db:
        owner_a = create_user_for_verified_identity(
            db,
            provider=AuthProvider.WECHAT,
            subject=union_subjects[credentials[0]],
            verified_at=datetime.now(UTC),
            nickname="pg-wechat-shared-openid-owner-a",
        )
        owner_b = create_user_for_verified_identity(
            db,
            provider=AuthProvider.WECHAT,
            subject=union_subjects[credentials[1]],
            verified_at=datetime.now(UTC),
            nickname="pg-wechat-shared-openid-owner-b",
        )
        db.commit()
        owner_ids = {owner_a.user_id, owner_b.user_id}
        user_ids.update(owner_ids)
        setup_user_count = db.scalar(select(func.count(User.id)))
        setup_entitlement_count = db.scalar(select(func.count(UserEntitlement.user_id)))
        setup_session_count = db.scalar(select(func.count(AuthSession.id)))

    owner_by_credential = {
        credentials[0]: owner_a.user_id,
        credentials[1]: owner_b.user_id,
    }
    resolver_barrier = threading.Barrier(2)
    provider = FakeProvider(
        {
            credentials[0]: _verified(openid="shared-openid", unionid=unionids[credentials[0]]),
            credentials[1]: _verified(openid="shared-openid", unionid=unionids[credentials[1]]),
        }
    )
    original_resolver = wechat_login_service._resolve_verified_identity

    def contested_resolver(db, *, result):
        subjects = result.canonical_subjects()
        union_subject = next(subject for subject in subjects if subject.startswith("unionid:"))
        openid_subject = next(subject for subject in subjects if subject.startswith("openid:"))
        owner_identity = db.scalar(
            select(AuthIdentity)
            .where(
                AuthIdentity.provider == AuthProvider.WECHAT,
                AuthIdentity.subject == union_subject,
            )
            .with_for_update()
        )
        assert owner_identity is not None
        expected_owner_id = owner_by_credential[
            credentials[0] if result.unionid == unionids[credentials[0]] else credentials[1]
        ]
        assert owner_identity.user_id == expected_owner_id

        # Both sessions have completed the owner query and are now ready to
        # compete on the same durable (provider, subject) unique key.
        resolver_barrier.wait(timeout=30)
        db.add(
            AuthIdentity(
                user_id=owner_identity.user_id,
                provider=AuthProvider.WECHAT,
                subject=openid_subject,
                verified_at=result.verified_at,
            )
        )
        db.flush()
        return owner_identity.user_id, union_subject

    wechat_login_service._resolve_verified_identity = contested_resolver
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda credential: _exchange(
                        provider=provider,
                        credential=credential,
                        device_id=devices[credential],
                    ),
                    credentials,
                )
            )
    finally:
        wechat_login_service._resolve_verified_identity = original_resolver

    request_ids.update(result[2] for result in results)
    result_by_credential = {
        credential: result for credential, result in zip(credentials, results, strict=True)
    }
    assert sorted(result[0] for result in results) == ["AUTH_IDENTITY_CONFLICT", "ok"], results
    assert len(provider.calls) == 2

    loser_credential = next(
        credential
        for credential, result in result_by_credential.items()
        if result[0] == "AUTH_IDENTITY_CONFLICT"
    )
    loser_request_id = result_by_credential[loser_credential][2]
    replay = _exchange(
        provider=provider,
        credential=loser_credential,
        device_id=devices[loser_credential],
        request_id=loser_request_id,
    )
    assert replay[0] == "AUTH_IDENTITY_CONFLICT", replay
    assert len(provider.calls) == 2

    with SessionLocal() as db:
        identity_rows = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.provider == AuthProvider.WECHAT,
                    AuthIdentity.subject.in_(
                        {shared_openid_subject, *union_subjects.values()}
                    ),
                )
            )
        )
        identities_by_subject = {identity.subject: identity for identity in identity_rows}
        assert identities_by_subject[union_subjects[credentials[0]]].user_id == owner_a.user_id
        assert identities_by_subject[union_subjects[credentials[1]]].user_id == owner_b.user_id
        assert identities_by_subject[shared_openid_subject].user_id in owner_ids
        assert sum(identity.subject == shared_openid_subject for identity in identity_rows) == 1
        assert {identity.user_id for identity in identity_rows} == owner_ids

        users = list(db.scalars(select(User).where(User.id.in_(owner_ids))))
        assert {user.id for user in users} == owner_ids
        assert {user.nickname for user in users} == {
            "pg-wechat-shared-openid-owner-a",
            "pg-wechat-shared-openid-owner-b",
        }
        assert db.scalar(select(func.count(User.id))) == setup_user_count
        assert (
            db.scalar(
                select(func.count(UserEntitlement.user_id)).where(
                    UserEntitlement.user_id.in_(owner_ids)
                )
            )
            == 2
        )
        assert db.scalar(select(func.count(UserEntitlement.user_id))) == setup_entitlement_count

        receipts = list(
            db.scalars(
                select(WechatLoginExchange).where(
                    WechatLoginExchange.request_id.in_(
                        {result[2] for result in results}
                    )
                )
            )
        )
        receipt_by_request = {receipt.request_id: receipt for receipt in receipts}
        assert len(receipt_by_request) == 2
        assert str(receipt_by_request[loser_request_id].state) == "PROVIDER_REJECTED"
        assert receipt_by_request[loser_request_id].error_code == "AUTH_IDENTITY_CONFLICT"
        assert all(str(receipt.state) != "RESERVED" for receipt in receipts)

        successful = next(result for result in results if result[0] == "ok")
        active_sessions = list(
            db.scalars(
                select(AuthSession).where(
                    AuthSession.user_id.in_(owner_ids),
                    AuthSession.device_id.in_(set(devices.values())),
                    AuthSession.revoked_at.is_(None),
                )
            )
        )
        assert len(active_sessions) == 1
        assert active_sessions[0].user_id == successful[1].tokens.user_id
        assert active_sessions[0].device_id == successful[1].device_id
        assert db.scalar(select(func.count(AuthSession.id))) == setup_session_count + 1


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


def _prove_completed_replay_is_rejected(request_ids: set[UUID], user_ids: set[UUID]) -> None:
    provider = FakeProvider(
        {"completed-replay": _verified(openid="replay-openid", unionid="replay-unionid")}
    )
    device_id = f"pg-replay-{uuid4()}"
    first = _exchange(provider=provider, credential="completed-replay", device_id=device_id)
    request_ids.add(first[2])
    assert first[0] == "ok", first
    user_ids.add(first[1].tokens.user_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        replayed = list(
            executor.map(
                lambda _: _exchange(
                    provider=provider,
                    credential="completed-replay",
                    device_id=device_id,
                    request_id=first[2],
                ),
                range(2),
            )
        )
    request_ids.update(result[2] for result in replayed)
    assert all(
        result[0] == "AUTH_WECHAT_CREDENTIAL_REPLAYED" for result in replayed
    ), replayed
    assert provider.calls == ["completed-replay"]
    with SessionLocal() as db:
        row = db.scalar(
            select(WechatLoginExchange).where(WechatLoginExchange.request_id == first[2])
        )
        assert row is not None
        assert str(row.state) == "COMPLETED"
        assert row.recovery_count == 0
        assert row.replacement_session_id is None
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
        _prove_shared_openid_unique_constraint_race(request_ids, user_ids)
        _prove_disabled_and_deletion(request_ids, user_ids)
        _prove_completed_replay_is_rejected(request_ids, user_ids)
        _prove_session_rollback(request_ids, user_ids)
    finally:
        _cleanup(request_ids=request_ids, user_ids=user_ids)
    print("PostgreSQL AUTH-04 WeChat login authority PASS")


if __name__ == "__main__":
    main()
