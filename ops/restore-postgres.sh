#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
BACKUP_FILE="${1:-}"
RESTORE_DATABASE="${RESTORE_DATABASE:-jiyidashi_restore_smoke}"

if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
  echo "usage: RESTORE_DATABASE=<fresh-db> $0 /path/to/backup.dump" >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production env: $ENV_FILE" >&2
  exit 2
fi

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
production_db="$("${compose[@]}" exec -T postgres sh -ceu 'printf %s "$POSTGRES_DB"')"

if [[ "$RESTORE_DATABASE" == "$production_db" ]]; then
  echo "refusing to restore over the production database" >&2
  exit 3
fi
if [[ ! "$RESTORE_DATABASE" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "RESTORE_DATABASE may contain only letters, digits and underscore" >&2
  exit 3
fi

"${compose[@]}" exec -T postgres sh -ceu "
  PGPASSWORD=\"\$POSTGRES_PASSWORD\" dropdb     --host=127.0.0.1 --username=\"\$POSTGRES_USER\"     --if-exists '$RESTORE_DATABASE'
  PGPASSWORD=\"\$POSTGRES_PASSWORD\" createdb     --host=127.0.0.1 --username=\"\$POSTGRES_USER\"     '$RESTORE_DATABASE'
"

cat "$BACKUP_FILE" | "${compose[@]}" exec -T postgres sh -ceu "
  PGPASSWORD=\"\$POSTGRES_PASSWORD\" pg_restore     --host=127.0.0.1     --username=\"\$POSTGRES_USER\"     --dbname='$RESTORE_DATABASE'     --no-owner     --no-acl
"

"${compose[@]}" exec -T postgres sh -ceu "
  PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql     --host=127.0.0.1     --username=\"\$POSTGRES_USER\"     --dbname='$RESTORE_DATABASE'     --tuples-only --no-align     --command='SELECT 1'
" | grep -qx '1'

echo "restore smoke PASS: $RESTORE_DATABASE"
