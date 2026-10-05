#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
BACKUP_LOCAL_STAGING_DIR="${BACKUP_LOCAL_STAGING_DIR:-$ROOT_DIR/backups/offhost-restore}"
BACKUP_LOCK_FILE="${BACKUP_LOCK_FILE:-/var/lock/jiyidashi-offhost-backup.lock}"
BACKUP_ID="${1:-latest}"
BACKUP_RESTORE_RETAIN="${BACKUP_RESTORE_RETAIN:-false}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production env: $ENV_FILE" >&2
  exit 2
fi

mkdir -p "$(dirname "$BACKUP_LOCK_FILE")" "$BACKUP_LOCAL_STAGING_DIR"
chmod 700 "$BACKUP_LOCAL_STAGING_DIR"
exec 9>"$BACKUP_LOCK_FILE"
if ! flock -n 9; then
  echo "backup or restore operation already running" >&2
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
  runtime_cid="$("${compose[@]}" ps -a -q api 2>/dev/null || true)"
  if [[ -z "$runtime_cid" ]]; then
    runtime_cid="$("${compose[@]}" ps -a -q worker 2>/dev/null || true)"
  fi
  if [[ -z "$runtime_cid" ]]; then
    echo "BACKEND_IMAGE is unset and no running api/worker image can be resolved" >&2
    exit 3
  fi
  BACKEND_IMAGE="$(docker inspect "$runtime_cid" --format '{{.Config.Image}}')"
  export BACKEND_IMAGE
fi


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

if [[ "$BACKUP_ID" == "latest" ]]; then
  BACKUP_ID="$(
    "${compose[@]}" "${run_args[@]}" backup-ops \
      python -m app.offhost_backup "${module_args[@]}" latest
  )"
fi
if [[ ! "$BACKUP_ID" =~ ^pg-[0-9]{4}-[0-9]{2}-[0-9]{2}(-[A-Za-z0-9._-]+)?$ ]]; then
  echo "invalid backup id" >&2
  exit 3
fi

dump_path="$BACKUP_LOCAL_STAGING_DIR/$BACKUP_ID.dump"
manifest_path="$BACKUP_LOCAL_STAGING_DIR/$BACKUP_ID.manifest.json"
rm -f "$dump_path" "$manifest_path" "$dump_path.partial"

"${compose[@]}" "${run_args[@]}" backup-ops \
  python -m app.offhost_backup "${module_args[@]}" fetch \
  --backup-id "$BACKUP_ID" \
  --output "/backup-staging/$BACKUP_ID.dump" \
  --manifest-output "/backup-staging/$BACKUP_ID.manifest.json"

test -s "$dump_path"
test -s "$manifest_path"

manifest_schema_revision="$(
  python3 - "$manifest_path" <<'PY'
import json
import sys

body = json.load(open(sys.argv[1], encoding="utf-8"))
value = body.get("schema_revision")
if not isinstance(value, str) or not value:
    raise SystemExit("manifest schema revision missing")
print(value)
PY
)"

suffix="$(date -u +%Y%m%d%H%M%S)-$$"
restore_database="jiyi_ops003_restore_${suffix//[^A-Za-z0-9_]/_}"
created_restore=false

cleanup() {
  rm -f "$dump_path" "$manifest_path" "$dump_path.partial"
  if [[ "$created_restore" == "true" && "$BACKUP_RESTORE_RETAIN" != "true" ]]; then
    "${compose[@]}" exec -T postgres sh -ceu "
      PGPASSWORD="\$POSTGRES_PASSWORD" dropdb \
        --host=127.0.0.1 \
        --username="\$POSTGRES_USER" \
        --if-exists '$restore_database'
    " >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

created_restore=true
ENV_FILE="$ENV_FILE" \
COMPOSE_FILE="$COMPOSE_FILE" \
RESTORE_DATABASE="$restore_database" \
  bash "$ROOT_DIR/ops/restore-postgres.sh" "$dump_path"

restored_revision="$(
  "${compose[@]}" exec -T postgres sh -ceu "
    PGPASSWORD="\$POSTGRES_PASSWORD" psql \
      --host=127.0.0.1 \
      --username="\$POSTGRES_USER" \
      --dbname='$restore_database' \
      --tuples-only --no-align \
      --command="SELECT MIN(version_num) FROM alembic_version HAVING COUNT(*) = 1;"
  " | tr -d '[:space:]'
)"
if [[ "$restored_revision" != "$manifest_schema_revision" ]]; then
  echo "restored Alembic revision does not match manifest" >&2
  exit 4
fi

"${compose[@]}" run --rm --no-deps \
  -e "RESTORE_DATABASE=$restore_database" api sh -ceu '
    restored_url="$(
      python -c '"'"'
import os
from sqlalchemy.engine import make_url
url = make_url(os.environ["DATABASE_URL"]).set(database=os.environ["RESTORE_DATABASE"])
print(url.render_as_string(hide_password=False))
'"'"'
    )"
    export DATABASE_URL="$restored_url"
    alembic upgrade head
    alembic check
  '

table_count="$(
  "${compose[@]}" exec -T postgres sh -ceu "
    PGPASSWORD="\$POSTGRES_PASSWORD" psql \
      --host=127.0.0.1 \
      --username="\$POSTGRES_USER" \
      --dbname='$restore_database' \
      --tuples-only --no-align \
      --command="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';"
  " | tr -d '[:space:]'
)"
if [[ ! "$table_count" =~ ^[0-9]+$ ]] || (( table_count < 1 )); then
  echo "restored database has no public schema tables" >&2
  exit 4
fi

user_count="$(
  "${compose[@]}" exec -T postgres sh -ceu "
    PGPASSWORD="\$POSTGRES_PASSWORD" psql \
      --host=127.0.0.1 \
      --username="\$POSTGRES_USER" \
      --dbname='$restore_database' \
      --tuples-only --no-align \
      --command='SELECT COUNT(*) FROM users;'
  " | tr -d '[:space:]'
)"
if [[ ! "$user_count" =~ ^[0-9]+$ ]]; then
  echo "restored users table is unreadable" >&2
  exit 4
fi

echo "off-host restore drill PASS: $BACKUP_ID -> $restore_database"

if [[ "$BACKUP_RESTORE_RETAIN" != "true" ]]; then
  "${compose[@]}" exec -T postgres sh -ceu "
    PGPASSWORD="\$POSTGRES_PASSWORD" dropdb \
      --host=127.0.0.1 \
      --username="\$POSTGRES_USER" \
      --if-exists '$restore_database'
  "
  created_restore=false
fi

rm -f "$dump_path" "$manifest_path" "$dump_path.partial"
trap - EXIT
