from functools import lru_cache
from urllib.parse import urlparse

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

    # [人工注释][S1-006] 媒体存储默认关闭且无公开 URL 回退；启用 s3 时可接
    # COS/OSS 的 S3 SigV4 兼容私有桶。
    storage_backend: str = "disabled"
    storage_bucket: str = ""
    storage_region: str = ""
    storage_endpoint_url: str | None = None
    storage_access_key_id: str = ""
    storage_secret_access_key: str = ""
    storage_addressing_style: str = "virtual"
    storage_object_prefix: str = "media"
    storage_presign_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    media_max_image_bytes: int = Field(
        default=20 * 1024 * 1024,
        ge=1,
        le=50 * 1024 * 1024,
    )
    # [人工注释][S1-004] 60 秒主动语音单独限制大小，防止音频 ASR 路径借共享
    # 50 MiB schema 上限制造不必要的对象存储下载/上游转写压力。
    media_max_audio_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1,
        le=50 * 1024 * 1024,
    )

    # [人工注释][S1-007] ASR 凭证只存在服务端配置。disabled 时语音媒体仍可安全
    # 上传/READY，但 voice-memory 必须 fail closed；openai 模式通过可替换 provider 边界调用转写。
    asr_provider: str = "disabled"
    asr_base_url: str = "https://api.openai.com/v1"
    asr_api_key: str = ""
    asr_model: str = "gpt-4o-mini-transcribe"
    asr_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    asr_min_confidence: float = Field(default=0.60, ge=0.0, le=1.0)

    # [人工注释][S1-FIX-003] 正式认证的滥用保护默认开启，生产环境禁止关闭。
    auth_rate_limit_enabled: bool = True
    auth_register_ip_limit: int = 20
    auth_register_window_seconds: int = 600
    auth_login_ip_limit: int = 30
    auth_login_account_ip_limit: int = 8
    auth_login_window_seconds: int = 900
    auth_login_backoff_after_failures: int = 3
    auth_login_backoff_max_seconds: int = 60

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
        # [人工注释][FND-019] 生产环境配置本身也必须拒绝 dev auth，避免误配置后服务带后门启动。
        if self.is_production and self.enable_dev_auth:
            raise ValueError("ENABLE_DEV_AUTH must be false in production")

        if self.is_production and not self.auth_rate_limit_enabled:
            raise ValueError("AUTH_RATE_LIMIT_ENABLED must be true in production")

        if self.is_production and (
            self.jwt_secret == "change-this-in-real-environments"
            or len(self.jwt_secret.encode("utf-8")) < 32
        ):
            raise ValueError(
                "Production JWT_SECRET must be at least 32 bytes and not use the default"
            )

        # [人工注释][S1-006] 只接受显式支持的存储驱动与寻址方式；启用私有对象
        # 存储时必须具备完整签名配置，禁止半配置后静默回退。
        if self.storage_backend not in {"disabled", "s3"}:
            raise ValueError("STORAGE_BACKEND must be disabled or s3")
        if self.storage_addressing_style not in {"virtual", "path", "auto"}:
            raise ValueError("STORAGE_ADDRESSING_STYLE must be virtual, path or auto")
        if self.storage_backend == "s3" and not all(
            (
                self.storage_bucket.strip(),
                self.storage_access_key_id.strip(),
                self.storage_secret_access_key.strip(),
            )
        ):
            raise ValueError(
                "STORAGE_BUCKET, STORAGE_ACCESS_KEY_ID and STORAGE_SECRET_ACCESS_KEY "
                "are required when STORAGE_BACKEND=s3"
            )

        # [人工注释][S1-006] 生产自定义对象存储 endpoint 承载原图和 SigV4 临时凭证，
        # 必须使用 HTTPS；development/test 仍允许本地 MinIO 等 HTTP endpoint。
        endpoint = (self.storage_endpoint_url or "").strip()
        if self.is_production and self.storage_backend == "s3" and endpoint:
            parsed = urlparse(endpoint)
            if parsed.scheme.lower() != "https" or not parsed.netloc:
                raise ValueError("STORAGE_ENDPOINT_URL must use HTTPS in production")

        # [人工注释][S1-007] provider 枚举和密钥/HTTPS 在服务端启动时 fail closed；
        # 客户端永远拿不到 ASR key，也不能把 provider endpoint 当成直连地址。
        if self.asr_provider not in {"disabled", "openai"}:
            raise ValueError("ASR_PROVIDER must be disabled or openai")
        if self.asr_provider == "openai":
            if not self.asr_api_key.strip() or not self.asr_model.strip():
                raise ValueError(
                    "ASR_API_KEY and ASR_MODEL are required when ASR_PROVIDER=openai"
                )
            parsed_asr = urlparse(self.asr_base_url.strip())
            if not parsed_asr.scheme or not parsed_asr.netloc:
                raise ValueError("ASR_BASE_URL must be an absolute URL")
            if self.is_production and parsed_asr.scheme.lower() != "https":
                raise ValueError("ASR_BASE_URL must use HTTPS in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
