from httpx import AsyncClient


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
