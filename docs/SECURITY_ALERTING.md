# SEC-015 — Security Event Alerting & Anomaly Response V1

## Purpose

SEC-015 is a repository-owned, backend-owned security signal and operator alert layer.
It observes existing canonical Auth, Family, Delete and Storage authority paths. It does
not change authorization, rate-limit status codes, Family grants, deletion state
machines, or automatically punish accounts.

V1 has no mandatory SaaS dependency and no email/Slack/pager adapter. The reviewed
delivery baseline is a durable PostgreSQL alert row plus one structured
`security.alert.triggered` operational event written through the #161 JSON log sink.

## Taxonomy and deterministic policy

| Rule | Window | Threshold | Cooldown | Severity |
| --- | ---: | ---: | ---: | --- |
| `AUTH_RATE_LIMIT_TRIGGERED` | 10 min | 1 | 10 min | MEDIUM |
| `AUTH_LOGIN_FAILURE_BURST` | 15 min | 5 | 15 min | HIGH |
| `FAMILY_SENSITIVE_READ_DENIED` | 10 min | 5 | 10 min | MEDIUM |
| `FAMILY_SENSITIVE_DOWNLOAD_DENIED` | 10 min | 3 | 10 min | HIGH |
| `FAMILY_SENSITIVE_ACCESS_BURST` | 10 min | 10 | 10 min | HIGH |
| `DESTRUCTIVE_OPERATION_FAILURE` | 15 min | 3 | 15 min | HIGH |
| `DESTRUCTIVE_OPERATION_RETRY_BURST` | 15 min | 3 | 15 min | HIGH |
| `STORAGE_CAPABILITY_FAILURE_BURST` | 10 min | 5 | 10 min | HIGH |

Severity is server-owned and is never inferred from exception text.

## Durable anomaly authority

`security_signal_windows` is the canonical threshold state. Its unique identity is:

```text
rule_code
+ correlation_digest
+ bounded scope
+ window_started_at
```

`security_alerts` stores one logical alert per cooldown identity. The dedupe key is
derived only from controlled dimensions:

```text
rule_code
+ severity
+ correlation_digest
+ bounded scope
+ cooldown bucket
```

Database row locking plus uniqueness constraints make the same logical anomaly converge
across concurrent Uvicorn workers and independent Sessions. Process/container restart
does not reset the window.

Cooldown is elapsed-time based, not a wall-clock bucket. Before creating a new logical
alert, the service locks the latest matching alert for the same rule/correlation/scope
and requires `now >= latest_alert.created_at + cooldown`. Crossing an aligned minute or
10-minute boundary does not create a second alert early.

## Correlation privacy

Raw IP addresses, email addresses and user/family identifiers are accepted only as
ephemeral input to a server-keyed HMAC-SHA256 correlation function. Only the 64-character
digest is persisted or emitted. The digest is intended for equality correlation only and
is not an authentication credential.

Deletion request UUIDs are also passed through the same digest path in V1.

The security path must never contain:

- Memory title/content or MemorySource raw text
- prompt/system/output, OCR or Vision output
- precise coordinates
- raw email or raw IP address
- password, Authorization/JWT or Cookie
- media/object keys, bucket names, provider endpoints or presigned URLs
- storage credentials
- provider exception bodies
- request or response bodies

## Source integrations

### Auth

The existing persistent auth rate-limit service remains authoritative. SEC-015 observes:

- registration IP limiter hits
- login IP limiter hits
- login account/IP limiter or active-penalty hits
- repeated login failures

The original HTTP 429 and `Retry-After` values are unchanged.

### Family

Exact-grant DENIED results are signaled only after the canonical Family audit row has
committed. Photo-download denial has its own higher-sensitivity rule. Denied accesses
also feed the cross-resource sensitive-access burst rule.

Family photo signing/storage failures feed the storage capability rule only after the
canonical audit result is committed. No Memory content, photo ID, coordinate, object key
or signed URL enters the alert stream.

### Data Delete / Account Delete

Canonical deletion exceptions feed failure and retry-burst rules. Existing request UUIDs
are correlated through the one-way digest. Deletion locking, idempotency and retry state
machines are unchanged.

### Storage/media

Reviewed owner-scoped media completion/download and Family photo signing failures feed
`STORAGE_CAPABILITY_FAILURE_BURST`. Expected object-not-found domain results are not
reclassified as suspicious by this rule.

## Operator event

New logical alerts attempt one structured event:

```text
event = security.alert.triggered
alert_id
rule_code
severity
signal_count
window_seconds
correlation_id
delivery_status
```

These fields are an explicit extension of the #161 observability whitelist. Arbitrary
payload dictionaries and ORM serialization are not supported.

Use `alert_id` for durable incident identity and `request_id` (when present in the
surrounding request context) for request-level tracing.

## Delivery and retry

V1 delivery states:

```text
PENDING
DELIVERED
RETRYABLE_FAILURE
TERMINAL_FAILURE
```

The built-in JSON log sink is the only active adapter. Security alert delivery uses the
same observability stream through an acknowledged write path: the alert is marked
`DELIVERED` only after both stream write and flush succeed. A failed delivery attempt
never changes the business request result.

Retry policy:

- maximum attempts: 5
- exponential backoff: 30s, 60s, 120s, 240s, 480s (capped at 900s)
- after the fifth failed attempt: `TERMINAL_FAILURE`
- retry scans are bounded to at most 100 alerts per call
- the same durable `alert_id` is reused on retries

V1 does not claim paging/email/IM delivery. The production image exposes a bounded
operator retry command:

```text
python -m app.security_alert_retry --limit 25
```

This command scans durable `PENDING` / due `RETRYABLE_FAILURE` rows and can be invoked
by cron/systemd/Kubernetes CronJob or another deployment scheduler. Each delivery attempt
re-checks status, attempt count, and `next_retry_at` after taking the row `FOR UPDATE`
lock, so concurrent retry workers cannot consume the same backoff slot.

## Investigation workflow

1. Start from `alert_id`, rule, severity, count and time window.
2. Use the pseudonymous correlation ID to group matching safe events.
3. If a request ID is available, inspect surrounding structured operational events.
4. Confirm the canonical domain result in its source system: Auth limiter, Family audit,
   deletion operation or storage/media authority.
5. Do not infer account guilt from an alert alone. V1 is operator information, not an
   automated enforcement engine.
6. For false positives, record the incident outcome operationally and adjust a reviewed
   server-owned threshold only through code review. Do not weaken the underlying Auth,
   Family, Delete or Storage security authority.
7. Rotate affected credentials/secrets when investigation finds actual credential
   exposure or provider compromise; do not rotate solely because a threshold fired.

## Retention

Retain security windows/alerts only as long as required for operational investigation
and applicable compliance obligations. A production retention job is not part of V1.
Operators should define a reviewed retention period before long-term production growth.

## Verification gates

SEC-015 requires:

- focused unit tests for threshold, elapsed cooldown boundary, redaction and bounded retry
- real checked-sink failure and durable PENDING recovery
- concurrent retry workers honoring one backoff slot
- real PostgreSQL concurrent same-window dedupe
- persistence visible from a new Session
- canonical Auth 429 + Retry-After unchanged
- migration/schema drift clean
- exact-head Backend CI
- Production Deployment CI because the production schema changed
