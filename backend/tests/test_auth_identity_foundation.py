from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.account_deletion_models import AccountDeletionOperation
from app.api import auth as auth_api
from app.auth_models import AuthIdentity, AuthProvider
from app.core.db import SessionLocal, create_schema
from app.models import User
from app.services.auth_identity_preflight import run_auth_identity_preflight
from app.services.auth_identity_service import (
    AuthIdentityError,
    canonicalize_email_subject,
    canonicalize_phone_subject,
    canonicalize_wechat_subject,
    create_user_for_verified_identity,
    issue_authenticated_session,
    link_verified_identity,
    link_verified_wechat_aliases,
    resolve_auth_identity,
)
from app.services.auth_session_service import PublicAuthError

create_schema()


def test_subject_canonicalization_is_provider_specific():
    assert canonicalize_email_subject("  USER@Example.COM ") == "user@example.com"
    assert canonicalize_phone_subject("+8613812345678") == "+8613812345678"
    assert canonicalize_wechat_subject("openid:wx-app:O1") == "openid:wx-app:O1"
    assert canonicalize_wechat_subject("unionid:wx-group:U1") == "unionid:wx-group:U1"

    with pytest.raises(AuthIdentityError, match="AUTH_PHONE_SUBJECT_NOT_CANONICAL"):
        canonicalize_phone_subject("13812345678")
    with pytest.raises(AuthIdentityError, match="AUTH_WECHAT_SUBJECT_INVALID"):
        canonicalize_wechat_subject("bare-openid")


def test_verified_phone_creation_and_wechat_aliases_share_user():
    with SessionLocal() as db:
        phone = create_user_for_verified_identity(
            db,
            provider=AuthProvider.PHONE,
            subject="+8613812345678",
            verified_at=datetime.now(UTC),
        )
        db.commit()
        user = db.get(User, phone.user_id)
        assert user is not None
        assert user.phone == "+8613812345678"

        link_verified_wechat_aliases(
            db,
            user_id=user.id,
            aliases=("openid:wx-app:O1", "unionid:wx-group:U1"),
            verified_at=datetime.now(UTC),
        )
        aliases = list(
            db.scalars(
                select(AuthIdentity).where(
                    AuthIdentity.user_id == user.id,
                    AuthIdentity.provider == AuthProvider.WECHAT,
                )
            )
        )
        assert {identity.subject for identity in aliases} == {
            "openid:wx-app:O1",
            "unionid:wx-group:U1",
        }


def test_identity_resolver_never_falls_back_to_user_projection():
    with SessionLocal() as db:
        user = User(email="projection-only@example.com", nickname="Projection")
        db.add(user)
        db.commit()

        assert (
            resolve_auth_identity(
                db,
                provider=AuthProvider.EMAIL_PASSWORD,
                subject="projection-only@example.com",
            )
            is None
        )


def test_email_duplicate_same_user_has_database_guard():
    with SessionLocal() as db:
        user = User(nickname="cardinality")
        db.add(user)
        db.flush()
        db.add_all(
            [
                AuthIdentity(
                    user_id=user.id,
                    provider=AuthProvider.EMAIL_PASSWORD,
                    subject=f"cardinality-{user.id}@example.com",
                    secret_hash="hash-1",
                ),
                AuthIdentity(
                    user_id=user.id,
                    provider=AuthProvider.EMAIL_PASSWORD,
                    subject=f"cardinality-2-{user.id}@example.com",
                    secret_hash="hash-2",
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_phone_duplicate_same_user_has_database_guard():
    with SessionLocal() as db:
        user = User(nickname="phone-cardinality")
        db.add(user)
        db.flush()
        db.add_all(
            [
                AuthIdentity(
                    user_id=user.id,
                    provider=AuthProvider.PHONE,
                    subject="+8613800000001",
                    verified_at=datetime.now(UTC),
                ),
                AuthIdentity(
                    user_id=user.id,
                    provider=AuthProvider.PHONE,
                    subject="+8613800000002",
                    verified_at=datetime.now(UTC),
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_wechat_multiple_aliases_same_user_are_allowed():
    with SessionLocal() as db:
        user = User(nickname="wechat-cardinality")
        db.add(user)
        db.flush()
        db.add_all(
            [
                AuthIdentity(
                    user_id=user.id,
                    provider=AuthProvider.WECHAT,
                    subject="openid:cardinality-app:O1",
                    verified_at=datetime.now(UTC),
                ),
                AuthIdentity(
                    user_id=user.id,
                    provider=AuthProvider.WECHAT,
                    subject="unionid:cardinality-group:U1",
                    verified_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()


def test_identity_material_invariants_are_enforced():
    invalid_cases = (
        {
            "provider": AuthProvider.PHONE,
            "subject": "+8613800000011",
            "secret_hash": None,
            "verified_at": None,
            "code": "AUTH_IDENTITY_NOT_VERIFIED",
        },
        {
            "provider": AuthProvider.PHONE,
            "subject": "+8613800000012",
            "secret_hash": "not-for-phone",
            "verified_at": datetime.now(UTC),
            "code": "AUTH_IDENTITY_SECRET_NOT_ALLOWED",
        },
        {
            "provider": AuthProvider.WECHAT,
            "subject": "openid:invariant-app:O1",
            "secret_hash": "not-for-wechat",
            "verified_at": datetime.now(UTC),
            "code": "AUTH_IDENTITY_SECRET_NOT_ALLOWED",
        },
        {
            "provider": AuthProvider.EMAIL_PASSWORD,
            "subject": "missing-secret@example.com",
            "secret_hash": None,
            "verified_at": None,
            "code": "AUTH_IDENTITY_SECRET_REQUIRED",
        },
    )
    with SessionLocal() as db:
        for case in invalid_cases:
            with pytest.raises(AuthIdentityError, match=case["code"]):
                create_user_for_verified_identity(
                    db,
                    provider=case["provider"],
                    subject=case["subject"],
                    secret_hash=case["secret_hash"],
                    verified_at=case["verified_at"],
                    nickname="invalid",
                )
            db.rollback()


def test_link_rejects_existing_unverified_external_identity():
    with SessionLocal() as db:
        user = User(nickname="unverified-external")
        db.add(user)
        db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.PHONE,
                subject="+8613800000021",
                verified_at=None,
            )
        )
        db.commit()
        with pytest.raises(AuthIdentityError, match="AUTH_IDENTITY_NOT_VERIFIED"):
            link_verified_identity(
                db,
                user_id=user.id,
                provider=AuthProvider.PHONE,
                subject="+8613800000021",
                verified_at=datetime.now(UTC),
            )
        db.rollback()


def test_resolver_fails_closed_for_unverified_external_identity():
    with SessionLocal() as db:
        user = User(nickname="resolver-unverified-external")
        db.add(user)
        db.flush()
        db.add(
            AuthIdentity(
                user_id=user.id,
                provider=AuthProvider.WECHAT,
                subject="openid:resolver-app:O1",
                verified_at=None,
            )
        )
        db.commit()
        with pytest.raises(AuthIdentityError, match="AUTH_IDENTITY_NOT_VERIFIED"):
            resolve_auth_identity(
                db,
                provider=AuthProvider.WECHAT,
                subject="openid:resolver-app:O1",
            )


def test_wechat_alias_binding_is_atomic_on_cross_user_conflict():
    with SessionLocal() as db:
        owner = create_user_for_verified_identity(
            db,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject="wechat-alias-owner@example.com",
            secret_hash="owner-hash",
        )
        db.commit()
        other = create_user_for_verified_identity(
            db,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject="wechat-alias-other@example.com",
            secret_hash="other-hash",
        )
        db.commit()
        link_verified_identity(
            db,
            user_id=other.user_id,
            provider=AuthProvider.WECHAT,
            subject="unionid:atomic-group:U1",
            verified_at=datetime.now(UTC),
        )

        with pytest.raises(AuthIdentityError, match="AUTH_IDENTITY_CONFLICT"):
            link_verified_wechat_aliases(
                db,
                user_id=owner.user_id,
                aliases=("openid:atomic-app:O1", "unionid:atomic-group:U1"),
                verified_at=datetime.now(UTC),
            )
        assert db.scalar(
            select(AuthIdentity.id).where(
                AuthIdentity.user_id == owner.user_id,
                AuthIdentity.subject == "openid:atomic-app:O1",
            )
        ) is None


def test_identity_conflict_is_fail_closed():
    with SessionLocal() as db:
        first = create_user_for_verified_identity(
            db,
            provider=AuthProvider.PHONE,
            subject="+8613812345678",
            verified_at=datetime.now(UTC),
        )
        db.commit()
        second = create_user_for_verified_identity(
            db,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject="second@example.com",
            secret_hash="second-hash",
            verified_at=datetime.now(UTC),
        )
        db.commit()

        with pytest.raises(AuthIdentityError, match="AUTH_IDENTITY_CONFLICT"):
            link_verified_identity(
                db,
                user_id=second.user_id,
                provider=AuthProvider.PHONE,
                subject="+8613812345678",
                verified_at=datetime.now(UTC),
            )
        assert first.user_id != second.user_id


def test_auth_disabled_is_hard_deny_and_deletion_issues_continuation():
    with SessionLocal() as db:
        created = create_user_for_verified_identity(
            db,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject="session-boundary@example.com",
            secret_hash="session-boundary-hash",
            verified_at=datetime.now(UTC),
        )
        db.commit()
        user = db.get(User, created.user_id)
        assert user is not None
        user.auth_disabled_at = datetime.now(UTC)
        db.commit()

        with pytest.raises(PublicAuthError, match="AUTH_ACCOUNT_UNAVAILABLE"):
            issue_authenticated_session(
                db,
                user_id=user.id,
                device_id="test",
            )

        user.auth_disabled_at = None
        db.add(
            AccountDeletionOperation(
                user_id=user.id,
                request_id=uuid4(),
                data_deletion_request_id=uuid4(),
            )
        )
        db.commit()
        issued = issue_authenticated_session(
            db,
            user_id=user.id,
            device_id="deletion-continuation",
        )
        assert issued.account_deletion_in_progress is True


def test_link_is_denied_during_account_deletion():
    with SessionLocal() as db:
        created = create_user_for_verified_identity(
            db,
            provider=AuthProvider.EMAIL_PASSWORD,
            subject="deleting-link@example.com",
            secret_hash="deleting-link-hash",
            verified_at=datetime.now(UTC),
        )
        db.commit()
        db.add(
            AccountDeletionOperation(
                user_id=created.user_id,
                request_id=uuid4(),
                data_deletion_request_id=uuid4(),
            )
        )
        db.commit()
        with pytest.raises(AuthIdentityError, match="ACCOUNT_DELETION_IN_PROGRESS"):
            link_verified_identity(
                db,
                user_id=created.user_id,
                provider=AuthProvider.PHONE,
                subject="+8613812345678",
                verified_at=datetime.now(UTC),
            )


def test_identity_preflight_is_read_only_and_reports_inventory():
    with SessionLocal() as db:
        before = db.scalar(select(User.id).order_by(User.id).limit(1))
        report = run_auth_identity_preflight(db)
        after = db.scalar(select(User.id).order_by(User.id).limit(1))
        assert before == after
        assert report.orphan_identity_count >= 0
        assert report.orphan_session_count >= 0
        assert report.active_account_deletion_count >= 0


@pytest.mark.asyncio
async def test_email_login_uses_shared_session_issuance(client, auth_email_delivery, monkeypatch):
    register = await client.post(
        "/v1/auth/register",
        json={
            "email": "shared-login@example.com",
            "password": "correct-horse-battery-staple",
            "nickname": "Shared Login",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )
    assert register.status_code == 201
    email, token = auth_email_delivery.verification_tokens[-1]
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": token, "device_id": "verify-first"},
    )
    assert verified.status_code == 200
    calls = []
    real_issue = auth_api.issue_authenticated_session

    def spy(*args, **kwargs):
        calls.append(kwargs["user_id"])
        return real_issue(*args, **kwargs)

    monkeypatch.setattr(auth_api, "issue_authenticated_session", spy)
    login = await client.post(
        "/v1/auth/login",
        json={
            "email": email,
            "password": "correct-horse-battery-staple",
            "device_id": "shared-login",
        },
    )
    assert login.status_code == 200
    assert [str(user_id) for user_id in calls] == [login.json()["user_id"]]


@pytest.mark.asyncio
async def test_email_verification_uses_shared_session_issuance(
    client,
    auth_email_delivery,
    monkeypatch,
):
    register = await client.post(
        "/v1/auth/register",
        json={
            "email": "shared-verify@example.com",
            "password": "correct-horse-battery-staple",
            "nickname": "Shared Verify",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
        },
    )
    assert register.status_code == 201
    _, token = auth_email_delivery.verification_tokens[-1]
    calls = []
    real_issue = auth_api.issue_authenticated_session

    def spy(*args, **kwargs):
        calls.append(kwargs["user_id"])
        return real_issue(*args, **kwargs)

    monkeypatch.setattr(auth_api, "issue_authenticated_session", spy)
    verified = await client.post(
        "/v1/auth/verify-email",
        json={"token": token, "device_id": "shared-verify"},
    )
    assert verified.status_code == 200
    assert [str(user_id) for user_id in calls] == [verified.json()["session"]["user_id"]]
