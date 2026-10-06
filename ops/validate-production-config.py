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
    "DB_POOL_SIZE",
    "DB_MAX_OVERFLOW",
    "DB_POOL_TIMEOUT_SECONDS",
    "DB_POOL_RECYCLE_SECONDS",
    "DB_CONNECTION_BUDGET",
    "API_REQUEST_BODY_LIMIT",
    "AUTH_RATE_LIMIT_ENABLED",
    "API_RATE_LIMIT_ENABLED",
    "API_NORMAL_USER_LIMIT",
    "API_NORMAL_IP_LIMIT",
    "API_MUTATION_USER_LIMIT",
    "API_MUTATION_IP_LIMIT",
    "API_MEDIA_USER_LIMIT",
    "API_MEDIA_IP_LIMIT",
    "API_EXPENSIVE_USER_LIMIT",
    "API_EXPENSIVE_IP_LIMIT",
    "API_EXPORT_USER_LIMIT",
    "API_EXPORT_IP_LIMIT",
    "API_RATE_WINDOW_SECONDS",
    "PROVIDER_AI_GLOBAL_CONCURRENCY",
    "PROVIDER_AI_USER_CONCURRENCY",
    "AI_IMAGE_PREPROCESS_GLOBAL_CONCURRENCY",
    "AI_IMAGE_PREPROCESS_USER_CONCURRENCY",
    "AI_IMAGE_PREPROCESS_PERMIT_LEASE_SECONDS",
    "PROVIDER_ASR_GLOBAL_CONCURRENCY",
    "PROVIDER_ASR_USER_CONCURRENCY",
    "PROVIDER_EMBEDDING_GLOBAL_CONCURRENCY",
    "PROVIDER_EMBEDDING_USER_CONCURRENCY",
    "PROVIDER_PERMIT_LEASE_SECONDS",
    "ARGON2_GLOBAL_CONCURRENCY",
    "ARGON2_PERMIT_LEASE_SECONDS",
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
    "BACKUP_OFFHOST_ENABLED",
    "BACKUP_STORAGE_BUCKET",
    "BACKUP_STORAGE_REGION",
    "BACKUP_STORAGE_ENDPOINT_URL",
    "BACKUP_STORAGE_ACCESS_KEY_ID",
    "BACKUP_STORAGE_SECRET_ACCESS_KEY",
    "BACKUP_STORAGE_ADDRESSING_STYLE",
    "BACKUP_OBJECT_PREFIX",
    "BACKUP_SOURCE_CLUSTER_ID",
    "BACKUP_RETENTION_DAILY",
    "BACKUP_RETENTION_WEEKLY",
    "BACKUP_RETENTION_MONTHLY",
    "MEDIA_MAX_IMAGE_BYTES",
    "MEDIA_MAX_AUDIO_BYTES",
    "EXPORT_BATCH_SIZE",
    "EXPORT_ARTIFACT_MAX_BYTES",
    "EXPORT_ARTIFACT_TTL_HOURS",
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
    "AI_IMAGE_MAX_BYTES",
    "AI_IMAGE_MAX_DIMENSION",
    "AI_IMAGE_MAX_PIXELS",
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
    "BACKUP_STORAGE_ACCESS_KEY_ID",
    "BACKUP_STORAGE_SECRET_ACCESS_KEY",
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
    for key in SENSITIVE_PLACEHOLDERS:
        assert values.get(key, "").startswith("CHANGE_ME"), (
            f"{key} must remain a placeholder in the committed template"
        )


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
    assert values["API_RATE_LIMIT_ENABLED"].lower() == "true"
    assert int(values["PROVIDER_AI_GLOBAL_CONCURRENCY"]) >= int(
        values["PROVIDER_AI_USER_CONCURRENCY"]
    )
    assert int(values["AI_IMAGE_PREPROCESS_GLOBAL_CONCURRENCY"]) >= int(
        values["AI_IMAGE_PREPROCESS_USER_CONCURRENCY"]
    )
    assert 1 <= int(values["AI_IMAGE_PREPROCESS_GLOBAL_CONCURRENCY"]) <= 64
    assert 5 <= int(values["AI_IMAGE_PREPROCESS_PERMIT_LEASE_SECONDS"]) <= 600
    assert int(values["PROVIDER_ASR_GLOBAL_CONCURRENCY"]) >= int(
        values["PROVIDER_ASR_USER_CONCURRENCY"]
    )
    assert int(values["PROVIDER_EMBEDDING_GLOBAL_CONCURRENCY"]) >= int(
        values["PROVIDER_EMBEDDING_USER_CONCURRENCY"]
    )
    assert int(values["ARGON2_GLOBAL_CONCURRENCY"]) >= 1
    assert values["AUTH_EMAIL_DELIVERY_MODE"] == "smtp"
    assert values["AUTH_PUBLIC_BASE_URL"].startswith("https://")
    assert values["AUTH_SMTP_HOST"]
    assert values["AUTH_SMTP_FROM"]
    assert values["STORAGE_BACKEND"] == "s3"
    assert values["BACKUP_OFFHOST_ENABLED"].lower() == "true"
    assert values["BACKUP_STORAGE_BUCKET"]
    assert values["BACKUP_STORAGE_REGION"]
    assert values["BACKUP_STORAGE_ENDPOINT_URL"].startswith("https://")
    assert values["BACKUP_STORAGE_ADDRESSING_STYLE"] in {"virtual", "path"}
    assert values["BACKUP_OBJECT_PREFIX"].strip("/")
    assert values["BACKUP_SOURCE_CLUSTER_ID"]
    assert int(values["BACKUP_RETENTION_DAILY"]) >= 1
    assert int(values["BACKUP_RETENTION_WEEKLY"]) >= 1
    assert int(values["BACKUP_RETENTION_MONTHLY"]) >= 1
    assert values["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert "@postgres:5432/" in values["DATABASE_URL"]
    pool_size = int(values["DB_POOL_SIZE"])
    max_overflow = int(values["DB_MAX_OVERFLOW"])
    pool_timeout = int(values["DB_POOL_TIMEOUT_SECONDS"])
    pool_recycle = int(values["DB_POOL_RECYCLE_SECONDS"])
    connection_budget = int(values["DB_CONNECTION_BUDGET"])
    web_concurrency = int(values["WEB_CONCURRENCY"])
    assert 1 <= pool_size <= 10
    assert 0 <= max_overflow <= 10
    assert 1 <= pool_timeout <= 30
    assert 30 <= pool_recycle <= 3600
    assert 4 <= connection_budget <= 64
    assert 1 <= web_concurrency <= 8
    assert (web_concurrency + 1) * (pool_size + max_overflow) <= connection_budget
    assert values["API_REQUEST_BODY_LIMIT"] == "2MB"
    assert values["STORAGE_ENDPOINT_URL"].startswith("https://")
    assert values["SECURITY_ALERT_HUMAN_PROVIDER"] == "feishu"
    webhook = values["SECURITY_ALERT_FEISHU_WEBHOOK_URL"]
    assert webhook.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/")
    assert "CHANGE_ME_SEC017_WEBHOOK_TOKEN" in webhook
    assert values["SECURITY_ALERT_FEISHU_SECRET"] == "CHANGE_ME_SEC017_SIGNING_SECRET"
    assert 1 <= float(values["SECURITY_ALERT_DELIVERY_TIMEOUT_SECONDS"]) <= 15
    assert 25 <= int(values["EXPORT_BATCH_SIZE"]) <= 1000
    export_artifact_max = int(values["EXPORT_ARTIFACT_MAX_BYTES"])
    assert 1024 * 1024 <= export_artifact_max <= 256 * 1024 * 1024
    assert 1 <= int(values["EXPORT_ARTIFACT_TTL_HOURS"]) <= 168
    assert values["ASR_BASE_URL"].startswith("https://")
    assert values["AI_BASE_URL"].startswith("https://")
    assert int(values["AI_IMAGE_MAX_BYTES"]) < int(values["MEDIA_MAX_IMAGE_BYTES"])
    assert 256 <= int(values["AI_IMAGE_MAX_DIMENSION"]) <= 8192
    assert 65_536 <= int(values["AI_IMAGE_MAX_PIXELS"]) <= 32_000_000
    assert int(values["AI_IMAGE_MAX_PIXELS"]) <= int(values["AI_IMAGE_MAX_DIMENSION"]) ** 2
    assert values["EMBEDDING_BASE_URL"].startswith("https://")
    assert "localhost" not in values["API_DOMAIN"]
    assert "127.0.0.1" not in values["API_DOMAIN"]

    assert_sensitive_placeholders(values)
    _prove_fernet_master_key_guard()

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
    assert "backup-ops:" in compose
    assert "backup-egress:" in compose
    assert 'profiles: ["ops"]' in compose
    assert 'x-bounded-logging: &bounded-logging' in compose
    assert 'driver: json-file' in compose
    assert 'max-size: "10m"' in compose
    assert 'max-file: "3"' in compose
    service_bodies: dict[str, str] = {}
    for service in ("postgres", "api", "worker", "reverse-proxy"):
        match = re.search(
            rf"(?ms)^  {re.escape(service)}:\n(?P<body>(?:^    .*\n|^\n)*)",
            compose,
        )
        assert match is not None, service
        service_bodies[service] = match.group("body")
        assert "logging: *bounded-logging" in match.group("body"), service

    export_temp_capacity = 320 * 1024 * 1024
    export_temp_headroom = 64 * 1024 * 1024
    assert "- /tmp:size=320m,mode=1777" in service_bodies["worker"]
    assert export_artifact_max + export_temp_headroom <= export_temp_capacity

    caddy = (ROOT / "ops" / "Caddyfile").read_text(encoding="utf-8")
    assert 'Strict-Transport-Security "max-age=31536000"' in caddy
    assert "preload" not in caddy
    assert 'X-Content-Type-Options "nosniff"' in caddy
    assert 'Referrer-Policy "strict-origin-when-cross-origin"' in caddy
    assert 'X-Frame-Options "DENY"' in caddy
    assert "respond /health/ready 404" in caddy
    assert "request_body {" in caddy
    assert "max_size {$API_REQUEST_BODY_LIMIT}" in caddy

    backup_service = (ROOT / "ops" / "systemd" / "jiyidashi-offhost-backup.service").read_text(
        encoding="utf-8"
    )
    backup_timer = (ROOT / "ops" / "systemd" / "jiyidashi-offhost-backup.timer").read_text(
        encoding="utf-8"
    )
    restore_service = (
        ROOT / "ops" / "systemd" / "jiyidashi-restore-drill.service"
    ).read_text(encoding="utf-8")
    restore_timer = (
        ROOT / "ops" / "systemd" / "jiyidashi-restore-drill.timer"
    ).read_text(encoding="utf-8")
    assert "Persistent=true" in backup_timer
    assert "OnCalendar=*-*-* 02:15:00 UTC" in backup_timer
    assert "Persistent=true" in restore_timer
    assert "OnCalendar=Sun *-*-* 04:15:00 UTC" in restore_timer
    assert "ops/offhost-backup.sh" in backup_service
    assert "ops/offhost-restore-drill.sh latest" in restore_service
    assert "jiyidashi-offhost-backup.lock" in backup_service
    assert "jiyidashi-offhost-backup.lock" in restore_service

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
