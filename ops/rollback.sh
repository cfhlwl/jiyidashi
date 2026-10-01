#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-jiyidashi-backend}"
EDGE_IMAGE_REPOSITORY="${EDGE_IMAGE_REPOSITORY:-jiyidashi-edge}"
ROLLBACK_SHA="${1:-}"
API_BASE_URL="${API_BASE_URL:-}"

if [[ ! "$ROLLBACK_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <full-40-char-git-sha>" >&2
  exit 2
fi
if [[ "${CONFIRM_SCHEMA_COMPATIBLE:-}" != "yes" ]]; then
  echo "set CONFIRM_SCHEMA_COMPATIBLE=yes after confirming the current DB schema is backward-compatible" >&2
  exit 3
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
export RELEASE_SHA="$ROLLBACK_SHA"
export BACKEND_IMAGE="$IMAGE_REPOSITORY:$ROLLBACK_SHA"
export EDGE_IMAGE="$EDGE_IMAGE_REPOSITORY:$ROLLBACK_SHA"
python3 "$ROOT_DIR/ops/validate-production-runtime.py" "$ENV_FILE"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

# Rollback changes only the application image. It never runs alembic downgrade
# and never performs an automatic database restore. Rollback is intentionally
# local-artifact-only: resolving a mutable registry tag could silently replace
# the reviewed image for the same Git SHA.
RELEASE_IMAGE_STATE_DIR="${RELEASE_IMAGE_STATE_DIR:-$ROOT_DIR/.ops-state/release-images}" \
  bash "$ROOT_DIR/ops/verify-recorded-release-image.sh" "$BACKEND_IMAGE" "$ROLLBACK_SHA"
RELEASE_IMAGE_STATE_DIR="${RELEASE_IMAGE_STATE_DIR:-$ROOT_DIR/.ops-state/release-images}" \
  bash "$ROOT_DIR/ops/verify-recorded-release-image.sh" "$EDGE_IMAGE" "$ROLLBACK_SHA" edge

"${compose[@]}" up -d --no-deps api

for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T api python -c     "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"     >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

"${compose[@]}" up -d --no-deps reverse-proxy

API_BASE_URL="$API_BASE_URL" SMOKE_ACCESS_TOKEN="${SMOKE_ACCESS_TOKEN:-}" SMOKE_EMAIL="${SMOKE_EMAIL:-}" SMOKE_PASSWORD="${SMOKE_PASSWORD:-}"   bash "$ROOT_DIR/ops/smoke-production.sh"

echo "application rollback accepted: $BACKEND_IMAGE and $EDGE_IMAGE"
echo "database schema was NOT downgraded or restored"
