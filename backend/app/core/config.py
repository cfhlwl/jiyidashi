from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "迹忆 API"
    database_url: str = "sqlite:///./jiyi.db"
    jwt_secret: str = "change-this-in-real-environments"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 24 * 7
    enable_dev_auth: bool = False
    auto_create_schema: bool = False
    cors_origins: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.is_production and (
            self.jwt_secret == "change-this-in-real-environments"
            or len(self.jwt_secret.encode("utf-8")) < 32
        ):
            raise ValueError(
                "Production JWT_SECRET must be at least 32 bytes and not use the default"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
