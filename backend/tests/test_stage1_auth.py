import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.auth_models import AuthIdentity, AuthProvider
from app.core.db import SessionLocal
from app.entitlement_models import PlanCode, UserEntitlement
from app.models import User
from app.services import auth_service
from app.services.auth_delivery import MemoryAuthEmailDelivery


async def _register(
    client: AsyncClient,
    *,
    email: str,
    password: str = "correct-horse-battery-staple",
    nickname: str = "Stage1 User",
    timezone: str = "Asia/Shanghai",
):
    return await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "nickname": nickname,
            "timezone": timezone,
            "locale": "zh-CN",
        },
    )


async def _register_verified(
    client: AsyncClient,
    delivery: MemoryAuthEmailDelivery,
    *,
    email: str,
    password: str = "correct-horse-battery-staple",
    nickname: str = "Stage1 User",
    timezone: str = "Asia/Shanghai",
):
    register = await _register(
        client,
        email=email,
        password=password,
        nickname=nickname,
        timezone=timezone,
    )
    assert register.status_code == 201
    assert delivery.verification_tokens
    delivered_email, token = delivery.verification_tokens[-1]
    assert delivered_email == email.strip().casefold()
    verified = await client.post(
        "/v1/auth/verify-email",
        json={
            "token": token,
            "device_id": "stage1-test-device",
            "client_platform": "test",
        },
    )
    assert verified.status_code == 200
    session = verified.json()["session"]
    assert session is not None
    return register, session


async def _elder_dev_user(client: AsyncClient, nickname: str):
    response = await client.post(
        "/v1/auth/dev-token",
        json={"nickname": nickname},
    )
    assert response.status_code == 200
    return response


def _registration_state(email: str) -> tuple[int, int, int, str | None]:
    subject = email.strip().casefold()
    with SessionLocal() as db:
        users = list(db.scalars(select(User).where(User.email == subject)))
        identities = int(
            db.scalar(
                select(func.count(AuthIdentity.id)).where(
                    AuthIdentity.provider == AuthProvider.EMAIL_PASSWORD,
                    AuthIdentity.subject == subject,
                )
            )
            or 0
        )
        entitlements = 0
        plan_code = None
        if users:
            entitlements = int(
                db.scalar(
                    select(func.count(UserEntitlement.user_id)).where(
                        UserEntitlement.user_id == users[0].id
                    )
                )
                or 0
            )
            row = db.get(UserEntitlement, users[0].id)
            plan_code = None if row is None else row.plan_code
        return len(users), identities, entitlements, plan_code


async def test_register_login_and_update_profile(
    client: AsyncClient,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    register, session = await _register_verified(
        client,
        auth_email_delivery,
        email="stage1-auth@example.com",
    )
    body = register.json()
    headers = {"Authorization": f"Bearer {session['access_token']}"}

    me = await client.get("/v1/user", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "stage1-auth@example.com"
    assert me.json()["timezone"] == "Asia/Shanghai"
    assert me.json()["elder_mode_enabled"] is False

    update = await client.patch(
        "/v1/user",
        headers=headers,
        json={"nickname": "记忆用户", "timezone": "Asia/Singapore"},
    )
    assert update.status_code == 200
    assert update.json()["nickname"] == "记忆用户"
    assert update.json()["timezone"] == "Asia/Singapore"

    login = await client.post(
        "/v1/auth/login",
        json={
            "email": " STAGE1-AUTH@EXAMPLE.COM ",
            "password": "correct-horse-battery-staple",
        },
    )
    assert login.status_code == 200
    assert login.json()["user_id"] == body["user_id"]


async def test_duplicate_registration_and_wrong_password_are_safe(client: AsyncClient):
    email = "stage1-duplicate@example.com"
    first = await _register(client, email=email)
    assert first.status_code == 201
    assert _registration_state(email) == (1, 1, 1, PlanCode.FREE.value)

    duplicate = await _register(client, email="STAGE1-DUPLICATE@example.com")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "AUTH_IDENTITY_EXISTS"
    assert _registration_state(email) == (1, 1, 1, PlanCode.FREE.value)

    wrong = await client.post(
        "/v1/auth/login",
        json={
            "email": "stage1-duplicate@example.com",
            "password": "definitely-wrong",
        },
    )
    missing = await client.post(
        "/v1/auth/login",
        json={
            "email": "missing-stage1@example.com",
            "password": "definitely-wrong",
        },
    )
    assert wrong.status_code == 401
    assert missing.status_code == 401
    assert wrong.json()["detail"] == "INVALID_CREDENTIALS"
    assert missing.json()["detail"] == "INVALID_CREDENTIALS"


async def test_registration_failure_rolls_back_user_identity_and_entitlement(
    client: AsyncClient,
    monkeypatch,
):
    email = "stage1-registration-rollback@example.com"
    real_create = auth_service.create_registration_default_entitlement

    def fail_after_entitlement_added(db, *, user_id, now=None):
        real_create(db, user_id=user_id, now=now)
        raise RuntimeError("BIZ011_TEST_REGISTRATION_FAILURE")

    monkeypatch.setattr(
        auth_service,
        "create_registration_default_entitlement",
        fail_after_entitlement_added,
    )

    with pytest.raises(RuntimeError, match="BIZ011_TEST_REGISTRATION_FAILURE"):
        await _register(client, email=email)

    assert _registration_state(email) == (0, 0, 0, None)


async def test_missing_account_still_executes_dummy_argon2_verify(
    client: AsyncClient,
    monkeypatch,
):
    calls: list[str] = []

    class SpyHasher:
        def verify(self, encoded: str, password: str) -> bool:
            calls.append(encoded)
            return False

    # [人工注释][S1-FIX-004] 不存在账号必须实际走一次 dummy Argon2 verify，而不是直接快速返回。
    monkeypatch.setattr(auth_service, "_password_hasher", SpyHasher())
    response = await client.post(
        "/v1/auth/login",
        json={
            "email": "missing-dummy-stage1@example.com",
            "password": "definitely-wrong",
        },
    )
    assert response.status_code == 401
    assert calls == [auth_service._DUMMY_ARGON2_HASH]


async def test_login_failure_backoff_returns_429(client: AsyncClient):
    register = await _register(client, email="stage1-backoff@example.com")
    assert register.status_code == 201

    for _ in range(3):
        response = await client.post(
            "/v1/auth/login",
            json={
                "email": "stage1-backoff@example.com",
                "password": "wrong-password",
            },
        )
        assert response.status_code == 401

    # [人工注释][S1-FIX-003] 同 IP + 同账号连续失败后必须短期退避，并以 429 + Retry-After 明确拒绝。
    blocked = await client.post(
        "/v1/auth/login",
        json={
            "email": "stage1-backoff@example.com",
            "password": "wrong-password",
        },
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "AUTH_RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) >= 1


async def test_register_rejects_client_owned_user_id_and_invalid_timezone(client: AsyncClient):
    # [人工注释][S1-001] 公共注册入口不允许客户端选择用户主键。
    chosen_id = await client.post(
        "/v1/auth/register",
        json={
            "email": "stage1-owned-id@example.com",
            "password": "correct-horse-battery-staple",
            "nickname": "Bad Input",
            "timezone": "Asia/Shanghai",
            "locale": "zh-CN",
            "user_id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert chosen_id.status_code == 422

    bad_timezone = await _register(
        client,
        email="stage1-bad-timezone@example.com",
        timezone="Mars/Olympus",
    )
    assert bad_timezone.status_code == 422


async def test_profile_rejects_invalid_timezone(
    client: AsyncClient,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    _, session = await _register_verified(
        client,
        auth_email_delivery,
        email="stage1-profile-timezone@example.com",
    )
    headers = {"Authorization": f"Bearer {session['access_token']}"}

    response = await client.patch(
        "/v1/user",
        headers=headers,
        json={"timezone": "UTC+8-not-iana"},
    )
    assert response.status_code == 422

    current = await client.get("/v1/user", headers=headers)
    assert current.status_code == 200
    assert current.json()["timezone"] == "Asia/Shanghai"


async def test_profile_and_registration_reject_whitespace_only_text(
    client: AsyncClient,
    auth_email_delivery: MemoryAuthEmailDelivery,
):
    bad_register = await _register(
        client,
        email="stage1-whitespace-register@example.com",
        nickname="   ",
    )
    assert bad_register.status_code == 422

    _, session = await _register_verified(
        client,
        auth_email_delivery,
        email="stage1-whitespace-profile@example.com",
    )
    headers = {"Authorization": f"Bearer {session['access_token']}"}

    # [人工注释][S1-FIX-005] nickname / locale 必须在 strip 后再校验，禁止把纯空白持久化为空字符串。
    nickname = await client.patch(
        "/v1/user",
        headers=headers,
        json={"nickname": "   "},
    )
    locale = await client.patch(
        "/v1/user",
        headers=headers,
        json={"locale": "   "},
    )
    assert nickname.status_code == 422
    assert locale.status_code == 422



async def test_elder_mode_is_self_controlled_persisted_and_patch_is_partial(client: AsyncClient):
    first = await _elder_dev_user(client, "本人")
    second = await _elder_dev_user(client, "其他人")
    first_headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
    second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}

    enabled = await client.patch(
        "/v1/user",
        headers=first_headers,
        json={"elder_mode_enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json()["elder_mode_enabled"] is True
    assert enabled.json()["nickname"] == "本人"
    assert enabled.json()["timezone"] == "Asia/Shanghai"
    assert enabled.json()["locale"] == "zh-CN"

    persisted = await client.get("/v1/user", headers=first_headers)
    assert persisted.status_code == 200
    assert persisted.json()["elder_mode_enabled"] is True

    other = await client.get("/v1/user", headers=second_headers)
    assert other.status_code == 200
    assert other.json()["elder_mode_enabled"] is False

    # There is no target-user profile mutation surface; query/body ownership
    # hints are ignored/rejected.
    remote_attempt = await client.patch(
        f"/v1/user?user_id={first.json()['user_id']}",
        headers=second_headers,
        json={"elder_mode_enabled": True, "user_id": first.json()["user_id"]},
    )
    assert remote_attempt.status_code == 422

    disabled = await client.patch(
        "/v1/user",
        headers=first_headers,
        json={"elder_mode_enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["elder_mode_enabled"] is False


async def test_elder_mode_rejects_malformed_values(client: AsyncClient):
    register = await _elder_dev_user(client, "Malformed Elder")
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    for invalid in ("true", 1, 0, [], {}):
        response = await client.patch(
            "/v1/user",
            headers=headers,
            json={"elder_mode_enabled": invalid},
        )
        assert response.status_code == 422

    current = await client.get("/v1/user", headers=headers)
    assert current.status_code == 200
    assert current.json()["elder_mode_enabled"] is False



async def test_family_owner_cannot_remotely_change_member_elder_mode(client: AsyncClient):
    owner = await _elder_dev_user(client, "Owner")
    member = await _elder_dev_user(client, "Member")
    owner_headers = {"Authorization": f"Bearer {owner.json()['access_token']}"}
    member_headers = {"Authorization": f"Bearer {member.json()['access_token']}"}

    assert (await client.post("/v1/family", headers=owner_headers)).status_code == 201
    invite = await client.post("/v1/family/invites", headers=owner_headers)
    assert invite.status_code == 201
    accepted = await client.post(
        "/v1/family/invites/accept",
        headers=member_headers,
        json={"token": invite.json()["token"]},
    )
    assert accepted.status_code == 200

    # A target hint in query cannot redirect the self profile endpoint.
    attempt = await client.patch(
        f"/v1/user?target_user_id={member.json()['user_id']}",
        headers=owner_headers,
        json={"elder_mode_enabled": True},
    )
    assert attempt.status_code == 200
    assert attempt.json()["id"] == owner.json()["user_id"]
    assert attempt.json()["elder_mode_enabled"] is True

    member_profile = await client.get("/v1/user", headers=member_headers)
    assert member_profile.status_code == 200
    assert member_profile.json()["id"] == member.json()["user_id"]
    assert member_profile.json()["elder_mode_enabled"] is False
