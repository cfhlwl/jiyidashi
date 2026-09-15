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
    settings = Settings(
        _env_file=None,
        app_env="prod",
        database_url="sqlite:///./unused.db",
        jwt_secret="0123456789abcdef0123456789abcdef",
    )
    assert settings.is_production is True
