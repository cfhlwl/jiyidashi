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
