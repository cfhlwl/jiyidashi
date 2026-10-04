#!/usr/bin/env python3
"""Static production deployment contract validation using only the stdlib."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_TEMPLATE = ROOT / "backend" / ".env.production.example"

REQUIRED_KEYS = {
    "APP_ENV",
    "APP_NAME",
    "DATABASE_URL",
    "JWT_SECRET",
    "JWT_ALGORITHM",
    "ACCESS_TOKEN_MINUTES",
    "JWT_ISSUER",
    "JWT_AUDIENCE",
    "REFRESH_TOKEN_DAYS",
    "EMAIL_VERIFICATION_MINUTES",
    "PASSWORD_RESET_MINUTES",
    "ENABLE_DEV_AUTH",
    "AUTO_CREATE_SCHEMA",
    "CORS_ORIGINS",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "API_DOMAIN",
    "ACME_EMAIL",
    "WEB_CONCURRENCY",
    "AUTH_RATE_LIMIT_ENABLED",
    "AUTH_REGISTER_IP_LIMIT",
    "AUTH_REGISTER_WINDOW_SECONDS",
    "AUTH_LOGIN_IP_LIMIT",
    "AUTH_LOGIN_ACCOUNT_IP_LIMIT",
    "AUTH_LOGIN_WINDOW_SECONDS",
    "AUTH_LOGIN_BACKOFF_AFTER_FAILURES",
    "AUTH_LOGIN_BACKOFF_MAX_SECONDS",
    "AUTH_REFRESH_SESSION_LIMIT",
    "AUTH_REFRESH_WINDOW_SECONDS",
    "AUTH_VERIFY_RESEND_IP_LIMIT",
    "AUTH_VERIFY_RESEND_ACCOUNT_LIMIT",
    "AUTH_VERIFY_RESEND_WINDOW_SECONDS",
    "AUTH_PASSWORD_RESET_IP_LIMIT",
    "AUTH_PASSWORD_RESET_ACCOUNT_LIMIT",
    "AUTH_PASSWORD_RESET_CONFIRM_LIMIT",
    "AUTH_PASSWORD_RESET_WINDOW_SECONDS",
    "AUTH_EMAIL_DELIVERY_MODE",
    "AUTH_PUBLIC_BASE_URL",
    "AUTH_SMTP_HOST",
    "AUTH_SMTP_PORT",
    "AUTH_SMTP_USERNAME",
    "AUTH_SMTP_PASSWORD",
    "PROVIDER_CONFIG_MASTER_KEY",
    "AUTH_SMTP_FROM",
    "AUTH_SMTP_STARTTLS",
    "STORAGE_BACKEND",
    "STORAGE_BUCKET",
    "STORAGE_REGION",
    "STORAGE_ENDPOINT_URL",
    "STORAGE_ACCESS_KEY_ID",
    "STORAGE_SECRET_ACCESS_KEY",
    "STORAGE_ADDRESSING_STYLE",
    "STORAGE_OBJECT_PREFIX",
    "STORAGE_PRESIGN_TTL_SECONDS",
    "STORAGE_DELETE_SETTLE_SECONDS",
    "MEDIA_MAX_IMAGE_BYTES",
    "MEDIA_MAX_AUDIO_BYTES",
    "PROVIDER_CONFIG_CACHE_TTL_SECONDS",
    "ASR_PROVIDER",
    "ASR_BASE_URL",
    "ASR_API_KEY",
    "ASR_MODEL",
    "ASR_TIMEOUT_SECONDS",
    "ASR_MIN_CONFIDENCE",
    "AI_PROVIDER",
    "AI_BASE_URL",
    "AI_API_KEY",
    "AI_MODEL",
    "AI_TIMEOUT_SECONDS",
    "AI_MAX_INPUT_CHARS",
    "AI_MAX_OUTPUT_TOKENS",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "EMBEDDING_TIMEOUT_SECONDS",
    "EMBEDDING_MAX_INPUT_CHARS",
    "LOCATION_VISIT_RADIUS_M",
    "LOCATION_VISIT_MAX_GAP_SECONDS",
    "LOCATION_VISIT_MIN_DURATION_SECONDS",
    "LOCATION_VISIT_MIN_POINTS",
    "LOCATION_LATE_ARRIVAL_GRACE_SECONDS",
    "LOCATION_RAW_RETENTION_DAYS",
    "LOCATION_FUTURE_SKEW_SECONDS",
    "LOCATION_PLACE_GEOHASH_PRECISION",
}

SENSITIVE_PLACEHOLDERS = {
    "JWT_SECRET",
    "POSTGRES_PASSWORD",
    "STORAGE_ACCESS_KEY_ID",
    "STORAGE_SECRET_ACCESS_KEY",
    "AUTH_SMTP_USERNAME",
    "AUTH_SMTP_PASSWORD",
    "PROVIDER_CONFIG_MASTER_KEY",
}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise AssertionError(f"invalid env template line: {raw_line!r}")
        values[key.strip()] = value.strip()
    return values


def assert_sensitive_placeholders(values: dict[str, str]) -> None:
    assert_sensitive_placeholders(values)
    _prove_fernet_master_key_guard()


def _prove_fernet_master_key_guard() -> None:
    probe = {key: "CHANGE_ME_TEST_PLACEHOLDER" for key in SENSITIVE_PLACEHOLDERS}
    probe["PROVIDER_CONFIG_MASTER_KEY"] = (
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    )
    try:
        assert_sensitive_placeholders(probe)
    except AssertionError:
        return
    raise AssertionError(
        "real-looking Fernet PROVIDER_CONFIG_MASTER_KEY unexpectedly passed"
    )


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        text=False,
    )
    return [
        ROOT / item.decode("utf-8")
        for item in output.split(b"\0")
        if item
    ]


def main() -> None:
    values = parse_env(ENV_TEMPLATE)
    missing = sorted(REQUIRED_KEYS - values.keys())
    assert not missing, f"production env template missing keys: {missing}"

    assert values["APP_ENV"] == "production"
    assert values["ENABLE_DEV_AUTH"].lower() == "false"
    assert values["AUTO_CREATE_SCHEMA"].lower() == "false"
    assert values["AUTH_RATE_LIMIT_ENABLED"].lower() == "true"
    assert values["AUTH_EMAIL_DELIVERY_MODE"] == "smtp"
    assert values["AUTH_PUBLIC_BASE_URL"].startswith("https://")
    assert values["AUTH_SMTP_HOST"]
    assert values["AUTH_SMTP_FROM"]
    assert values["STORAGE_BACKEND"] == "s3"
    assert values["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert "@postgres:5432/" in values["DATABASE_URL"]
    assert values["STORAGE_ENDPOINT_URL"].startswith("https://")
    assert values["ASR_BASE_URL"].startswith("https://")
    assert values["AI_BASE_URL"].startswith("https://")
    assert values["EMBEDDING_BASE_URL"].startswith("https://")
    assert "localhost" not in values["API_DOMAIN"]
    assert "127.0.0.1" not in values["API_DOMAIN"]

    for key in SENSITIVE_PLACEHOLDERS:
        assert values[key].startswith("CHANGE_ME"), (
            f"{key} must remain a placeholder in the committed template"
        )

    assert not subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "backend/.env.production"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0, "backend/.env.production must never be tracked"

    secret_patterns = [
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"\bLTAI[A-Za-z0-9]{16,}\b"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
    ]
    excluded = {
        ROOT / "ops" / "validate-production-config.py",
    }
    findings: list[str] = []
    for path in tracked_files():
        if path in excluded or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in secret_patterns:
            if pattern.search(content):
                findings.append(f"{path.relative_to(ROOT)}: {pattern.pattern}")
    assert not findings, "possible committed secret material: " + ", ".join(findings)

    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert "5432:5432" not in compose
    assert 'ports:\n      - "8000:8000"' not in compose
    assert "service_completed_successfully" in compose
    assert "pgvector/pgvector:0.8.6-pg16-bookworm" in compose
    assert "${ENV_FILE:-./backend/.env.production}" in compose
    assert "APP_ENV: production" in compose
    assert 'ENABLE_DEV_AUTH: "false"' in compose
    assert 'AUTH_RATE_LIMIT_ENABLED: "true"' in compose
    assert 'AUTO_CREATE_SCHEMA: "false"' in compose
    assert "RELEASE_SHA: ${RELEASE_SHA:-unknown}" in compose

    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert "--reload" not in dockerfile
    assert "alembic upgrade" not in dockerfile
    assert "requirements.production.lock" in dockerfile
    assert "pip install --no-deps -r requirements.production.lock" in dockerfile
    assert "pip install ." not in dockerfile
    assert 'org.opencontainers.image.revision="$RELEASE_SHA"' in dockerfile

    print("production deployment static contract PASS")


if __name__ == "__main__":
    main()
