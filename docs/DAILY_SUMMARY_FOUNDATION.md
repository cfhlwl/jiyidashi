# Daily Summary Foundation

Issue #82 / S3-015 implements an internal, read-only, trustworthy answer seam for:

```text
今天发生了什么？
```

It deliberately does not use S3-011 top-k retrieval as a complete-day source.

## Core invariant

```text
persisted server timezone
→ complete bounded local-day inventory
→ authoritative Memory / finalized Visit facts
→ opaque D1/D2/... slots
→ AIGateway
→ strict summary/citation parser
→ revalidate complete inventory + every visible slot
→ DailySummaryResult
```

A partial scan is never presented as a complete day.

## Server-owned day

The service reads persisted `User.timezone` through an independent
`autoflush=False` read session.

The request does not accept a client-selected timezone or day. Production uses one captured
server reference timestamp to derive the user's local day.

Invalid persisted timezone values fail over to UTC consistently with the existing time
foundation.

## Complete bounded inventory

Daily Summary performs dedicated owner-scoped day scans instead of retrieval top-K.

Memory:

- `user_id` matches trusted owner
- non-deleted
- `occurred_at >= day_start`
- `occurred_at < day_end`
- deterministic `(occurred_at, id)` ordering
- maximum 64 rows plus one overflow sentinel

Visit:

- owner-scoped Visit
- owner-scoped Place join
- Today Footprint overlap semantics:
  - `arrived_at < day_end`
  - `left_at IS NULL OR left_at >= day_start`
- deterministic `(arrived_at, id)` ordering
- maximum 32 rows plus one overflow sentinel

Overflow returns `SUMMARY_INCOMPLETE` before provider I/O.

## Memory trust

Every raw day Memory gets a frozen S3-013 authority projection before prompt inclusion:

```text
memory_id
trust_state
trust_reason
evidence_source_id
```

This projection is retained even when the Memory is `NO_EVIDENCE` or
`INFERENCE_ONLY` and therefore excluded from provider context.

Only current:

- `CONFIRMED`
- `EVIDENCE_SUPPORTED`

may enter provider context.

The service uses current `Memory.content` plus the exact authoritative
`MemorySource.id` returned by S3-013. Latest edit-source semantics therefore remain
authoritative.

`INFERENCE_ONLY` and `NO_EVIDENCE` do not enter the prompt.

## Visit trust

Visit is treated as a server-derived location fact only when all foundation provenance
requirements hold:

- finalized Visit
- `source == LOCATION_CLUSTER`
- finite confidence >= 0.6
- derivation key present
- source fingerprint present
- at least two source points
- algorithm version present
- owner-scoped Place exists

Mutable/unfinalized Visit may exist in the complete inventory, but is not promoted into
summary context.

## Prompt completeness

Authoritative provider context is also bounded:

- maximum 48 slots
- maximum 1600 characters for one Memory fact
- maximum 20000 total evidence characters

If all authoritative facts cannot fit these bounds, the service returns
`SUMMARY_INCOMPLETE`. It never truncates an overlong Memory and calls the result complete.

Provider-visible slots contain only:

- opaque slot ID `D1`, `D2`, ...
- fact kind
- fact text
- event time
- Visit end time when relevant
- server-derived provenance label

They do not expose user IDs, Memory IDs, MemorySource IDs, Visit IDs, Place IDs, vectors,
arbitrary metadata, storage keys, media URLs, or authorization fields.

## Prompt-injection boundary

Slot text is serialized as quoted JSON input data and is never concatenated into system
instructions.

The static system instruction says that slot content is untrusted data and must not alter
system rules. The model may not use outside knowledge or invent missing events.

## Provider output

The exact accepted shape is:

```json
{"summary":"...","citations":["D1","D2"]}
```

The citation list must contain every provider-visible slot exactly once. This does not make
provider citations authoritative; it only prevents a declared "complete" summary from
omitting server-visible day facts at the output-contract level.

Malformed JSON, extra keys, duplicate slots, unknown slots, missing slots, or an empty
summary fail closed.

## Complete-snapshot revalidation

The service validates completeness twice:

1. immediately before provider I/O;
2. immediately after provider I/O.

Both checks re-read:

- persisted timezone and local-day bounds;
- full bounded raw Memory inventory and Memory state fingerprints;
- the S3-013 authority projection for **every raw day Memory**, including excluded ones;
- full bounded raw Visit inventory and derived provenance fields.

This catches facts inserted, deleted, edited, retimestamped, moved across day boundaries,
or changed only through Evidence/trust state while generation is in flight.

For example, a raw day Memory that begins as `NO_EVIDENCE` and gains a qualifying
`MemorySource` during provider I/O changes to `EVIDENCE_SUPPORTED`; even if its Memory
row is byte-for-byte unchanged and it never had a D-slot, the whole generated summary is
rejected as stale.

After raw inventory and all-Memory authority validation, every provider-visible
Memory/Visit slot is independently revalidated again against its authoritative
trust/provenance rules.

Any drift returns `DATA_CHANGED_DURING_GENERATION` with no summary/citations.

## Read-only / transaction boundary

All authoritative reads use independent short-lived `autoflush=False` sessions.

Provider I/O occurs after those read sessions have closed and does not hold the caller's
database transaction.

The foundation persists no generated summary and writes no Memory, Evidence, Visit,
Reminder, or trust state.

## Explicitly out of scope

- public open-ended chat
- monthly summary
- yearly summary
- summary persistence/cache
- provider-selected IDs
- trust promotion
- Reminder creation
- global/web knowledge
- UI redesign
- multimodal summarization.
