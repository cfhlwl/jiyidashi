# Monthly Summary Foundation

Issue #86 / S3-016 implements an internal, read-only, trust-preserving monthly recollection
seam for one exact local calendar month.

It does not call provider-generated Daily Summary outputs as factual input, and it does not
use S3-011 top-k retrieval as a substitute for month completeness.

## Core invariant

```text
persisted User.timezone
→ exact local YYYY-MM
→ complete bounded raw Memory / Visit inventory
→ freeze S3-013 authority for every raw Memory
→ authoritative opaque M1/M2/... slots
→ AIGateway
→ strict monthly summary/citation parser
→ revalidate complete inventory + all raw-Memory authority + all visible slots
→ MonthlySummaryResult
```

A partial month is never presented as a complete month.

## Server-owned month

The internal API accepts either:

- no target month: derive the current local month from one captured server timestamp and
  persisted `User.timezone`;
- a strict server-validated `YYYY-MM`.

Callers cannot provide arbitrary UTC start/end boundaries.

The month starts at local midnight on day 1 and ends at local midnight on day 1 of the next
month. December → January rollover and leap-year February therefore use calendar semantics,
not fixed-duration arithmetic.

Invalid persisted timezone values fall back to UTC consistently with the existing time
foundation.

## Complete bounded inventory

Monthly Summary scans underlying authoritative data directly.

It never summarizes generated Daily Summary text.

Memory scan:

- trusted owner only;
- non-deleted;
- `occurred_at >= month_start`;
- `occurred_at < month_end`;
- deterministic `(occurred_at, id)` ordering;
- maximum 256 rows plus one overflow sentinel.

Visit scan:

- trusted owner Visit;
- owner-scoped Place join;
- overlap semantics:
  - `arrived_at < month_end`;
  - `left_at IS NULL OR left_at >= month_start`;
- deterministic `(arrived_at, id)` ordering;
- maximum 128 rows plus one overflow sentinel.

Any raw scan overflow returns `SUMMARY_INCOMPLETE` before provider I/O.

## All-Memory authority projection

Every raw month Memory receives a frozen S3-013 projection:

```text
memory_id
trust_state
trust_reason
evidence_source_id
```

The projection is retained for both answerable and excluded Memory.

Only current:

- `CONFIRMED`;
- `EVIDENCE_SUPPORTED`;

may enter provider context.

`INFERENCE_ONLY` and `NO_EVIDENCE` remain in the month snapshot as excluded authority
states, so Evidence-only promotion or demotion during provider I/O invalidates the whole
result.

Latest edit-source semantics remain authoritative. A visible Memory slot uses current
`Memory.content` plus the exact current `MemorySource.id` selected by S3-013.

## Visit authority

Visit enters provider context only when all deterministic provenance rules hold:

- finalized;
- `source == LOCATION_CLUSTER`;
- finite confidence >= 0.6;
- derivation key present;
- source fingerprint present;
- at least two source points;
- algorithm version present;
- owner-scoped Place exists.

Mutable/unfinalized Visits remain part of the complete raw inventory but are not promoted
into provider context.

## Provider-context completeness

Provider context is complete-or-fail:

- maximum 96 authoritative slots;
- maximum 1200 characters for one Memory fact;
- maximum 32000 evidence characters total.

If every authoritative fact cannot fit within these fixed bounds, the service returns
`SUMMARY_INCOMPLETE`.

It never chooses important days, top events, representative facts, or other semantic
subsets in this foundation.

## Prompt boundary

Provider-visible fields are limited to:

- opaque request-local slot: `M1`, `M2`, ...;
- kind: Memory or Visit;
- fact text;
- event timestamp;
- Visit end timestamp when applicable;
- server-derived provenance label.

Provider does not receive User UUID, Memory ID, MemorySource ID, Visit ID, Place ID,
embeddings, retrieval scores, arbitrary metadata, storage keys, media URLs, authorization
fields, or secrets.

Evidence is serialized as quoted JSON data and is never concatenated into system
instructions.

The static system instruction explicitly treats slot text as untrusted data and forbids
outside knowledge or invented chronology/patterns.

## Strict provider output

The only accepted shape is:

```json
{"summary":"...","citations":["M1","M2"]}
```

The citation set must contain every provider-visible slot exactly once.

Malformed JSON, extra keys, duplicate citations, unknown citations, missing citations, or an
empty summary fail closed.

Provider citations do not prove which context influenced generation; all visible context is
revalidated independently.

## Complete-snapshot revalidation

Before provider I/O and again after provider I/O, the service revalidates:

- persisted timezone and exact local month bounds;
- complete bounded raw Memory inventory;
- complete bounded raw Visit inventory including Place name/provenance;
- S3-013 authority projection for every raw Memory, including excluded Memory;
- every provider-visible Memory/Visit slot.

This catches:

- inserts;
- deletes;
- content edits;
- retimestamping across month boundaries;
- Evidence-only trust promotion/demotion;
- Place rename;
- Visit provenance/finalization drift;
- timezone drift.

Any change returns `DATA_CHANGED_DURING_GENERATION` with no summary or citations.

## Read-only and transaction boundary

All authoritative reads use independent short-lived `autoflush=False` sessions.

Provider I/O occurs after those read sessions have closed and does not hold the caller's
database transaction.

The foundation writes no generated summary, Memory, MemorySource, Visit, Reminder, or trust
state.

## Explicitly out of scope

- public open-ended chat;
- annual summary;
- summary persistence or cache;
- generated Daily Summary as factual source;
- semantic top-N event selection;
- provider-selected IDs;
- trust promotion;
- Reminder creation;
- global/web knowledge;
- UI redesign;
- multimodal monthly summary.
