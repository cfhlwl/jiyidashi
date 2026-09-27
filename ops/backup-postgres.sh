#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/backend/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups/postgres}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing production env: $ENV_FILE" >&2
  exit 2
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="$BACKUP_DIR/jiyidashi-$timestamp.dump"
tmp_path="$backup_path.tmp"
trap 'rm -f "$tmp_path"' EXIT

compose=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

# Password stays inside the postgres container environment; no secret is expanded
# into the host shell command/history.
"${compose[@]}" exec -T postgres sh -ceu '
  PGPASSWORD="$POSTGRES_PASSWORD"     pg_dump       --host=127.0.0.1       --username="$POSTGRES_USER"       --dbname="$POSTGRES_DB"       --format=custom       --no-owner       --no-acl
' >"$tmp_path"

test -s "$tmp_path"
mv "$tmp_path" "$backup_path"
chmod 600 "$backup_path"
trap - EXIT

find "$BACKUP_DIR" -type f -name 'jiyidashi-*.dump'   -mtime "+$BACKUP_RETENTION_DAYS" -delete

printf '%s\n' "$backup_path"
