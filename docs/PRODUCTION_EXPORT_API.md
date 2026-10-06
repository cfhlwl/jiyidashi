# Production Export & Legacy Pagination V1

API-001 removes the synchronous whole-account export from the request process and
makes export completion a durable owner-scoped authority.

## Public export protocol

```text
POST /v1/export/jobs
  Idempotency-Key: <UUID>
  -> 202 UserExportJob

GET /v1/export/jobs/{id}
  -> owner-only status/metadata

GET /v1/export/jobs/{id}/download
  -> COMPLETED + unexpired + owner
  -> short-lived private signed GET

GET /v1/export/data
  -> 410 EXPORT_ASYNC_REQUIRED
```

The public job row is `UserExportJob`. `MaintenanceJob` remains internal execution
authority and is never exposed as a user-visible job domain.

## Worker and artifact authority

```text
UserExportJob PENDING
→ OPS-002 EXPORT MaintenanceJob
→ token-bound maintenance claim
→ UserExportJob RUNNING + revision++
→ PostgreSQL REPEATABLE READ snapshot
→ deterministic keyset batches
→ bounded local temp JSON + incremental SHA-256
→ private attempt object upload
→ verify remote size/content-type/SHA-256 metadata
→ re-lock same owner/job/revision
→ revalidate account/deletion authority
→ atomically publish COMPLETED metadata
```

Attempt object keys include export job revision and maintenance claim token. A stale
attempt cannot publish over a newer revision. Failed unpublished attempt objects are
best-effort removed and later retries sweep the job prefix before generation.

Blocking artifact upload runs under a database-backed heartbeat for the full physical
upload duration, not just before/after checks. It also holds the canonical shared
owner-destructive advisory handoff across upload, verification and publication. After
acquiring that handoff the worker rechecks both maintenance authority and the current
export/deletion gate, so either Export owns the shared phase before deletion starts or a
committed Data/Account Delete gate stops the upload before object creation.

Lease loss, local I/O failure, storage failure, and unexpected execution failure all
converge the revision-fenced `UserExportJob` out of RUNNING. If a final claimed
attempt crashes and its lease expires, maintenance housekeeping terminalizes both the
internal MaintenanceJob and the still-active public export job.

Production defaults:

```text
EXPORT_BATCH_SIZE=200
EXPORT_ARTIFACT_MAX_BYTES=268435456
EXPORT_ARTIFACT_TTL_HOURS=24
worker /tmp tmpfs=320MiB
required temp headroom=64MiB
```

Export generation never materializes all sections or the complete JSON artifact in
one Python object. The artifact hard ceiling fails closed with a bounded error code.
Production static/runtime preflight requires the 256MiB ceiling to fit inside the
reviewed 320MiB worker temp budget with 64MiB headroom.

## Snapshot semantics

PostgreSQL export generation uses one REPEATABLE READ snapshot. Rows committed after
that snapshot starts are intentionally not mixed into the artifact. A later export job
captures later state.

The V1 schema is retained, including:

- soft-deleted Memories and their Evidence remain absent;
- ObjectLocation whose backing Memory was deleted is redacted;
- media storage keys, upload keys, ETags, credentials, and signed URLs are excluded.

## Artifact lifetime and deletion

Completed artifacts expire after the configured TTL. The existing OPS-002 scheduler
enqueues an `EXPORT/CLEANUP` job using the same durable worker system.

Data Delete / Account Delete own the stronger authority:

- `media/_exports/{owner}/` is part of the authoritative storage deletion prefixes;
- `user_export_jobs` is part of the owner database deletion inventory;
- owner maintenance jobs are fenced by the existing destructive-operation boundary;
- export publication rechecks owner/deletion state before COMPLETED.

Worker startup removes abandoned local `jiyidashi-export-*.json` temp files older
than 24 hours.

## Legacy list audit

API-001 audited production list routes under `backend/app/api/**`.

| Surface | V1 result |
| --- | --- |
| `GET /v1/objects` | Legacy released-client array contract preserved unchanged. |
| `GET /v1/objects/page-v1` | New owner-bound HMAC keyset pagination, default 50, max 100, `limit+1`. |
| Memory timeline | Already bounded by request limit; canonical timeline API already has opaque cursor where required. |
| Life events / event memories | Existing SQL limits, max 100. |
| Life stages / stage events | Existing SQL limits, max 100. |
| Location visits / places | Existing SQL limits, max 500. |
| People / interactions / memory links / relationships | Existing SQL limits, max 100. |
| Reminders | Existing SQL limit, max 200. |
| Family memories / audit | Existing SQL limits, max 50. |
| Family photos | Service-owned `FAMILY_PHOTO_LIST_LIMIT`. |
| Emergency shares | Service-owned `EMERGENCY_SHARE_LIST_LIMIT`. |
| Arrival reminders | Service-owned `ARRIVAL_REMINDER_LIST_LIMIT`. |
| Auth sessions | Explicit SQL hard limit 100 added by API-001. |
| Admin account list | Privileged Admin surface, not owner-consumer pagination scope. |

The versioned `/objects/page-v1` cursor contains no trusted client authority. It is
HMAC signed and binds version, endpoint, owner UUID, normalized-name key and object UUID.
Malformed, tampered, foreign-owner, or version-mismatched cursors return a deterministic
400. The legacy `/objects` array remains only for compatibility with already-released
Flutter/Mini clients and is not the pagination contract for new callers.

Stable order:

```text
objects:
(normalized_name ASC, id ASC)
```

## Acceptance

Exact-head CI must prove:

- legacy synchronous export returns only bounded migration guidance;
- create is authenticated, rate-limited and idempotent;
- status/download are owner-isolated;
- worker generation is bounded and preserves V1 redaction/privacy semantics;
- remote artifact size/hash/content type are verified before publication;
- upload heartbeat prevents lease reclaim during a blocking upload;
- local ENOSPC/OSError cannot leave the public export job RUNNING;
- exhausted final maintenance lease converges the public export job to FAILED;
- stale revision cannot publish;
- TTL download fails closed;
- PostgreSQL REPEATABLE READ excludes writes committed after snapshot start;
- migration roundtrip and schema drift pass;
- legacy `/objects` still returns the released top-level array contract;
- `/objects/page-v1` default/max/multi-page/tamper/foreign-owner behavior passes;
- full backend and production deployment gates pass.
