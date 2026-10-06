#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-jiyidashi-backend}"
EDGE_IMAGE_REPOSITORY="${EDGE_IMAGE_REPOSITORY:-jiyidashi-edge}"
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
export EDGE_IMAGE="$EDGE_IMAGE_REPOSITORY:$TARGET_SHA"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

verify_backend_service_release() {
  local service="$1"
  local container_id expected_image_id actual_image_id revision

  container_id="$("${compose[@]}" ps -q "$service")"
  if [[ -z "$container_id" ]]; then
    echo "$service container is not running" >&2
    exit 5
  fi
  expected_image_id="$(docker image inspect "$BACKEND_IMAGE" --format '{{.Id}}')"
  actual_image_id="$(docker inspect "$container_id" --format '{{.Image}}')"
  revision="$(
    docker inspect "$container_id" \
      --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
  )"
  if [[ "$actual_image_id" != "$expected_image_id" || "$revision" != "$TARGET_SHA" ]]; then
    echo "$service is not running the exact reviewed backend release" >&2
    exit 5
  fi
}

echo "[1/11] validate exact release source and actual production env"
ROOT_DIR="$ROOT_DIR" TARGET_SHA="$TARGET_SHA" \
  bash "$ROOT_DIR/ops/validate-release-source.sh"
python3 "$ROOT_DIR/ops/validate-production-runtime.py" "$ENV_FILE"

echo "[2/11] validate production compose"
"${compose[@]}" config --quiet

echo "[3/11] prepare immutable backend image: $BACKEND_IMAGE"
RELEASE_IMAGE_STATE_DIR="${RELEASE_IMAGE_STATE_DIR:-$ROOT_DIR/.ops-state/release-images}" \
  bash "$ROOT_DIR/ops/prepare-release-image.sh" "$BACKEND_IMAGE" "$TARGET_SHA"

echo "[4/11] prepare immutable admin edge image: $EDGE_IMAGE"
RELEASE_IMAGE_STATE_DIR="${RELEASE_IMAGE_STATE_DIR:-$ROOT_DIR/.ops-state/release-images}" \
  bash "$ROOT_DIR/ops/prepare-release-image.sh" "$EDGE_IMAGE" "$TARGET_SHA" edge

echo "[5/11] quiesce old worker/API, back up PostgreSQL, then migrate"
ENV_FILE="$ENV_FILE" \
COMPOSE_FILE="$COMPOSE_FILE" \
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/postgres}" \
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}" \
  bash "$ROOT_DIR/ops/prepare-production-database.sh"

echo "[6/11] start exact-SHA maintenance worker"
"${compose[@]}" up -d --no-deps --force-recreate worker
worker_health="$(mktemp)"
trap 'rm -f "$worker_health"' EXIT
for _ in $(seq 1 30); do
  if "${compose[@]}" exec -T worker python -m app.maintenance_worker --health \
    >"$worker_health" 2>/dev/null; then
    break
  fi
  sleep 2
done
python3 - "$worker_health" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
assert body["status"] == "ready", body
assert body["schema"] == "current", body
PY
verify_backend_service_release worker
rm -f "$worker_health"
trap - EXIT

echo "[7/11] start exact-SHA API without re-running migration dependency"
"${compose[@]}" up -d --no-deps --force-recreate api
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()" \
    >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
"${compose[@]}" exec -T api python -c \
  "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()" \
  >/dev/null
verify_backend_service_release api

echo "[8/11] start HTTPS reverse proxy and Admin Console"
"${compose[@]}" up -d --no-deps --force-recreate reverse-proxy

echo "[9/11] production acceptance smoke"
if [[ "${DEPLOY_CI_SKIP_EXTERNAL_SMOKE:-false}" == "true" ]]; then
  if [[ "${CI:-}" != "true" ]]; then
    echo "DEPLOY_CI_SKIP_EXTERNAL_SMOKE is CI-only" >&2
    exit 2
  fi
  echo "CI-only external smoke bypass; cutover/runtime gates still executed"
else
  API_BASE_URL="$API_BASE_URL" \
  SMOKE_ACCESS_TOKEN="${SMOKE_ACCESS_TOKEN:-}" \
  SMOKE_EMAIL="${SMOKE_EMAIL:-}" \
  SMOKE_PASSWORD="${SMOKE_PASSWORD:-}" \
    bash "$ROOT_DIR/ops/smoke-production.sh"
fi

echo "[10/11] verify final backend services remain on exact release"
verify_backend_service_release worker
verify_backend_service_release api

echo "[11/11] deployment accepted: $BACKEND_IMAGE and $EDGE_IMAGE"

