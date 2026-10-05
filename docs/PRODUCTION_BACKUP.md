# JiYiDashi Production Off-host Backup V1

This runbook defines the OPS-003 disaster-recovery baseline for the current single-host
production topology. PostgreSQL local dumps remain useful migration safety copies, but they are
not disaster-recovery authority. A backup is disaster-recovery valid only after its verified
off-host manifest is published.

## Architecture

```text
production PostgreSQL
→ pg_dump custom format
→ short-lived local staging file
→ SHA-256 + operational manifest
→ private S3-compatible COS/OSS backup bucket
→ verified/<backup-id>/database.dump
→ verified/<backup-id>/manifest.json published last
→ daily/weekly/monthly retention
→ weekly isolated restore drill
```

The local filesystem is staging/cache only. The final manifest is the publication authority:
a dump without its canonical final manifest is incomplete and must not be selected for restore.

## Required private bucket configuration

Use a bucket/container dedicated to database backups where practical.

Required provider controls:

- Bucket ACL/public access: **private only**. Public-read/public-list must be disabled.
- Default encryption at rest: provider-managed server-side encryption enabled.
  - S3-compatible setting: `AES256` / SSE-S3 equivalent.
  - Tencent COS equivalent: provider-managed SSE-COS.
  - Alibaba OSS equivalent: SSE-OSS with AES256/provider-managed key.
- Do not enable a public website endpoint or permanent public object URL for this bucket.
- Credentials should be scoped to this backup bucket and `BACKUP_OBJECT_PREFIX` only.
- Required object permissions are list/head/get/put/copy/delete within that prefix.
- Do not grant ACL-management/publication permissions unless the provider requires them.
- Provider versioning may be enabled, but OPS-003 correctness does not depend on it.

OPS-003 does not add application-side encryption. Introducing a second application-managed
encryption key without a separately reviewed recovery/rotation authority would make disaster
recovery easier to lose than to protect.

## Production environment

The real untracked `backend/.env.production` must contain:

```text
BACKUP_OFFHOST_ENABLED=true
BACKUP_STORAGE_BUCKET=<private backup bucket>
BACKUP_STORAGE_REGION=<provider region>
BACKUP_STORAGE_ENDPOINT_URL=https://<private-compatible endpoint>
BACKUP_STORAGE_ACCESS_KEY_ID=<server-only credential>
BACKUP_STORAGE_SECRET_ACCESS_KEY=<server-only credential>
BACKUP_STORAGE_ADDRESSING_STYLE=virtual
BACKUP_OBJECT_PREFIX=postgresql-backups
BACKUP_SOURCE_CLUSTER_ID=<stable non-secret cluster id>
BACKUP_RETENTION_DAILY=14
BACKUP_RETENTION_WEEKLY=8
BACKUP_RETENTION_MONTHLY=12
```

`BACKUP_SOURCE_CLUSTER_ID` is a stable operational label such as
`prod-primary-sg-01`; it must not contain a hostname credential, connection URL, customer name,
token, or secret.

Production preflight fails closed if off-host backup is disabled, the endpoint is not HTTPS,
credentials/bucket/region are incomplete, the prefix is invalid, or retention generations are
less than one.

Backup credentials stay only in the server environment and backup operations container. They are
never emitted into Flutter/Mini configuration, manifests, object names, GitHub artifacts, or
normal command output.

## Backup identity and atomic publication

The daily scheduled slot is UTC date based:

```text
2026-10-05 → backup_id pg-2026-10-05
```

Re-running the same date uses the same backup identity. If a valid final manifest already exists,
the operation verifies it and returns idempotently rather than replacing it.

Object layout:

```text
postgresql-backups/_staging/pg-YYYY-MM-DD/database.dump
postgresql-backups/verified/pg-YYYY-MM-DD/database.dump
postgresql-backups/verified/pg-YYYY-MM-DD/manifest.json
```

Publication order is:

1. Upload the dump to `_staging`.
2. Re-read object HEAD and validate size + operational SHA-256 metadata.
3. Copy to the canonical verified dump key.
4. Revalidate the canonical dump HEAD.
5. Build a secret-free deterministic JSON manifest.
6. Publish the final manifest last and revalidate manifest size/checksum metadata.
7. Re-read the published manifest and dump identity.
8. Delete the staging object.

If steps 1–5 fail, there is no final manifest and the partial object is not a valid backup.

The manifest contains only operational metadata: backup ID, UTC timestamps, source database label,
stable cluster ID, release revision when available, Alembic revision, pg_dump version, format,
dump object key, dump size and SHA-256. Passwords, access keys, JWT/provider secrets and
credential-bearing URLs are rejected.

## Manual backup

Run from the checked-out production release:

```bash
sudo ENV_FILE=/srv/jiyidashi/backend/.env.production \
  BACKUP_LOCAL_STAGING_DIR=/srv/jiyidashi/backups/offhost-staging \
  bash /srv/jiyidashi/ops/offhost-backup.sh
```

To deliberately retry a specific daily slot:

```bash
sudo ENV_FILE=/srv/jiyidashi/backend/.env.production \
  BACKUP_SLOT=2026-10-05 \
  bash /srv/jiyidashi/ops/offhost-backup.sh
```

The script uses a host `flock` lock. A concurrent invocation exits with status 75 before taking a
new dump. This lock is correct for the reviewed single-host production topology. Before adding a
second backup-capable host, replace it with a distributed lease/lock authority.

Local staging dumps are removed after successful off-host publication and are pruned aggressively
on later runs. Local copies are not counted as off-host recovery generations.

## Scheduled backup

Install the reviewed units:

```bash
sudo cp ops/systemd/jiyidashi-offhost-backup.service /etc/systemd/system/
sudo cp ops/systemd/jiyidashi-offhost-backup.timer /etc/systemd/system/
sudo cp ops/systemd/jiyidashi-restore-drill.service /etc/systemd/system/
sudo cp ops/systemd/jiyidashi-restore-drill.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jiyidashi-offhost-backup.timer
sudo systemctl enable --now jiyidashi-restore-drill.timer
```

Default schedules:

```text
backup       daily 02:15 UTC + up to 10m randomized delay
restore drill Sunday 04:15 UTC + up to 15m randomized delay
```

Both timers use `Persistent=true`, so a powered-off host runs the missed obligation after the
host returns. Failures remain visible in systemd/journald and can be retried manually using the
same slot.

Check status:

```bash
systemctl list-timers 'jiyidashi-*backup*' 'jiyidashi-*restore*'
journalctl -u jiyidashi-offhost-backup.service --since today
journalctl -u jiyidashi-restore-drill.service --since '7 days ago'
```

## Restore drill

Never restore an off-host backup directly over `POSTGRES_DB` through OPS-003.

Latest verified backup:

```bash
sudo ENV_FILE=/srv/jiyidashi/backend/.env.production \
  bash /srv/jiyidashi/ops/offhost-restore-drill.sh latest
```

Specific backup:

```bash
sudo ENV_FILE=/srv/jiyidashi/backend/.env.production \
  bash /srv/jiyidashi/ops/offhost-restore-drill.sh pg-2026-10-05
```

The drill:

1. Loads the final manifest and verifies canonical object identity.
2. Downloads into a `.partial` local file.
3. Computes the downloaded dump SHA-256 and size before any restore database is created.
4. Atomically exposes the local dump only after checksum success.
5. Creates a uniquely named isolated `jiyi_ops003_restore_*` database.
6. Runs real `pg_restore`.
7. Confirms the restored Alembic revision matches the manifest.
8. Runs `alembic upgrade head` and `alembic check` against the isolated database.
9. Verifies public-schema tables and the `users` table are readable.
10. Drops the isolated database and removes local restore staging.

For debugging only, `BACKUP_RESTORE_RETAIN=true` may retain the temporary database. Never use
the production database name as the restore target.

## Retention

Retention is applied only to canonical manifests discovered under:

```text
<BACKUP_OBJECT_PREFIX>/verified/
```

V1 keeps the union of configurable:

- newest N UTC daily generations;
- newest N ISO-week generations;
- newest N monthly generations;
- the newest known-good verified backup unconditionally.

Deletion order is manifest first, dump second. A crash during deletion can leave an unadvertised
orphan dump, but cannot leave a manifest advertising a dump that retention already deleted.

Malformed or ambiguous manifest identity causes retention to fail closed. Objects outside the
configured prefix are never considered by retention.

## Failure recovery

### Dump fails

No off-host manifest is published. Fix PostgreSQL/disk/runtime error and retry the same slot.

### Upload/copy fails

The final manifest is absent, so the backup is not advertised. Retry the same slot. Staging
objects may remain until operator cleanup; they are not restore authority.

### Manifest exists but verification fails

Do not overwrite it automatically. Treat this as a storage-integrity incident, preserve evidence,
select another verified backup for recovery, and investigate the provider copy/object state.

### Restore checksum mismatch

The drill fails before creating or mutating a restore database. Preserve the affected object and
manifest for investigation. Do not bypass checksum validation.

### Timer missed or failed

`Persistent=true` handles missed schedules after reboot. For a failed service, inspect journald
and rerun the same daily slot manually.

## Credential rotation

1. Create a new server-side credential limited to the backup bucket/prefix.
2. Update only untracked `backend/.env.production`.
3. Run `ops/validate-production-runtime.py`.
4. Run one manual backup using a new daily/custom slot.
5. Run a restore drill against that verified backup.
6. Revoke the old credential only after both steps pass.

Do not place old/new access keys in command-line arguments, manifests or tickets.

## Production acceptance

The exact-head production deployment gate proves:

- production config fails closed when backup settings are disabled/incomplete;
- backup shell/module syntax is valid in the immutable backend image;
- an actual PostgreSQL custom dump is produced;
- the same scheduled slot is idempotent;
- only one canonical verified manifest/dump pair is published;
- fake private-store artifacts contain no configured access-key/secret values;
- an overlapping process is fenced by the deployment lock;
- a selected off-host backup is downloaded, checksum-verified and really restored to PostgreSQL;
- Alembic upgrade/check succeeds against that isolated restored database;
- the restore database is removed after the drill;
- same-size remote dump corruption causes restore to fail before any restore database mutation.

The CI filesystem provider is a deterministic test seam only. Runtime code refuses to select it
unless the process is explicitly running under `CI=true`; production configuration remains S3
compatible and HTTPS-only.
