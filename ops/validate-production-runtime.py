#!/usr/bin/env python3
"""Validate the actual production runtime env file before Compose touches services."""

from __future__ import annotations

import base64
import binascii
import sys
from pathlib import Path

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
    if not database_url.startswith("postgresql+psycopg://") or "@postgres:5432/" not in database_url:
        errors.append("DATABASE_URL must target the production postgres service")

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
