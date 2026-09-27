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
if [[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" != "$TARGET_SHA" ]]; then
  echo "checked-out HEAD does not match TARGET_SHA" >&2
  exit 2
fi
if ! git -C "$ROOT_DIR" diff --quiet || ! git -C "$ROOT_DIR" diff --cached --quiet; then
  echo "refusing deployment from a dirty tracked worktree" >&2
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

export BACKEND_IMAGE="$IMAGE_REPOSITORY:$TARGET_SHA"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

echo "[1/8] validate production compose"
"${compose[@]}" config --quiet

echo "[2/8] build immutable backend image: $BACKEND_IMAGE"
"${compose[@]}" build api

echo "[3/8] backup existing PostgreSQL when present"
if "${compose[@]}" ps --status running --services | grep -qx postgres; then
  ENV_FILE="$ENV_FILE" COMPOSE_FILE="$COMPOSE_FILE"     bash "$ROOT_DIR/ops/backup-postgres.sh"
else
  echo "first deployment: no running postgres service to back up"
fi

echo "[4/8] start PostgreSQL and wait for health"
"${compose[@]}" up -d postgres
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T postgres sh -ceu     'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
"${compose[@]}" exec -T postgres sh -ceu   'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

echo "[5/8] run Alembic exactly once for this release"
"${compose[@]}" run --rm migrate

echo "[6/8] start API without re-running migration dependency"
"${compose[@]}" up -d --no-deps api
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T api python -c     "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"     >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
"${compose[@]}" exec -T api python -c   "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"   >/dev/null

echo "[7/8] start HTTPS reverse proxy"
"${compose[@]}" up -d --no-deps reverse-proxy

echo "[8/8] production acceptance smoke"
API_BASE_URL="$API_BASE_URL" SMOKE_ACCESS_TOKEN="${SMOKE_ACCESS_TOKEN:-}" SMOKE_EMAIL="${SMOKE_EMAIL:-}" SMOKE_PASSWORD="${SMOKE_PASSWORD:-}"   bash "$ROOT_DIR/ops/smoke-production.sh"

echo "deployment accepted: $BACKEND_IMAGE"
