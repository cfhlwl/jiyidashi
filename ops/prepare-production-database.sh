#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/postgres}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_RECORD_FILE="${BACKUP_RECORD_FILE:-}"

export ENV_FILE

python3 "$ROOT_DIR/ops/validate-production-runtime.py" "$ENV_FILE"
compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

echo "quiesce maintenance worker and API before backup/migration"
"${compose[@]}" stop -t 90 worker api

echo "start PostgreSQL before any migration decision"
"${compose[@]}" up -d postgres

for _ in $(seq 1 60); do
  if "${compose[@]}" exec -T postgres sh -ceu     'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
"${compose[@]}" exec -T postgres sh -ceu   'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

echo "backup healthy PostgreSQL before migration"
backup_path="$(
  ENV_FILE="$ENV_FILE"   COMPOSE_FILE="$COMPOSE_FILE"   BACKUP_DIR="$BACKUP_DIR"   BACKUP_RETENTION_DAYS="$BACKUP_RETENTION_DAYS"     bash "$ROOT_DIR/ops/backup-postgres.sh"
)"
test -s "$backup_path"

if [[ -n "$BACKUP_RECORD_FILE" ]]; then
  printf '%s\n' "$backup_path" >"$BACKUP_RECORD_FILE"
fi

echo "run Alembic exactly once after backup"
"${compose[@]}" run --rm migrate

echo "database release preparation PASS"
echo "BACKUP_PATH=$backup_path"
