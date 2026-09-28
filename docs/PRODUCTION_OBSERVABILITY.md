# Production Observability V1

Issue: #161  
Parent closeout: #160  
Security alerting dependency: #165

## Purpose

Production Observability V1 provides repository-owned operational telemetry without changing business authority. V1 intentionally uses structured JSON logging to stdout/stderr so operators can aggregate logs later without coupling the backend to a telemetry SaaS.

It does **not** add product analytics, a process-local metrics endpoint, distributed tracing infrastructure, or the SEC-015 anomaly/alert engine.

## Structured event envelope

Every observability record is one JSON object containing:

```text
timestamp   UTC ISO-8601
level       DEBUG | INFO | WARNING | ERROR
event       stable event name
request_id  canonical UUID or null
```

Additional fields come from a fixed allowlist only. The helper has no generic arbitrary-field serialization surface.

Allowed operational fields include:

```text
method
route
status_code
latency_ms
purpose
provider
model
gateway_request_id
provider_request_id
input_tokens
output_tokens
retryable
error_code
operation
operation_request_id
operation_status
completed
dependency
ready
```

Telemetry failures are swallowed by the observability helper and never change successful business behavior.

## Request correlation

Header:

```text
X-Request-ID
```

Rules:

- valid incoming UUID → canonicalized and reused;
- missing/malformed value → server-generated UUIDv4;
- every normal HTTP response echoes the canonical request ID;
- a `ContextVar` carries the request ID into service-layer operational events.

Request completion telemetry uses the FastAPI **route template**, not the raw path. Query strings are never recorded.

Events:

```text
http.request.completed
http.request.failed
```

Health/readiness request completions use DEBUG level to reduce probe noise.

## Redaction policy

The observability stream must never contain:

- Memory title/content or MemorySource raw text;
- AI system instruction, input, output, image bytes or provider error bodies;
- OCR/Vision output;
- precise latitude/longitude;
- object keys/prefixes, bucket names, endpoints or presigned URLs;
- storage access credentials;
- JWT, Authorization or Cookie values;
- passwords or email addresses;
- HTTP request/response bodies;
- arbitrary exception messages/tracebacks.

Operational error events use stable `error_code` values only.

Tests seed distinctive sentinel secrets/content and assert that captured JSON does not contain them.

## AI Gateway events

Instrumentation exists only in canonical `AIGateway.infer()` and `infer_image()`.

Success:

```text
ai.inference.completed
request_id
gateway_request_id
purpose
provider
model
provider_request_id
latency_ms
input_tokens
output_tokens
```

Failure:

```text
ai.inference.failed
request_id
gateway_request_id
purpose
provider
model
latency_ms
error_code
retryable
```

The gateway request ID is created before the provider attempt and is also the ID returned in public/internal `AIProvenance` on success.

Cancellation still propagates; no synthetic result is created.

## Object-storage failures

Canonical S3 adapter failures emit:

```text
storage.operation.failed
request_id
operation
error_code
```

Controlled operation names:

```text
sign_upload
sign_download
stat
read_prefix
read_object
promote
delete
list
```

Object-not-found remains a normal domain outcome and does not emit noisy operational-failure telemetry.

No bucket, endpoint, object key/prefix, URL or provider exception body is logged.

## Data / Account Delete events

HTTP orchestration emits safe lifecycle events without changing deletion state machines.

```text
data_deletion.progress
data_deletion.failed
account_deletion.progress
account_deletion.failed
```

Safe fields include deletion request UUID, status/completed state, HTTP status, retryable classification and stable error code.

The events never include user IDs, deleted content, object keys or deleted-count resource names.

## Liveness and readiness

### Liveness

```text
GET /health
```

Existing process-liveness semantics are unchanged.

### Readiness

```text
GET /health/ready
```

Required V1 dependency: PostgreSQL/database.

Readiness performs a bounded simple database `SELECT 1`.

Ready:

```json
{"status":"ready","database":"ready"}
```

Unavailable:

```json
{"status":"not_ready","database":"unavailable"}
```

The unavailable response is HTTP 503 and never includes DSN, host, credentials or exception text.

AI, ASR, Embedding and object storage are feature dependencies and are deliberately not called by readiness probes.

Production Compose uses `/health/ready` for API container health. External smoke/liveness checks may continue to use `/health`.

## Configuration

```text
OBSERVABILITY_LOG_LEVEL=INFO
```

Allowed values:

```text
DEBUG
INFO
WARNING
ERROR
```

Production default remains structured JSON event messages at INFO.

No external telemetry credentials are introduced.

## Operator correlation workflow

1. Start with the `X-Request-ID` returned to the client or reported by support.
2. Filter structured events by `request_id`.
3. For provider calls, follow `gateway_request_id` and optional `provider_request_id`.
4. For destructive operations, follow `operation_request_id`.
5. Use route template / provider purpose / storage operation / error code as bounded aggregation dimensions.
6. Never use user IDs or resource IDs as metric labels.

## Retention recommendation

V1 does not ship a log-storage backend. Operators should configure their chosen log collector to:

- retain production operational logs only as long as needed for incident response and reliability analysis;
- apply access control equal to other production operational data;
- preserve JSON fields without scraping application payloads;
- enforce deletion/retention policy outside the application process.

Security-alert routing, anomaly thresholds and incident notification delivery belong to **#165 / SEC-015**, not #161.
