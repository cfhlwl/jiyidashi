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
quiesce old worker + API
→ PostgreSQL healthy + pre-migration backup
→ one-shot migrate: alembic upgrade head
→ exact-SHA worker + schema health
→ exact-SHA API
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

Deployment tags the backend and Admin edge images with the full git SHA:

```text
jiyidashi-backend:<40-char-git-sha>
jiyidashi-edge:<40-char-git-sha>
```

The production Dockerfile:

- is built from a temporary `git archive <exact-sha> backend` export, so ignored/untracked workstation files cannot enter the Docker context;
- pins the exact Python 3.12 slim-bookworm base-image digest;
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
EDGE_IMAGE_REPOSITORY="registry.example.com/jiyidashi/edge" \
bash ops/deploy.sh
```

The script performs:

1. verify exact full git SHA and reject **tracked or untracked** release-source changes;
2. validate the actual production env and production Compose;
3. export the exact reviewed `backend/` Git tree and `admin/` + `ops/` edge tree with `git archive`, build/tag only from those clean trees, embed the SHA as the OCI revision label, and record/verify their `sha256` image IDs;
4. gracefully stop the old maintenance worker and API before any migration decision;
5. start PostgreSQL even if its container was stopped;
6. wait for PostgreSQL health and **always create the pre-migration backup** from the existing volume/data;
7. execute `alembic upgrade head` once only after that backup succeeds;
8. force-recreate the maintenance worker from the exact reviewed backend image, verify its OCI revision/image ID, and require `maintenance_worker --health` to report `schema=current`;
9. force-recreate the API from the same exact reviewed backend image and wait for internal `/health/ready`;
10. start Caddy with the built Admin Console at `/admin/` and run the external HTTPS/auth acceptance smoke.

A stopped PostgreSQL container is never treated as proof of a first deployment. Existing volumes
are brought up and backed up before migration.

A migration failure stops the release before the new API starts.

The Git SHA tag is a human release coordinate, while the Docker `sha256` image ID is the exact
built artifact identity. On first preparation of a SHA, `ops/prepare-release-image.sh` records
the exact image ID under `.ops-state/release-images/<sha>.image-id`. A later deployment of the
same SHA may reuse that exact local image, or rebuild only to recover the exact recorded image ID;
a different image for the same SHA fails closed instead of being adopted silently.

Rollback is intentionally local-artifact-only in OPS-001: it requires that recorded SHA→image-ID
mapping and will not pull a mutable registry tag during rollback. If release images are moved to a
registry later, that flow must use a registry digest (for example `repo@sha256:...`) as the
authoritative artifact identity rather than trusting a mutable SHA tag.

Do not reuse mutable `latest` as a release or rollback identity.

## HTTPS / reverse proxy

`ops/Caddyfile` uses `API_DOMAIN` and `ACME_EMAIL` from runtime environment. Caddy redirects HTTP to HTTPS, serves the built Admin Console at `/admin/`, routes `/admin/api/*` to `api:8000`, and reverse-proxies the public API to `api:8000`.

Caddy preserves standard forwarded headers. Uvicorn accepts those headers because direct public access to API port 8000 is absent. Do not publish port 8000 later without revisiting this trust boundary.

`GET /health` remains process liveness and must be reachable through the final HTTPS domain.

The API container healthcheck uses `GET /health/ready`, which performs only a database `SELECT 1`. It returns HTTP 503 with a generic body when the required database dependency is unavailable. Readiness deliberately does **not** call AI, ASR, embeddings or object storage.

Operational request/provider/storage/deletion telemetry is documented in `docs/PRODUCTION_OBSERVABILITY.md`. Production emits structured JSON events to stdout/stderr; no external telemetry SaaS is required by V1.

## Deployment acceptance

`ops/smoke-production.sh` requires an HTTPS origin and verifies:

```text
HTTPS /health = 200
internal /health/ready = 200 with database=ready
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

OPS-001 local dumps remain the pre-migration safety copy. They are **not** the sole
disaster-recovery authority after OPS-003. Production must also publish verified private
off-host copies and run scheduled restore drills as defined in
`docs/PRODUCTION_BACKUP.md`.

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

## Mobile push provider credentials

NOTIFY-001B keeps live APNs / FCM / HMS routing disabled until the final app identity is reviewed.
Do not turn on any mobile push provider while `PUSH_APP_IDENTITY_REVIEWED=false`.

The provider decision matrix, production fail-closed rules, and credential rotation/revocation
procedures are recorded in `docs/MOBILE_PUSH_PROVIDER_V1.md`. In particular:

- APNs private keys, FCM service-account private keys, and HMS client secrets remain server-only;
- rotate by installing replacement authority first, restarting provider processes so cached OAuth/JWT
  state is discarded, proving physical-device delivery, then revoking the superseded credential;
- on suspected compromise, disable the affected provider route before replacement/revocation work;
- never bind production credentials to the historical app identifier while APP-ID-001 is unresolved.

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
- [ ] mobile push APP-ID identity review completed before APNs/FCM/HMS enablement
- [ ] mobile push credential rotation/revocation plan recorded
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
- negative tests for unsafe **actual** production env values, including a short/weak `JWT_SECRET`;
- Compose hard runtime overrides for the four production invariants;
- custom `ENV_FILE` with no default env file present;
- exact production dependency lock parity;
- untracked source rejection;
- a Git-ignored `.key` probe placed under `backend/app/` is proven absent from the built image;
- production Docker image build + pinned base digest + OCI revision + recorded `sha256` image identity;
- same-SHA/different-image replacement is rejected and cannot be silently adopted;
- Compose render;
- Caddy static validation;
- disposable pgvector PostgreSQL;
- stopped existing PostgreSQL volume → start → backup → one-shot Alembic migration;
- restore of that pre-migration backup with marker-data verification;
- `alembic check` schema-drift check;
- execution of the real `ops/deploy.sh` from a running legacy worker/API release, proving quiesce-before-migration, exact-SHA worker/API replacement, no old process residue, and worker `schema=current`;
- API startup and internal `/health`;
- production `/v1/auth/dev-token=404`;
- custom-format backup;
- fresh-database restore smoke.

The existing backend CI remains the product regression suite.

## Out of scope

OPS-001 does not add Kubernetes, Terraform, autoscaling, HA PostgreSQL, multi-region, deployment SaaS, product behavior, Mini/Flutter features, V2-005 or AI semantics changes.
