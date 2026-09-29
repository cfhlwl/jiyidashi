# Product Analytics Foundation V1

## Scope

Issue #169 implements repository-owned product outcome analytics for BIZ-007, BIZ-008,
and BIZ-009. PostgreSQL rows are canonical. V1 does not add a client tracking SDK,
marketing attribution, a visual dashboard, or a second observability system.

## BIZ-007 — Successful Memory Retrievals

The canonical V1 retrieval surface is `POST /v1/memory/query`.

An attempt begins only after authentication and request validation admit the endpoint.
The server records `SUCCESS` only when all three canonical response properties hold:

```text
can_answer == true
memory_ids is non-empty
evidence is non-empty
```

A completed accepted request that does not meet all three conditions is
`NO_EVIDENCE`. An accepted request that later raises a server/infrastructure error may
record `FAILED`. SUCCESS is never inferred from answer text or a client flag.

BIZ-007 is the count of `SUCCESS` attempts.

## BIZ-009 — Memory Retrieval Success

```text
successes / all accepted MEMORY_QUERY attempts
```

The denominator contains SUCCESS, NO_EVIDENCE, and FAILED. Invalid authentication,
schema-invalid payloads, and requests rejected before endpoint admission are excluded.

A zero denominator yields JSON `null`, not 0%.

## Retrieval data minimization

`retrieval_analytics_attempts` contains only:

- owner user FK
- normalized request operation UUID
- strict retrieval surface enum
- strict outcome enum
- bounded aggregate result/evidence counts
- UTC occurrence time

It never stores query text/hash, Memory/MemorySource/Person/Object/Place/media IDs,
answer text, evidence excerpts, prompts/outputs, coordinates, IP/email, tokens, object
keys, or arbitrary metadata JSON.

`(user_id, operation_id, surface)` is unique.

## BIZ-008 — UTC D1/D7/D30 retention

The cohort day is immutable UTC signup date:

```text
cohort_day = UTC date(User.created_at)
D1 target  = cohort_day + 1
D7 target  = cohort_day + 7
D30 target = cohort_day + 30
```

A user is eligible for Dn only when the target day is no later than the report cutoff
(`--to`). Retained means a canonical `product_active_days` row exists exactly on the
target UTC date. Zero eligible users yields a null rate.

## Active-day allowlist

V1 records one row per user per UTC day for successful server-owned product activity:

- POST /v1/memories
- POST /v1/memory/query
- GET /v1/timeline
- GET /v1/timeline/events
- successful POST /v1/media/uploads reservation
- successful POST /v1/media/{media_id}/complete

The activity enum is backend-owned but is not persisted; the durable row needs only user
and UTC date. Health/readiness, auth/token issuance, entitlement reads, maintenance,
background AI/provider work, security retry, and analytics report execution are excluded.

## Fail-safe recording and deletion generation

Product transactions do not depend on analytics success. Recording uses an isolated
`GuardedSession` that copies the request's canonical `UserDataAdmission`. Any
analytics exception emits only:

```text
event      = analytics.recording.failed
error_code = ANALYTICS_RECORDING_FAILED
```

and leaves the original product response/status unchanged.

Because the isolated session commits through the existing GuardedSession generation
check, a request admitted before DELETE_MY_DATA or DELETE_MY_ACCOUNT cannot recreate
analytics after the destructive generation/account gate advances.

DELETE_MY_DATA explicitly removes retrieval-attempt and active-day rows. Account deletion
also removes them through the user FK cascade.

## Aggregate report

```bash
python -m app.analytics_report --from YYYY-MM-DD --to YYYY-MM-DD
```

Output is aggregate JSON only: retrieval counts/rate and per-cohort D1/D7/D30
eligible/retained/rate values. It contains no user IDs or per-user rows.

## Retention maintenance

Default configuration:

```text
ANALYTICS_RETRIEVAL_RETENTION_DAYS = 90
ANALYTICS_ACTIVE_DAY_RETENTION_DAYS = 400
```

Both are bounded to 31..3650 days and active-day retention may not be shorter than raw
retrieval retention. Operators can run:

```bash
python -m app.analytics_retention \
  --retrieval-days 90 \
  --active-day-days 400
```

User-requested deletion always overrides these maintenance windows.

These periods apply only to product analytics; they do not alter Memory or location
retention policy.

## Authority separation

Analytics rows are never read by Memory trust/ranking, Family permission, Privacy Pause,
Entitlement/quota, security alerting, AI prompt construction, or account eligibility.
Removing analytics cannot change product authority.
