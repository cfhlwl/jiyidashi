# Entitlement & Quota Foundation V1

## Purpose

Issue #168 introduces a server-owned entitlement and quota authority without adding
payment providers, prices, purchase UI, receipt validation, renewal logic, or client-
authoritative plan state.

The canonical flow is:

```text
authenticated user
→ UserEntitlement
→ PlanCode
→ server capability catalog
→ server quota catalog
→ durable usage authority
→ allow / typed deny
```

Clients may read their resolved state from `GET /v1/entitlements/me`, but the server
still enforces media and AI operations independently.

## Plan vocabulary

Commercial vocabulary:

```text
FREE
PERSONAL
FAMILY
PREMIUM
```

Rollout-only compatibility plan:

```text
LEGACY_FULL
```

`LEGACY_FULL` is not a paid tier. Migration 0026 assigns it to every user that exists
at migration time. New registration during this foundation phase creates the same
assignment in the account-registration transaction. Missing, future-effective, expired,
unknown, or otherwise unusable entitlement state fails closed with
`ENTITLEMENT_STATE_UNAVAILABLE`.

A future rollout may choose a different default for new users. This V1 does not.

## Capability catalog

Capabilities are enum values owned by backend code:

```text
CORE_MEMORY
BASIC_SEARCH
EXTENDED_HISTORY
IMAGE_MEDIA
VOICE_MEDIA
AI_INFERENCE
FAMILY_FEATURES
ELDER_MODE
ARRIVAL_REMINDER
ANNUAL_MEMOIR
LIFE_MEMOIR
LONG_TERM_REASONING
```

The catalog is centralized in `entitlement_service.py`. Product endpoints must not
scatter plan-code comparisons.

V1 bundles:

- FREE: core memory and basic search only.
- PERSONAL: FREE plus extended history and annual memoir representation.
- FAMILY: PERSONAL plus family, elder and arrival-reminder representation.
- PREMIUM: all defined capabilities.
- LEGACY_FULL: all defined capabilities to preserve pre-entitlement behavior.

Only media-kind and AI inference capabilities are formally enforced by this foundation.
Advanced capability representation does not mean every advanced endpoint is paywalled.

## Quota dimensions

V1 defines:

```text
STORAGE_BYTES
AI_PROVIDER_REQUESTS
AI_INPUT_TOKENS
AI_OUTPUT_TOKENS
```

The enforceable dimensions are `STORAGE_BYTES` and `AI_PROVIDER_REQUESTS`.

Commercial quota values are supplied by the validated server-owned
`ENTITLEMENT_QUOTA_CATALOG` configuration. The backend does not hard-code commercial
limits. A commercial plan missing either required enforceable quota fails closed rather
than silently becoming unlimited.

`LEGACY_FULL` explicitly resolves all quota limits to null/unlimited.

Token dimensions are accounting metadata only in V1.

## Storage accounting

Canonical storage usage is derived from PostgreSQL `MediaAsset` rows:

```text
PENDING.size_bytes
+
READY.size_bytes
```

Both states count so unfinished signed uploads cannot reserve unbounded external
storage without affecting quota.

The upload path serializes the authenticated user before:

```text
capability resolve
→ existing client_upload_id lookup
→ current PENDING + READY usage
→ quota decision
→ new MediaAsset reservation
→ upload signing
```

This prevents two concurrent uploads from each observing the same remaining capacity.
A replay of the same canonical `client_upload_id` reuses the existing MediaAsset and
does not consume quota twice.

Object-store LIST results are never quota authority.

## Media capability mapping

At `POST /v1/media/uploads`:

```text
IMAGE → IMAGE_MEDIA
AUDIO → VOICE_MEDIA
```

File-size, MIME, signature, storage ownership and READY validation remain independent
media-security policies. Entitlement does not replace them.

## AI accounting

The enforceable AI unit is one provider invocation.

Gateway ordering is:

```text
local request validation
→ authenticated actor entitlement lookup
→ AI_INFERENCE capability check
→ atomic provider-request reservation
→ commit reservation
→ provider invocation
→ token/provider-request-id finalization when available
```

A locally invalid request does not reserve quota. Once provider invocation is allowed
to start, the reservation remains consumed even if the provider later fails or times
out.

The gateway operation ID is server-generated. `user_id + gateway_request_id` is unique
in the durable usage ledger, so token finalization or replay cannot charge a second
provider request.

No prompt, model output, OCR text, Vision output or other user content is stored in the
quota ledger.

## AI quota period

V1 uses the UTC calendar month:

```text
[month start 00:00:00 UTC, next month start 00:00:00 UTC)
```

This is an accounting period, not a payment renewal cycle.

## Read-only API

`GET /v1/entitlements/me` returns:

```text
plan_code
capabilities[]
storage.used
storage.limit
ai_requests.used
ai_requests.limit
ai_requests.period_start
ai_requests.period_end
```

It exposes no mutation surface, prices, payment IDs, provider secrets or internal ledger
rows.

## Typed errors

Server-owned entitlement errors:

```text
ENTITLEMENT_STATE_UNAVAILABLE
ENTITLEMENT_CAPABILITY_REQUIRED
ENTITLEMENT_QUOTA_EXCEEDED
```

These errors do not contain purchase URLs or pricing information.

## Family authority separation

The FAMILY capability means only that the product capability can be enabled for an
account. It does not replace:

```text
FamilyMembership
FamilyPermissionGrant
FamilyAccessAuditEvent
Privacy Pause
Emergency Share
VIEW_MEMORY
VIEW_PHOTOS
VIEW_CURRENT_LOCATION
VIEW_FOOTPRINT
```

Existing Family authorization remains authoritative.

Household pooled billing/quota is not part of V1.

## Deletion lifecycle

`DELETE_MY_DATA` removes application data as before, including MediaAsset rows, so
derived storage usage can fall naturally. It deliberately preserves:

```text
UserEntitlement
AIQuotaPeriod
AIUsageEvent
```

A user therefore cannot reset AI quota by deleting application data.

`DELETE_MY_ACCOUNT` removes entitlement and AI usage in the final account-deletion
transaction and then removes the User. Foreign-key cascade remains a secondary database
safety boundary.

## Privacy

Entitlement and usage persistence contains no:

```text
Memory content
MemorySource raw text
AI prompt/output
OCR/Vision output
precise coordinates
media object keys
signed URLs
storage credentials
password/JWT
raw email/IP
```

AI usage stores only controlled accounting metadata such as gateway operation ID,
purpose, provider request ID and optional numeric token counts.

## No-payment boundary

This foundation does not implement or imply:

```text
Stripe
WeChat Pay
App Store / Google Play billing
prices
discounts
trials
purchase / renewal / refund
receipt validation
payment webhooks
client purchase UI
household pooled billing
```

Commercial launch remains a later packaging/payment/rollout task.

## Verification

Required exact-head evidence includes:

- focused plan/catalog/fail-closed/accounting tests;
- migration 0025 → 0026 backfill of existing users;
- real PostgreSQL concurrent storage reservation;
- real PostgreSQL AI last-slot provider race;
- provider failure remains charged;
- Data Delete preserves entitlement/AI usage;
- Account Delete removes entitlement/AI usage;
- schema drift clean;
- full Backend CI;
- Production Deployment CI because migration/schema changed.
