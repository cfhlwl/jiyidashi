#!/usr/bin/env python3
"""Validate the actual production runtime env file before Compose touches services."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_EXACT = {
    "APP_ENV": "production",
    "ENABLE_DEV_AUTH": "false",
    "AUTH_RATE_LIMIT_ENABLED": "true",
    "AUTO_CREATE_SCHEMA": "false",
    "AUTH_EMAIL_DELIVERY_MODE": "smtp",
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

    if errors:
        for error in errors:
            print(f"production preflight: {error}", file=sys.stderr)
        raise SystemExit(2)

    print(f"production runtime preflight PASS: {path}")


if __name__ == "__main__":
    main()
