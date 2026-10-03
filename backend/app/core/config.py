from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.embedding_policy import (
    MEMORY_EMBEDDING_DIMENSIONS,
    MEMORY_EMBEDDING_MAX_INPUT_CHARS,
    MEMORY_EMBEDDING_MODEL,
)


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "迹忆 API"
    app_version: str = "0.1.0"
    app_git_sha: str = ""
    app_build_time: str = ""
    database_url: str = "sqlite:///./jiyi.db"
    jwt_secret: str = "change-this-in-real-environments"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "jiyidashi-api"
    jwt_audience: str = "jiyidashi-public"
    access_token_minutes: int = Field(default=15, ge=5, le=120)
    refresh_token_days: int = Field(default=30, ge=1, le=180)
    email_verification_minutes: int = Field(default=30, ge=5, le=1440)
    password_reset_minutes: int = Field(default=30, ge=5, le=240)
    auth_email_delivery_mode: str = "disabled"
    auth_public_base_url: str = ""
    auth_smtp_host: str = ""
    auth_smtp_port: int = Field(default=587, ge=1, le=65535)
    auth_smtp_username: str = ""
    auth_smtp_password: str = ""
    auth_smtp_from: str = ""
    auth_smtp_starttls: bool = True

    # ADMIN-001: privileged browser auth is an independent opaque session domain.
    # No Admin bearer token is issued to browser JavaScript.
    admin_session_minutes: int = Field(default=30, ge=5, le=480)
    admin_session_cookie_name: str = "jiyi_admin_session"
    admin_csrf_cookie_name: str = "jiyi_admin_csrf"

    enable_dev_auth: bool = False
    auto_create_schema: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    observability_log_level: str = "INFO"
    analytics_retrieval_retention_days: int = Field(default=90, ge=31, le=3650)
    analytics_active_day_retention_days: int = Field(default=400, ge=31, le=3650)
    database_readiness_connect_timeout_seconds: int = Field(default=2, ge=1, le=10)
    database_readiness_statement_timeout_ms: int = Field(default=1500, ge=100, le=10000)

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
    # [人工注释][S1-021-FIX-002] Presigned PUT 在 expiry 前已经开始时可继续在过期后完成。
    # Data Delete 因此必须在 capability expiry 之后再等待真实 settle window；
    # 生产值应覆盖部署链路允许的最大 in-flight PUT 生命周期。
    storage_delete_settle_seconds: int = Field(default=300, ge=30, le=86400)
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

    # [人工注释][S3-001] Stage 3 模型调用默认关闭，密钥和 provider endpoint 只在后端。
    # Gateway 对输入大小、输出上限、timeout 和 provider 响应统一 fail closed。
    ai_provider: str = "disabled"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    ai_max_input_chars: int = Field(default=64000, ge=1, le=1_000_000)
    ai_max_output_tokens: int = Field(default=4096, ge=1, le=65536)

    # [BIZ-001..004] Commercial quota values are server-owned configuration.
    # LEGACY_FULL is intentionally unlimited and does not use this catalog.
    entitlement_quota_catalog: dict[str, dict[str, int]] = Field(default_factory=dict)

    # [人工注释][S3-009] Embedding 是服务端派生索引，模型/维度由 schema policy 固定；
    # provider endpoint/key 不进入客户端，也不能由单次生成请求覆盖。
    embedding_provider: str = "disabled"
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = MEMORY_EMBEDDING_MODEL
    embedding_dimensions: int = Field(default=MEMORY_EMBEDDING_DIMENSIONS, ge=1, le=4096)
    embedding_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    embedding_max_input_chars: int = Field(
        default=MEMORY_EMBEDDING_MAX_INPUT_CHARS,
        ge=1,
        le=MEMORY_EMBEDDING_MAX_INPUT_CHARS,
    )

    # [人工注释][S1-FIX-003] 正式认证的滥用保护默认开启，生产环境禁止关闭。
    auth_rate_limit_enabled: bool = True
    auth_register_ip_limit: int = 20
    auth_register_window_seconds: int = 600
    auth_login_ip_limit: int = 30
    auth_login_account_ip_limit: int = 8
    auth_login_window_seconds: int = 900
    auth_login_backoff_after_failures: int = 3
    auth_login_backoff_max_seconds: int = 60
    auth_refresh_session_limit: int = Field(default=30, ge=5, le=300)
    auth_refresh_window_seconds: int = Field(default=900, ge=60, le=86400)
    auth_verify_resend_ip_limit: int = Field(default=10, ge=1, le=100)
    auth_verify_resend_account_limit: int = Field(default=5, ge=1, le=50)
    auth_verify_resend_window_seconds: int = Field(default=3600, ge=60, le=86400)
    auth_password_reset_ip_limit: int = Field(default=10, ge=1, le=100)
    auth_password_reset_account_limit: int = Field(default=5, ge=1, le=50)
    auth_password_reset_confirm_limit: int = Field(default=10, ge=1, le=50)
    auth_password_reset_window_seconds: int = Field(default=3600, ge=60, le=86400)

    # ADMIN-001 review hardening: privileged login has a separate, stricter
    # namespace/policy so ordinary-user traffic cannot consume or reset Admin buckets.
    admin_login_ip_limit: int = Field(default=30, ge=1, le=100)
    admin_login_account_ip_limit: int = Field(default=5, ge=1, le=50)
    admin_login_window_seconds: int = Field(default=900, ge=60, le=86400)
    admin_login_backoff_after_failures: int = Field(default=2, ge=1, le=20)
    admin_login_backoff_max_seconds: int = Field(default=300, ge=1, le=3600)

    # [人工注释][S2-006~S2-014] Stage 2 第一条线只在服务端定义定位派生参数。
    # late-arrival grace 决定历史点可回补多久；raw retention 必须明显长于它，
    # 才能保证 Visit 已 durable finalization 后再清理原始位置证据。
    location_visit_radius_m: float = Field(default=120.0, ge=20.0, le=1000.0)
    location_visit_max_gap_seconds: int = Field(default=1800, ge=60, le=21600)
    location_visit_min_duration_seconds: int = Field(default=300, ge=60, le=21600)
    location_visit_min_points: int = Field(default=2, ge=2, le=50)
    location_late_arrival_grace_seconds: int = Field(
        default=86400,
        ge=3600,
        le=30 * 86400,
    )
    location_raw_retention_days: int = Field(default=30, ge=2, le=365)
    # [人工注释][S2-006] 设备时钟允许有限漂移，但明显未来点不能进入 raw/Visit/Place，
    # 否则既会制造未来事实，也会绕过以 server now 为基准的 retention。
    location_future_skew_seconds: int = Field(default=300, ge=0, le=86400)
    location_place_geohash_precision: int = Field(default=7, ge=5, le=9)

    # CORE-004: reverse place naming is a server-only provider boundary. Mobile clients
    # never receive the AMap key and never embed an AMap SDK for naming.
    place_resolver_provider: str = "disabled"
    amap_web_service_base_url: str = "https://restapi.amap.com/v3"
    amap_web_service_key: str = ""
    amap_timeout_seconds: float = Field(default=3.0, ge=0.5, le=15.0)
    place_naming_cache_ttl_seconds: int = Field(default=86400, ge=60, le=604800)
    place_naming_failure_backoff_seconds: int = Field(default=300, ge=10, le=86400)
    place_naming_cache_max_entries: int = Field(default=2048, ge=16, le=10000)
    place_naming_backfill_batch_size: int = Field(default=20, ge=1, le=200)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_analytics_retention(self):
        if self.analytics_active_day_retention_days < self.analytics_retrieval_retention_days:
            raise ValueError(
                "ANALYTICS_ACTIVE_DAY_RETENTION_DAYS must be >= retrieval retention"
            )
        return self

    @model_validator(mode="after")
    def validate_observability(self):
        level = self.observability_log_level.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(
                "OBSERVABILITY_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR"
            )
        self.observability_log_level = level
        return self

    @model_validator(mode="after")
    def validate_entitlement_quota_catalog(self):
        allowed_plans = {"FREE", "PERSONAL", "FAMILY", "PREMIUM"}
        allowed_dimensions = {
            "STORAGE_BYTES",
            "AI_PROVIDER_REQUESTS",
            "AI_INPUT_TOKENS",
            "AI_OUTPUT_TOKENS",
        }
        # PostgreSQL BIGINT is the canonical persisted quota/counter domain.
        max_limit = 9_223_372_036_854_775_807
        for plan_code, quotas in self.entitlement_quota_catalog.items():
            if plan_code not in allowed_plans or not isinstance(quotas, dict):
                raise ValueError("ENTITLEMENT_QUOTA_CATALOG contains an invalid plan")
            for dimension, limit in quotas.items():
                if dimension not in allowed_dimensions:
                    raise ValueError(
                        "ENTITLEMENT_QUOTA_CATALOG contains an invalid quota dimension"
                    )
                if (
                    not isinstance(limit, int)
                    or isinstance(limit, bool)
                    or limit < 0
                    or limit > max_limit
                ):
                    raise ValueError(
                        "ENTITLEMENT_QUOTA_CATALOG limits must be bounded non-negative integers"
                    )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def validate_production_security(self):
        if (
            self.location_raw_retention_days * 86400
            <= self.location_late_arrival_grace_seconds
            + self.location_visit_max_gap_seconds
        ):
            raise ValueError(
                "LOCATION_RAW_RETENTION_DAYS must outlive late-arrival grace "
                "plus the Visit gap window"
            )

        # [人工注释][FND-019] 生产环境配置本身也必须拒绝 dev auth，避免误配置后服务带后门启动。
        if self.is_production and self.enable_dev_auth:
            raise ValueError("ENABLE_DEV_AUTH must be false in production")

        if self.is_production and not self.auth_rate_limit_enabled:
            raise ValueError("AUTH_RATE_LIMIT_ENABLED must be true in production")

        if self.auth_email_delivery_mode not in {"disabled", "smtp"}:
            raise ValueError("AUTH_EMAIL_DELIVERY_MODE must be disabled or smtp")
        if self.is_production and self.auth_email_delivery_mode != "smtp":
            raise ValueError("AUTH_EMAIL_DELIVERY_MODE must be smtp in production")
        if self.auth_email_delivery_mode == "smtp":
            if not self.auth_smtp_host.strip() or not self.auth_smtp_from.strip():
                raise ValueError(
                    "AUTH_SMTP_HOST and AUTH_SMTP_FROM are required when email delivery is smtp"
                )
            public_base = self.auth_public_base_url.strip()
            parsed_auth_base = urlparse(public_base)
            if not parsed_auth_base.scheme or not parsed_auth_base.netloc:
                raise ValueError("AUTH_PUBLIC_BASE_URL must be an absolute URL")
            if self.is_production and parsed_auth_base.scheme.lower() != "https":
                raise ValueError("AUTH_PUBLIC_BASE_URL must use HTTPS in production")

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

        # [人工注释][S3-001] AI provider 选择在服务启动配置期失败关闭；生产 provider
        # endpoint 必须 HTTPS，客户端不会获得 key、base URL 或 provider 选择权。
        if self.ai_provider not in {"disabled", "openai"}:
            raise ValueError("AI_PROVIDER must be disabled or openai")
        if self.ai_provider == "openai":
            if not self.ai_api_key.strip() or not self.ai_model.strip():
                raise ValueError(
                    "AI_API_KEY and AI_MODEL are required when AI_PROVIDER=openai"
                )
            parsed_ai = urlparse(self.ai_base_url.strip())
            if not parsed_ai.scheme or not parsed_ai.netloc:
                raise ValueError("AI_BASE_URL must be an absolute URL")
            if self.is_production and parsed_ai.scheme.lower() != "https":
                raise ValueError("AI_BASE_URL must use HTTPS in production")

        if self.embedding_provider not in {"disabled", "openai"}:
            raise ValueError("EMBEDDING_PROVIDER must be disabled or openai")
        if (
            self.embedding_model != MEMORY_EMBEDDING_MODEL
            or self.embedding_dimensions != MEMORY_EMBEDDING_DIMENSIONS
        ):
            raise ValueError(
                "Embedding model/dimensions must match the reviewed S3-009 policy"
            )
        if self.embedding_provider == "openai":
            if not self.embedding_api_key.strip():
                raise ValueError(
                    "EMBEDDING_API_KEY is required when EMBEDDING_PROVIDER=openai"
                )
            parsed_embedding = urlparse(self.embedding_base_url.strip())
            if not parsed_embedding.scheme or not parsed_embedding.netloc:
                raise ValueError("EMBEDDING_BASE_URL must be an absolute URL")
            if self.is_production and parsed_embedding.scheme.lower() != "https":
                raise ValueError("EMBEDDING_BASE_URL must use HTTPS in production")

        if self.place_resolver_provider not in {"disabled", "amap"}:
            raise ValueError("PLACE_RESOLVER_PROVIDER must be disabled or amap")
        if self.place_resolver_provider == "amap":
            if not self.amap_web_service_key.strip():
                raise ValueError(
                    "AMAP_WEB_SERVICE_KEY is required when PLACE_RESOLVER_PROVIDER=amap"
                )
            parsed_amap = urlparse(self.amap_web_service_base_url.strip())
            if not parsed_amap.scheme or not parsed_amap.netloc:
                raise ValueError("AMAP_WEB_SERVICE_BASE_URL must be an absolute URL")
            if self.is_production and parsed_amap.scheme.lower() != "https":
                raise ValueError("AMAP_WEB_SERVICE_BASE_URL must use HTTPS in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
