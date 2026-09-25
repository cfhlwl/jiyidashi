from httpx import AsyncClient

from app.services import auth_service


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


async def test_register_login_and_update_profile(client: AsyncClient):
    # [人工注释][S1-001] 正式注册必须直接得到可访问本人资源的 Token。
    register = await _register(client, email="stage1-auth@example.com")
    assert register.status_code == 201
    body = register.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}

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
    first = await _register(client, email="stage1-duplicate@example.com")
    assert first.status_code == 201

    duplicate = await _register(client, email="STAGE1-DUPLICATE@example.com")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "AUTH_IDENTITY_EXISTS"

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


async def test_profile_rejects_invalid_timezone(client: AsyncClient):
    register = await _register(client, email="stage1-profile-timezone@example.com")
    assert register.status_code == 201
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

    response = await client.patch(
        "/v1/user",
        headers=headers,
        json={"timezone": "UTC+8-not-iana"},
    )
    assert response.status_code == 422

    current = await client.get("/v1/user", headers=headers)
    assert current.status_code == 200
    assert current.json()["timezone"] == "Asia/Shanghai"


async def test_profile_and_registration_reject_whitespace_only_text(client: AsyncClient):
    bad_register = await _register(
        client,
        email="stage1-whitespace-register@example.com",
        nickname="   ",
    )
    assert bad_register.status_code == 422

    register = await _register(client, email="stage1-whitespace-profile@example.com")
    assert register.status_code == 201
    headers = {"Authorization": f"Bearer {register.json()['access_token']}"}

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
    first = await _register(client, email="elder-self@example.com", nickname="本人")
    second = await _register(client, email="elder-other@example.com", nickname="其他人")
    assert first.status_code == 201
    assert second.status_code == 201
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

    # There is no target-user profile mutation surface; query/body ownership hints are ignored/rejected.
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
    register = await _register(client, email="elder-malformed@example.com")
    assert register.status_code == 201
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
