#!/usr/bin/env python3
"""Validate the actual production runtime env file before Compose touches services."""

from __future__ import annotations

import base64
import binascii
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

REQUIRED_EXACT = {
    "APP_ENV": "production",
    "ENABLE_DEV_AUTH": "false",
    "AUTH_RATE_LIMIT_ENABLED": "true",
    "AUTO_CREATE_SCHEMA": "false",
    "AUTH_EMAIL_DELIVERY_MODE": "smtp",
    "BACKUP_OFFHOST_ENABLED": "true",
}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def valid_fernet_key(value: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError, binascii.Error):
        return False
    return len(decoded) == 32


def bounded_int(
    values: dict[str, str],
    name: str,
    *,
    minimum: int,
    maximum: int,
    errors: list[str],
) -> int | None:
    try:
        value = int(values.get(name, ""))
    except ValueError:
        value = None
    if value is None or not minimum <= value <= maximum:
        errors.append(f"{name} must be between {minimum} and {maximum}")
        return None
    return value


def body_limit_bytes(value: str) -> int | None:
    match = re.fullmatch(r"([1-9][0-9]*)(B|KB|MB|KiB|MiB)", value)
    if match is None:
        return None
    amount = int(match.group(1))
    multiplier = {
        "B": 1,
        "KB": 1000,
        "MB": 1000 * 1000,
        "KiB": 1024,
        "MiB": 1024 * 1024,
    }[match.group(2)]
    return amount * multiplier


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate-production-runtime.py /path/to/.env.production")

    path = Path(sys.argv[1]).resolve()
    if not path.is_file():
        raise SystemExit(f"production env does not exist: {path}")

    values = parse_env(path)
    errors: list[str] = []
    for key, expected in REQUIRED_EXACT.items():
        actual = values.get(key, "")
        if actual.lower() != expected:
            errors.append(f"{key} must be {expected!r}, got {actual!r}")

    jwt_secret = values.get("JWT_SECRET", "")
    if len(jwt_secret.encode("utf-8")) < 32 or jwt_secret == "change-this-in-real-environments":
        errors.append("JWT_SECRET must be non-default and at least 32 bytes")

    provider_master_key = values.get("PROVIDER_CONFIG_MASTER_KEY", "")
    if not valid_fernet_key(provider_master_key):
        errors.append("PROVIDER_CONFIG_MASTER_KEY must be a valid 32-byte Fernet key")

    public_auth_base = values.get("AUTH_PUBLIC_BASE_URL", "")
    if not public_auth_base.startswith("https://"):
        errors.append("AUTH_PUBLIC_BASE_URL must use HTTPS")
    if not values.get("AUTH_SMTP_HOST", ""):
        errors.append("AUTH_SMTP_HOST is required")
    if not values.get("AUTH_SMTP_FROM", ""):
        errors.append("AUTH_SMTP_FROM is required")

    database_url = values.get("DATABASE_URL", "")
    try:
        parsed_database = urlsplit(database_url)
    except ValueError:
        parsed_database = None

    if (
        parsed_database is None
        or parsed_database.scheme != "postgresql+psycopg"
        or parsed_database.hostname != "postgres"
        or parsed_database.port != 5432
    ):
        errors.append("DATABASE_URL must target the production postgres service")
    else:
        url_database = unquote(parsed_database.path.lstrip("/"))
        url_username = unquote(parsed_database.username or "")
        url_password = unquote(parsed_database.password or "")
        if url_database != values.get("POSTGRES_DB", ""):
            errors.append("DATABASE_URL database must match POSTGRES_DB")
        if url_username != values.get("POSTGRES_USER", ""):
            errors.append("DATABASE_URL username must match POSTGRES_USER")
        if url_password != values.get("POSTGRES_PASSWORD", ""):
            errors.append("DATABASE_URL password must match POSTGRES_PASSWORD")

    pool_size = bounded_int(
        values, "DB_POOL_SIZE", minimum=1, maximum=10, errors=errors
    )
    max_overflow = bounded_int(
        values, "DB_MAX_OVERFLOW", minimum=0, maximum=10, errors=errors
    )
    pool_timeout = bounded_int(
        values, "DB_POOL_TIMEOUT_SECONDS", minimum=1, maximum=30, errors=errors
    )
    pool_recycle = bounded_int(
        values, "DB_POOL_RECYCLE_SECONDS", minimum=30, maximum=3600, errors=errors
    )
    connection_budget = bounded_int(
        values, "DB_CONNECTION_BUDGET", minimum=4, maximum=64, errors=errors
    )
    web_concurrency = bounded_int(
        values, "WEB_CONCURRENCY", minimum=1, maximum=8, errors=errors
    )
    if (
        pool_size is not None
        and max_overflow is not None
        and connection_budget is not None
        and web_concurrency is not None
    ):
        max_application_connections = (web_concurrency + 1) * (
            pool_size + max_overflow
        )
        if max_application_connections > connection_budget:
            errors.append(
                "DB pool connection budget exceeded for WEB_CONCURRENCY + worker"
            )

    security_provider = values.get("SECURITY_ALERT_HUMAN_PROVIDER", "").strip().lower()
    if security_provider != "feishu":
        errors.append("SECURITY_ALERT_HUMAN_PROVIDER must be feishu in production")

    security_webhook = values.get("SECURITY_ALERT_FEISHU_WEBHOOK_URL", "").strip()
    try:
        parsed_security_webhook = urlsplit(security_webhook)
    except ValueError:
        parsed_security_webhook = None
    if (
        parsed_security_webhook is None
        or parsed_security_webhook.scheme.lower() != "https"
        or parsed_security_webhook.hostname != "open.feishu.cn"
        or parsed_security_webhook.port not in (None, 443)
        or parsed_security_webhook.username
        or parsed_security_webhook.password
        or parsed_security_webhook.query
        or parsed_security_webhook.fragment
        or not parsed_security_webhook.path.startswith("/open-apis/bot/v2/hook/")
        or not parsed_security_webhook.path[len("/open-apis/bot/v2/hook/") :]
        or "/" in parsed_security_webhook.path[len("/open-apis/bot/v2/hook/") :]
    ):
        errors.append(
            "SECURITY_ALERT_FEISHU_WEBHOOK_URL must be a reviewed Feishu HTTPS webhook"
        )
    elif (
        "CHANGE_ME" in security_webhook.upper()
        or "PLACEHOLDER" in security_webhook.upper()
    ):
        errors.append("SECURITY_ALERT_FEISHU_WEBHOOK_URL must not be a placeholder")

    def _env_true(key: str) -> bool:
        return values.get(key, "").strip().lower() == "true"

    def _placeholder(value: str) -> bool:
        upper = value.strip().upper()
        return not upper or "CHANGE_ME" in upper or "PLACEHOLDER" in upper

    apns_enabled = _env_true("APNS_ENABLED")
    fcm_enabled = _env_true("FCM_ENABLED")
    hms_enabled = _env_true("HMS_ENABLED")
    if apns_enabled or fcm_enabled or hms_enabled:
        if not _env_true("PUSH_APP_IDENTITY_REVIEWED"):
            errors.append(
                "PUSH_APP_IDENTITY_REVIEWED must be true before live push is enabled"
            )

    if apns_enabled:
        ios_bundle = values.get("PUSH_IOS_BUNDLE_ID", "").strip()
        apns_topic = values.get("APNS_TOPIC", "").strip()
        if _placeholder(ios_bundle) or _placeholder(apns_topic) or ios_bundle != apns_topic:
            errors.append("APNS_TOPIC must exactly match reviewed PUSH_IOS_BUNDLE_ID")
        if values.get("APNS_ENVIRONMENT", "").strip().lower() != "production":
            errors.append("APNS_ENVIRONMENT must be production")
        for key in ("APNS_TEAM_ID", "APNS_KEY_ID"):
            if _placeholder(values.get(key, "")):
                errors.append(f"{key} must be a non-placeholder reviewed value")
        apns_inline = values.get("APNS_PRIVATE_KEY", "").strip()
        apns_file = values.get("APNS_PRIVATE_KEY_FILE", "").strip()
        if bool(apns_inline) == bool(apns_file):
            errors.append(
                "configure exactly one of APNS_PRIVATE_KEY or APNS_PRIVATE_KEY_FILE"
            )
        if apns_inline and _placeholder(apns_inline):
            errors.append("APNS_PRIVATE_KEY must not be a placeholder")
        if apns_file and not apns_file.startswith("/"):
            errors.append("APNS_PRIVATE_KEY_FILE must be an absolute runtime secret path")

    if fcm_enabled:
        if _placeholder(values.get("PUSH_ANDROID_APPLICATION_ID", "")):
            errors.append("PUSH_ANDROID_APPLICATION_ID must be reviewed before FCM")
        for key in ("FCM_PROJECT_ID", "FCM_CLIENT_EMAIL"):
            if _placeholder(values.get(key, "")):
                errors.append(f"{key} must be a non-placeholder reviewed value")
        fcm_inline = values.get("FCM_PRIVATE_KEY", "").strip()
        fcm_file = values.get("FCM_PRIVATE_KEY_FILE", "").strip()
        if bool(fcm_inline) == bool(fcm_file):
            errors.append(
                "configure exactly one of FCM_PRIVATE_KEY or FCM_PRIVATE_KEY_FILE"
            )
        if fcm_inline and _placeholder(fcm_inline):
            errors.append("FCM_PRIVATE_KEY must not be a placeholder")
        if fcm_file and not fcm_file.startswith("/"):
            errors.append("FCM_PRIVATE_KEY_FILE must be an absolute runtime secret path")
        if values.get("FCM_TOKEN_URI", "").strip() != "https://oauth2.googleapis.com/token":
            errors.append("FCM_TOKEN_URI must use the reviewed Google OAuth endpoint")

    if hms_enabled:
        if _placeholder(values.get("PUSH_ANDROID_APPLICATION_ID", "")):
            errors.append("PUSH_ANDROID_APPLICATION_ID must be reviewed before HMS")
        for key in ("HMS_APP_ID", "HMS_CLIENT_ID", "HMS_CLIENT_SECRET"):
            if _placeholder(values.get(key, "")):
                errors.append(f"{key} must be a non-placeholder reviewed value")
        if (
            values.get("HMS_OAUTH_URL", "").strip()
            != "https://oauth-login.cloud.huawei.com/oauth2/v3/token"
        ):
            errors.append("HMS_OAUTH_URL must use the reviewed Huawei OAuth endpoint")
        if (
            values.get("HMS_PUSH_BASE_URL", "").strip().rstrip("/")
            != "https://push-api.cloud.huawei.com"
        ):
            errors.append("HMS_PUSH_BASE_URL must use the reviewed Huawei Push origin")

    for key, default, minimum, maximum in (
        ("PUSH_PROVIDER_CONNECT_TIMEOUT_SECONDS", 3.0, 0.5, 15.0),
        ("PUSH_PROVIDER_READ_TIMEOUT_SECONDS", 5.0, 0.5, 30.0),
        ("PUSH_PROVIDER_WRITE_TIMEOUT_SECONDS", 5.0, 0.5, 30.0),
        ("PUSH_PROVIDER_POOL_TIMEOUT_SECONDS", 3.0, 0.5, 15.0),
    ):
        try:
            value = float(values.get(key, str(default)))
        except ValueError:
            value = 0.0
        if not minimum <= value <= maximum:
            errors.append(f"{key} must be between {minimum} and {maximum}")

    security_secret = values.get("SECURITY_ALERT_FEISHU_SECRET", "").strip()
    if (
        not security_secret
        or "CHANGE_ME" in security_secret.upper()
        or "PLACEHOLDER" in security_secret.upper()
    ):
        errors.append("SECURITY_ALERT_FEISHU_SECRET must be a non-placeholder secret")

    try:
        security_timeout = float(
            values.get("SECURITY_ALERT_DELIVERY_TIMEOUT_SECONDS", "")
        )
    except ValueError:
        security_timeout = 0.0
    if not 1.0 <= security_timeout <= 15.0:
        errors.append(
            "SECURITY_ALERT_DELIVERY_TIMEOUT_SECONDS must be between 1 and 15"
        )

    media_image_max = bounded_int(
        values, "MEDIA_MAX_IMAGE_BYTES", minimum=1, maximum=50 * 1024 * 1024, errors=errors
    )
    ai_image_max = bounded_int(
        values, "AI_IMAGE_MAX_BYTES", minimum=64 * 1024, maximum=8 * 1024 * 1024, errors=errors
    )
    ai_image_dimension = bounded_int(
        values, "AI_IMAGE_MAX_DIMENSION", minimum=256, maximum=8192, errors=errors
    )
    ai_image_pixels = bounded_int(
        values, "AI_IMAGE_MAX_PIXELS", minimum=65_536, maximum=32_000_000, errors=errors
    )
    if (
        media_image_max is not None
        and ai_image_max is not None
        and ai_image_max >= media_image_max
    ):
        errors.append("AI_IMAGE_MAX_BYTES must be lower than MEDIA_MAX_IMAGE_BYTES")
    if (
        ai_image_dimension is not None
        and ai_image_pixels is not None
        and ai_image_pixels > ai_image_dimension * ai_image_dimension
    ):
        errors.append("AI_IMAGE_MAX_PIXELS must not exceed AI_IMAGE_MAX_DIMENSION squared")

    preprocess_global = bounded_int(
        values,
        "AI_IMAGE_PREPROCESS_GLOBAL_CONCURRENCY",
        minimum=1,
        maximum=64,
        errors=errors,
    )
    preprocess_user = bounded_int(
        values,
        "AI_IMAGE_PREPROCESS_USER_CONCURRENCY",
        minimum=1,
        maximum=64,
        errors=errors,
    )
    bounded_int(
        values,
        "AI_IMAGE_PREPROCESS_PERMIT_LEASE_SECONDS",
        minimum=5,
        maximum=600,
        errors=errors,
    )
    if (
        preprocess_global is not None
        and preprocess_user is not None
        and preprocess_user > preprocess_global
    ):
        errors.append(
            "AI_IMAGE_PREPROCESS_USER_CONCURRENCY must be <= global concurrency"
        )

    bounded_int(
        values, "EXPORT_BATCH_SIZE", minimum=25, maximum=1000, errors=errors
    )
    export_artifact_max = bounded_int(
        values,
        "EXPORT_ARTIFACT_MAX_BYTES",
        minimum=1024 * 1024,
        maximum=256 * 1024 * 1024,
        errors=errors,
    )
    if export_artifact_max is not None:
        export_temp_capacity = 320 * 1024 * 1024
        export_temp_headroom = 64 * 1024 * 1024
        if export_artifact_max + export_temp_headroom > export_temp_capacity:
            errors.append(
                "EXPORT_ARTIFACT_MAX_BYTES exceeds reviewed worker temp budget"
            )
    bounded_int(
        values, "EXPORT_ARTIFACT_TTL_HOURS", minimum=1, maximum=168, errors=errors
    )

    request_body_limit = body_limit_bytes(values.get("API_REQUEST_BODY_LIMIT", ""))
    if request_body_limit is None:
        errors.append("API_REQUEST_BODY_LIMIT must be a bounded byte size")
    elif not 256 * 1024 <= request_body_limit <= 8 * 1024 * 1024:
        errors.append("API_REQUEST_BODY_LIMIT must be between 256KiB and 8MiB")

    backup_bucket = values.get("BACKUP_STORAGE_BUCKET", "")
    backup_region = values.get("BACKUP_STORAGE_REGION", "")
    backup_endpoint = values.get("BACKUP_STORAGE_ENDPOINT_URL", "")
    backup_access = values.get("BACKUP_STORAGE_ACCESS_KEY_ID", "")
    backup_secret = values.get("BACKUP_STORAGE_SECRET_ACCESS_KEY", "")
    backup_style = values.get("BACKUP_STORAGE_ADDRESSING_STYLE", "")
    backup_prefix = values.get("BACKUP_OBJECT_PREFIX", "")
    backup_cluster = values.get("BACKUP_SOURCE_CLUSTER_ID", "")
    if not backup_bucket:
        errors.append("BACKUP_STORAGE_BUCKET is required")
    if not backup_region:
        errors.append("BACKUP_STORAGE_REGION is required")
    if not backup_endpoint.startswith("https://"):
        errors.append("BACKUP_STORAGE_ENDPOINT_URL must use HTTPS")
    if not backup_access or not backup_secret:
        errors.append("backup storage credentials are required")
    if backup_style not in {"virtual", "path"}:
        errors.append("BACKUP_STORAGE_ADDRESSING_STYLE must be virtual or path")
    if not backup_prefix.strip("/"):
        errors.append("BACKUP_OBJECT_PREFIX is required")
    if not backup_cluster:
        errors.append("BACKUP_SOURCE_CLUSTER_ID is required")
    for key, value in (
        ("BACKUP_STORAGE_BUCKET", backup_bucket),
        ("BACKUP_STORAGE_REGION", backup_region),
        ("BACKUP_STORAGE_ACCESS_KEY_ID", backup_access),
        ("BACKUP_STORAGE_SECRET_ACCESS_KEY", backup_secret),
        ("BACKUP_SOURCE_CLUSTER_ID", backup_cluster),
    ):
        if value.startswith("CHANGE_ME"):
            errors.append(f"{key} must not use the committed placeholder")
    for key in (
        "BACKUP_RETENTION_DAILY",
        "BACKUP_RETENTION_WEEKLY",
        "BACKUP_RETENTION_MONTHLY",
    ):
        try:
            value = int(values.get(key, ""))
        except ValueError:
            value = 0
        if value < 1:
            errors.append(f"{key} must be >= 1")

    if errors:
        for error in errors:
            print(f"production preflight: {error}", file=sys.stderr)
        raise SystemExit(2)

    print(f"production runtime preflight PASS: {path}")


if __name__ == "__main__":
    main()
