import pytest

from app.api import auth as auth_api
from app.core.config import Settings


def test_dev_auth_is_fail_closed_by_default():
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="sqlite:///./unused.db",
        jwt_secret="test-secret-0123456789abcdef-0123456789abcdef",
        enable_dev_auth=False,
        auto_create_schema=False,
    )
    assert settings.enable_dev_auth is False


def test_prod_alias_is_treated_as_production():
    # [人工注释][FND-019] 本测试只验证 prod 别名，显式关闭 dev auth，避免继承 CI 开发环境变量。
    settings = Settings(
        _env_file=None,
        app_env="prod",
        database_url="sqlite:///./unused.db",
        jwt_secret="0123456789abcdef0123456789abcdef",
        enable_dev_auth=False,
        auto_create_schema=False,
    )
    assert settings.is_production is True


def test_production_configuration_rejects_enabled_dev_auth():
    # [人工注释][FND-019] 生产配置层必须拒绝 ENABLE_DEV_AUTH=true，防止误配置带后门启动。
    with pytest.raises(ValueError, match="ENABLE_DEV_AUTH must be false in production"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="sqlite:///./unused.db",
            jwt_secret="0123456789abcdef0123456789abcdef",
            enable_dev_auth=True,
            auto_create_schema=False,
        )


async def test_dev_token_endpoint_still_rejects_bypassed_production_config(
    client,
    monkeypatch,
):
    # [人工注释][FND-019] 即使有人绕过 Settings validator 构造危险配置，endpoint 仍必须硬 404。
    unsafe_settings = Settings.model_construct(
        app_env="production",
        enable_dev_auth=True,
        jwt_secret="0123456789abcdef0123456789abcdef",
    )
    monkeypatch.setattr(auth_api, "settings", unsafe_settings)

    response = await client.post("/v1/auth/dev-token", json={"nickname": "Unsafe Prod"})
    assert response.status_code == 404
    assert response.json()["detail"] == "NOT_FOUND"
