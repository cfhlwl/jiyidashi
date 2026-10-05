#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
BACKUP_LOCAL_STAGING_DIR="${BACKUP_LOCAL_STAGING_DIR:-$ROOT_DIR/backups/offhost-staging}"
BACKUP_LOCAL_RETENTION_MINUTES="${BACKUP_LOCAL_RETENTION_MINUTES:-1440}"
BACKUP_LOCK_FILE="${BACKUP_LOCK_FILE:-/var/lock/jiyidashi-offhost-backup.lock}"
BACKUP_SLOT="${BACKUP_SLOT:-$(date -u +%F)}"

if [[ ! "$BACKUP_SLOT" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "BACKUP_SLOT must be YYYY-MM-DD" >&2
  exit 2
fi
if [[ ! "$BACKUP_LOCAL_RETENTION_MINUTES" =~ ^[0-9]+$ ]] \
  || (( BACKUP_LOCAL_RETENTION_MINUTES < 1 )); then
  echo "BACKUP_LOCAL_RETENTION_MINUTES must be >= 1" >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production env: $ENV_FILE" >&2
  exit 2
fi

mkdir -p "$(dirname "$BACKUP_LOCK_FILE")" "$BACKUP_LOCAL_STAGING_DIR"
chmod 700 "$BACKUP_LOCAL_STAGING_DIR"
exec 9>"$BACKUP_LOCK_FILE"
if ! flock -n 9; then
  echo "off-host backup already running" >&2
  exit 75
fi

python3 "$ROOT_DIR/ops/validate-production-runtime.py" "$ENV_FILE"

export ENV_FILE
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

"${compose[@]}" up -d postgres
for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T postgres sh -ceu \
    'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then

    break
  fi
  sleep 2
done
"${compose[@]}" exec -T postgres sh -ceu \
  'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

# Timers do not inherit deploy-shell variables. Reuse the exact immutable image
# already running for API/worker unless the operator/CI explicitly supplied one.
if [[ -z "${BACKEND_IMAGE:-}" ]]; then
  runtime_cid="$("${compose[@]}" ps -q api 2>/dev/null || true)"
  if [[ -z "$runtime_cid" ]]; then
    runtime_cid="$("${compose[@]}" ps -q worker 2>/dev/null || true)"
  fi
  if [[ -z "$runtime_cid" ]]; then
    echo "BACKEND_IMAGE is unset and no running api/worker image can be resolved" >&2
    exit 3
  fi
  BACKEND_IMAGE="$(docker inspect "$runtime_cid" --format '{{.Config.Image}}')"
  export BACKEND_IMAGE
fi


find "$BACKUP_LOCAL_STAGING_DIR" \
  -type f -name 'jiyidashi-*.dump' \
  -mmin "+$BACKUP_LOCAL_RETENTION_MINUTES" -delete

dump_path="$(
  ENV_FILE="$ENV_FILE" \
  COMPOSE_FILE="$COMPOSE_FILE" \
  BACKUP_DIR="$BACKUP_LOCAL_STAGING_DIR" \
  BACKUP_RETENTION_DAYS=2 \
    bash "$ROOT_DIR/ops/backup-postgres.sh"
)"
test -s "$dump_path"

cleanup_dump() {
  rm -f "$dump_path"
}
trap cleanup_dump EXIT

schema_revision="$(
  "${compose[@]}" exec -T postgres sh -ceu '
    PGPASSWORD="$POSTGRES_PASSWORD" psql \
      --host=127.0.0.1 \
      --username="$POSTGRES_USER" \
      --dbname="$POSTGRES_DB" \
      --tuples-only --no-align \
      --command="SELECT version_num FROM alembic_version LIMIT 1;"
  ' | tr -d '[:space:]'
)"
if [[ -z "$schema_revision" ]]; then
  echo "unable to determine Alembic revision" >&2
  exit 3
fi

pg_dump_version="$(
  "${compose[@]}" exec -T postgres pg_dump --version | tr -d '\r\n'
)"
release_revision="${RELEASE_SHA:-}"
if [[ -z "$release_revision" || "$release_revision" == "unknown" ]]; then
  api_cid="$("${compose[@]}" ps -q api 2>/dev/null || true)"
  if [[ -n "$api_cid" ]]; then
    release_revision="$(
      docker inspect "$api_cid" \
        --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
        2>/dev/null || true
    )"
  fi
fi
release_revision="${release_revision:-unknown}"

run_args=(
  run --rm --no-deps
  --user "$(id -u):$(id -g)"
  -v "$BACKUP_LOCAL_STAGING_DIR:/backup-staging:rw"
)
module_args=()
if [[ -n "${BACKUP_TEST_FAKE_ROOT:-}" ]]; then
  if [[ "${CI:-}" != "true" ]]; then
    echo "BACKUP_TEST_FAKE_ROOT is CI-only" >&2
    exit 3
  fi
  mkdir -p "$BACKUP_TEST_FAKE_ROOT"
  run_args+=(-v "$BACKUP_TEST_FAKE_ROOT:/backup-fake:rw")
  module_args+=(--test-filesystem-root /backup-fake)
fi

backup_id="pg-$BACKUP_SLOT"
scheduled_slot="${BACKUP_SLOT}T00:00:00Z"
dump_name="$(basename "$dump_path")"

"${compose[@]}" "${run_args[@]}" backup-ops \
  python -m app.offhost_backup "${module_args[@]}" publish \
  --dump "/backup-staging/$dump_name" \
  --backup-id "$backup_id" \
  --scheduled-slot "$scheduled_slot" \
  --release-revision "$release_revision" \
  --schema-revision "$schema_revision" \
  --pg-dump-version "$pg_dump_version"

"${compose[@]}" "${run_args[@]}" backup-ops \
  python -m app.offhost_backup "${module_args[@]}" retention

rm -f "$dump_path"
trap - EXIT
echo "off-host backup PASS: $backup_id"
