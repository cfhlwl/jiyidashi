# Production Runtime Guardrails V1

OPS-004 defines the bounded runtime contract for the reviewed single-host production
topology. These limits are deliberately conservative for the initial 2C2G target and
must be re-reviewed before increasing process counts or introducing additional workers.

## PostgreSQL connection budget

Canonical production values:

```text
WEB_CONCURRENCY=2
maintenance workers=1
DB_POOL_SIZE=3
DB_MAX_OVERFLOW=1
DB_POOL_TIMEOUT_SECONDS=5
DB_POOL_RECYCLE_SECONDS=300
DB_CONNECTION_BUDGET=20
```

Each API worker process owns one SQLAlchemy pool. The maintenance worker imports the
same canonical engine and therefore owns one additional pool.

The reviewed worst-case application connection equation is:

```text
(WEB_CONCURRENCY + maintenance workers)
× (DB_POOL_SIZE + DB_MAX_OVERFLOW)

= (2 + 1) × (3 + 1)
= 12 maximum application connections
```

The explicit production budget is 20, leaving 8 connections of application-budget
headroom for bounded migration, restore, backup verification, and operator activity.
This is intentionally below PostgreSQL's normal server connection capacity; production
preflight rejects a configuration whose derived application maximum exceeds the
reviewed budget instead of waiting for PostgreSQL to fail under load.

SQLite and test paths do not receive PostgreSQL QueuePool sizing arguments. Readiness
checks continue to use their independent `NullPool` engine.

## Container log retention

Long-running production services use Docker's `json-file` driver with:

```text
max-size = 10m
max-file = 3
```

The bound applies to PostgreSQL, API, maintenance worker, and reverse proxy. stdout and
stderr remain the observability interface; rotation only bounds local disk growth.

## Edge security headers

The HTTPS Caddy site emits:

```text
Strict-Transport-Security: max-age=31536000
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
X-Frame-Options: DENY
```

HSTS preload is intentionally not enabled. Preload is a separate long-lived operational
commitment and is outside OPS-004 V1.

The Admin Console remains served under `/admin/`, and `/admin/api/*` continues to
proxy to the API. The same edge headers apply to Admin and API HTTPS responses.

## Request-body ceiling

Production uses:

```text
API_REQUEST_BODY_LIMIT=2MB
```

Caddy enforces this before unbounded request bodies reach the application. Requests over
the ceiling fail with HTTP 413.

This ceiling is for normal authenticated JSON/form requests, auth, Admin API requests,
and signed-upload completion metadata. It is not a raw-media upload limit.

The media architecture remains:

```text
client
→ server-authorized signed transfer
→ private object storage
→ bounded completion metadata to API
```

Raw photos and audio therefore must not be routed through the API merely to bypass this
limit. MEDIA-001 may evolve media processing, but it does not change this authority.

## Production preflight

`ops/validate-production-runtime.py` fails closed when:

- pool size is outside 1..10;
- overflow is outside 0..10;
- pool timeout is outside 1..30 seconds;
- recycle is outside 30..3600 seconds;
- connection budget is outside 4..64;
- WEB_CONCURRENCY is outside 1..8;
- the derived API+worker connection maximum exceeds the configured budget;
- request-body limit is absent, malformed, below 256KiB, or above 8MiB.

Errors name only configuration fields and bounded policy failures. They do not echo
`DATABASE_URL`, passwords, or other credentials.

## Acceptance evidence

The production deployment gate must prove on the exact PR HEAD that:

- rendered Compose contains bounded logging on all four long-running services;
- invalid database pool and body-limit configurations fail preflight;
- SQLite engine creation receives no PostgreSQL pool parameters;
- a real PostgreSQL application engine exposes the reviewed pool values and executes
  `SELECT 1`;
- Caddy validates with the configured body limit;
- an HTTPS health response carries every required security header;
- Admin static routing still returns content;
- a request over 2MB returns HTTP 413;
- a normal-sized auth request is not rejected by the body ceiling.
