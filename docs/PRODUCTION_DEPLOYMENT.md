# JiYiDashi Production Deployment V1

This runbook is the reviewed **single-server** production baseline for OPS-001. It does not define Kubernetes, Terraform, HA PostgreSQL, multi-region deployment, or any product feature.

## Architecture

```text
Internet
  │  HTTPS only
  ▼
Caddy :443/:80 redirect
  │  private Docker backend network
  ▼
api:8000
  │
  ├── postgres:5432 (private, pgvector PostgreSQL 16)
  └── private S3-compatible COS/OSS via signed URLs

release:
postgres healthy
→ one-shot migrate: alembic upgrade head
→ api
→ HTTPS smoke
```

Only Caddy publishes host ports. PostgreSQL and API use the internal Docker network and must not be exposed by host firewall/NAT rules.

## Host prerequisites

- Linux server with Docker Engine and Docker Compose V2.
- Public DNS A/AAAA for `API_DOMAIN` pointed at the server.
- TCP 80/443 reachable for Caddy ACME; UDP 443 is optional HTTP/3.
- A private S3-compatible COS/OSS bucket.
- A production smoke account or short-lived authenticated smoke token.
- Sufficient disk for PostgreSQL volume, Caddy state, image versions and local backup retention.

## Production environment

Copy the committed template and edit only the untracked copy:

```bash
cp backend/.env.production.example backend/.env.production
chmod 600 backend/.env.production
```

Never commit `backend/.env.production`.

Hard production locks:

```text
APP_ENV=production
ENABLE_DEV_AUTH=false
AUTH_RATE_LIMIT_ENABLED=true
AUTO_CREATE_SCHEMA=false
JWT_SECRET >= 32 random bytes
DATABASE_URL -> postgres service
STORAGE_BACKEND=s3
STORAGE_ENDPOINT_URL=https://...
AI/ASR/Embedding custom endpoints -> HTTPS when enabled
```

These four application invariants are enforced twice: `ops/validate-production-runtime.py`
validates the **actual server ENV_FILE**, and production Compose explicitly overrides the same
four values for `api` and `migrate`. Editing a real env file to development/unsafe values
therefore fails deployment preflight and cannot weaken the container runtime.

All deployment scripts export the same `ENV_FILE` into Compose. A custom absolute env path is
therefore the single source for both Compose interpolation and the API/migrate `env_file`;
there is no hidden fallback to `backend/.env.production`.

`POSTGRES_PASSWORD` is the PostgreSQL container credential. The password embedded in `DATABASE_URL` must represent the same value and must be URL-encoded when it contains reserved URI characters.

Provider keys are server-only. They are never copied into Mini Program or Flutter configuration.

## Build and immutable release images

Deployment tags the backend image with the full git SHA:

```text
jiyidashi-backend:<40-char-git-sha>
```

The production Dockerfile:

- uses Python 3.12;
- installs the complete exact-version `backend/requirements.production.lock`;
- does not resolve `pyproject.toml` version ranges during an image build;
- validates the installed frozen graph with `pip check`;
- excludes pytest/pytest-asyncio/ruff from the production lock;
- runs as non-root UID/GID 10001;
- does not copy tests, `.env`, Git metadata or local DB files;
- does not run migrations during image build/startup;
- runs Uvicorn without reload;
- trusts proxy headers because API port 8000 is not publicly published and only the internal Caddy path reaches it.

Run the static contract check before deployment:

```bash
python3 ops/validate-production-config.py
docker compose --env-file backend/.env.production -f docker-compose.prod.yml config --quiet
```

## Release procedure

Set acceptance credentials and the external HTTPS origin, then deploy the checked-out immutable commit:

```bash
export API_BASE_URL="https://api.example.com"
export SMOKE_EMAIL="deployment-smoke@example.com"
export SMOKE_PASSWORD="..."
# or export SMOKE_ACCESS_TOKEN="..."

TARGET_SHA="$(git rev-parse HEAD)" \
IMAGE_REPOSITORY="registry.example.com/jiyidashi/backend" \
bash ops/deploy.sh
```

The script performs:

1. verify exact full git SHA and reject **tracked or untracked** release-source changes;
2. validate the actual production env and production Compose;
3. build/tag the backend image by immutable SHA, embed the SHA as the OCI revision label, and record/verify its `sha256` image ID;
4. start PostgreSQL even if its container was stopped;
5. wait for PostgreSQL health and **always create the pre-migration backup** from the existing volume/data;
6. execute `alembic upgrade head` once only after that backup succeeds;
7. start API without re-running migration dependency and wait for internal `/health`;
8. start Caddy and run the external HTTPS/auth acceptance smoke.

A stopped PostgreSQL container is never treated as proof of a first deployment. Existing volumes
are brought up and backed up before migration.

A migration failure stops the release before the new API starts.

The Git SHA tag is a human release coordinate, while the Docker `sha256` image ID is the exact
built artifact identity. Release logs must retain both. Rollback validates that the selected
image carries the expected OCI git revision and a real `sha256` image ID.

For registry-backed deployment, push the reviewed immutable image through your normal registry credentials after build and before remote rollout. Do not reuse mutable `latest` as the rollback identity.

## HTTPS / reverse proxy

`ops/Caddyfile` uses `API_DOMAIN` and `ACME_EMAIL` from runtime environment. Caddy redirects HTTP to HTTPS and reverse-proxies to `api:8000`.

Caddy preserves standard forwarded headers. Uvicorn accepts those headers because direct public access to API port 8000 is absent. Do not publish port 8000 later without revisiting this trust boundary.

`GET /health` must be reachable through the final HTTPS domain. Health does **not** call AI, ASR, embeddings or object storage.

## Deployment acceptance

`ops/smoke-production.sh` requires an HTTPS origin and verifies:

```text
HTTPS /health = 200
POST /v1/auth/dev-token = 404
register route reachable
login route reachable
invalid Bearer token fails closed
authenticated GET /v1/user = 200
```

Use either `SMOKE_ACCESS_TOKEN` or `SMOKE_EMAIL + SMOKE_PASSWORD`.

External provider checks are separate operational acceptance and are intentionally not required in CI:

- signed image PUT + completion + READY;
- voice ASR;
- AI query/summary;
- embedding/RAG.

## PostgreSQL backup

Default local retention is 14 days and can be changed with `BACKUP_RETENTION_DAYS`.

```bash
BACKUP_DIR=/srv/jiyidashi/backups \
BACKUP_RETENTION_DAYS=14 \
bash ops/backup-postgres.sh
```

The script uses PostgreSQL **custom format**, UTC timestamped names, `set -Eeuo pipefail`, atomic temp-file publish and mode 0600. The password is read inside the PostgreSQL container environment rather than expanded into host shell history.

A successful dump alone is **not** proof of a valid backup.

## Restore smoke

Restore only into a fresh non-production database:

```bash
RESTORE_DATABASE=jiyidashi_restore_20260927 \
bash ops/restore-postgres.sh /srv/jiyidashi/backups/jiyidashi-YYYYMMDDTHHMMSSZ.dump
```

The restore script refuses `RESTORE_DATABASE == POSTGRES_DB`, recreates only the named test database, runs `pg_restore`, then verifies `SELECT 1`.

Perform scheduled restore drills and record the backup file, restore database, timestamp and result.

## Rollback

Application rollback is image-only:

```bash
export API_BASE_URL="https://api.example.com"
export CONFIRM_SCHEMA_COMPATIBLE=yes
bash ops/rollback.sh <previous-40-char-git-sha>
```

Before setting `CONFIRM_SCHEMA_COMPATIBLE=yes`, confirm the current production DB schema is backward-compatible with the target application image.

Rollback **never** runs `alembic downgrade` and never performs automatic destructive database restore. If a future migration is not backward-compatible, that release must define its migration rollback/forward-fix plan before production. Backups are the disaster-recovery boundary, not an automatic release rollback mechanism.

## Object storage security

Production media storage remains private:

- bucket/container ACL is private;
- access key/secret exist only on the server;
- clients receive only short-lived signed PUT/GET capabilities;
- there is no public permanent media URL;
- production custom storage endpoint must be HTTPS;
- rotate credentials by creating a new provider credential, updating the untracked production env, restarting API, verifying signed PUT/GET, then revoking the old credential.

Do not proxy signed object uploads through the backend to avoid platform domain configuration.

## WeChat Mini Program production contract

Production Mini build already rejects localhost and non-HTTPS API bases:

```bash
JIYI_API_BASE_URL="https://api.example.com" npm run build:weapp
```

WeChat admin must whitelist **both** request domains:

1. the API domain used by `JIYI_API_BASE_URL`;
2. the actual COS/OSS domain contained in signed PUT URLs.

If storage moves to another endpoint/custom domain/CDN, update the WeChat legal-domain configuration and re-run real-device acceptance. Direct client → private object storage signed PUT remains the intended architecture.

See also `docs/MINIPROGRAM_DEPLOYMENT_ACCEPTANCE.md`.

## Security checklist

Before production acceptance:

- [ ] `APP_ENV=production`
- [ ] `ENABLE_DEV_AUTH=false`
- [ ] `AUTH_RATE_LIMIT_ENABLED=true`
- [ ] `AUTO_CREATE_SCHEMA=false`
- [ ] strong random `JWT_SECRET`
- [ ] only Caddy publishes public ports
- [ ] PostgreSQL has no public host port
- [ ] API port 8000 has no public host port
- [ ] private object-storage bucket
- [ ] provider keys exist only on server
- [ ] HTTPS `/health` passes
- [ ] dev-auth negative smoke passes
- [ ] authenticated `/v1/user` smoke passes
- [ ] backup created
- [ ] fresh-database restore smoke passes
- [ ] immutable release SHA recorded
- [ ] rollback compatibility decision recorded

## CI coverage

`production-deployment-ci` validates without a public server or paid providers:

- production env/template static security contract;
- negative tests for unsafe **actual** production env values;
- Compose hard runtime overrides for the four production invariants;
- custom `ENV_FILE` with no default env file present;
- exact production dependency lock parity;
- untracked source rejection;
- production Docker image build + OCI revision + `sha256` image identity;
- Compose render;
- Caddy static validation;
- disposable pgvector PostgreSQL;
- stopped existing PostgreSQL volume → start → backup → one-shot Alembic migration;
- restore of that pre-migration backup with marker-data verification;
- `alembic check` schema-drift check;
- API startup and internal `/health`;
- production `/v1/auth/dev-token=404`;
- custom-format backup;
- fresh-database restore smoke.

The existing backend CI remains the product regression suite.

## Out of scope

OPS-001 does not add Kubernetes, Terraform, autoscaling, HA PostgreSQL, multi-region, deployment SaaS, product behavior, Mini/Flutter features, V2-005 or AI semantics changes.
