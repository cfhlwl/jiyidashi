#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-jiyidashi-backend}"
TARGET_SHA="${TARGET_SHA:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
API_BASE_URL="${API_BASE_URL:-}"

if [[ ! "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "TARGET_SHA must be a full immutable git SHA" >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production env: $ENV_FILE" >&2
  exit 2
fi
if [[ ! "$API_BASE_URL" =~ ^https:// ]]; then
  echo "API_BASE_URL=https://<API_DOMAIN> is required" >&2
  exit 2
fi

export ENV_FILE
export RELEASE_SHA="$TARGET_SHA"
export BACKEND_IMAGE="$IMAGE_REPOSITORY:$TARGET_SHA"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

echo "[1/8] validate exact release source and actual production env"
ROOT_DIR="$ROOT_DIR" TARGET_SHA="$TARGET_SHA" \
  bash "$ROOT_DIR/ops/validate-release-source.sh"
python3 "$ROOT_DIR/ops/validate-production-runtime.py" "$ENV_FILE"

echo "[2/8] validate production compose"
"${compose[@]}" config --quiet

echo "[3/8] build immutable backend image: $BACKEND_IMAGE"
"${compose[@]}" build api
bash "$ROOT_DIR/ops/verify-image-identity.sh" "$BACKEND_IMAGE" "$TARGET_SHA"

echo "[4/8] start PostgreSQL, back it up, then migrate"
ENV_FILE="$ENV_FILE" \
COMPOSE_FILE="$COMPOSE_FILE" \
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/postgres}" \
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}" \
  bash "$ROOT_DIR/ops/prepare-production-database.sh"

echo "[5/8] start API without re-running migration dependency"
"${compose[@]}" up -d --no-deps api
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" \
    >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
"${compose[@]}" exec -T api python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()" \
  >/dev/null

echo "[6/8] start HTTPS reverse proxy"
"${compose[@]}" up -d --no-deps reverse-proxy

echo "[7/8] production acceptance smoke"
API_BASE_URL="$API_BASE_URL" \
SMOKE_ACCESS_TOKEN="${SMOKE_ACCESS_TOKEN:-}" \
SMOKE_EMAIL="${SMOKE_EMAIL:-}" \
SMOKE_PASSWORD="${SMOKE_PASSWORD:-}" \
  bash "$ROOT_DIR/ops/smoke-production.sh"

echo "[8/8] deployment accepted: $BACKEND_IMAGE"
