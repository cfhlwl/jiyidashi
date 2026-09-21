# Structured First Retrieval

Issue #73 / S3-010 introduces an internal read-only candidate retrieval seam for later
Memory RAG. It does not generate answers and does not change current `/memory/query`.

## Precedence

```text
STRUCTURED
  > KEYWORD
  > VECTOR
  > LLM_ASSISTED_QUERY_FALLBACK
```

This is retrieval precedence only. It is not a trust ranking.

The first tier that produces usable candidates wins. A recognized authoritative Object
whose CURRENT ObjectLocation is absent is a terminal structured miss: lower tiers must not
resurrect STALE/UNKNOWN location history.

## STRUCTURED

The first S3-010 structured selector is deliberately narrow:

```text
owner Object identity
+ object-location intent
+ CURRENT ObjectLocation
+ owner/non-deleted backing Memory
```

Object resolution is bounded. The database first narrows to owner Objects whose compact
name is actually contained in the compact query and fetches at most 33 rows: 32 usable
candidate slots plus one overflow sentinel. Overflow returns the typed fail-closed status
`CANDIDATE_LIMIT_REACHED`; the full owner Object catalog is never loaded into Python.

The candidate carries the backing `memory_id` plus an `OBJECT_LOCATION` structured
reference. Object ambiguity is fail-closed.

## KEYWORD

Keyword retrieval uses bounded deterministic server-owned terms over persisted:

- owner-scoped Memory
- non-deleted Memory
- title/content
- excluding `MemoryType.OBJECT_LOCATION`

Unconfirmed/AI-only Memory can be retrieved internally, but its candidate remains
`answer_eligible=false`. Keyword score never changes Evidence trust.

## VECTOR

VECTOR runs only when STRUCTURED and KEYWORD produce no usable candidate.

Query embeddings:

- use the server-only S3-009 `EmbeddingGateway`
- use the reviewed model/dimensions
- are transient and never persisted by S3-010
- are never exposed by a public endpoint

Vector candidate SQL requires:

```text
MemoryEmbedding.user_id == trusted user_id
Memory.user_id == trusted user_id
MemoryEmbedding.memory_id/user_id rejoin authoritative Memory
Memory.is_deleted == false
Memory.memory_type != OBJECT_LOCATION
embedding.model/dimensions == current policy
embedding.memory_revision == Memory.edit_revision
```

Candidates are then post-validated against the current canonical Memory fingerprint.
Because that fingerprint validation is application-side, vector retrieval uses bounded
keyset pagination ordered by:

```text
(cosine distance ASC, memory_id ASC)
```

Each page validates at most 8 rows and the whole request validates at most 32 rows.
Stale nearest rows therefore cannot hide a later valid candidate inside the validation
window. If the window is exhausted before retrieval can finish, the result is explicitly:

```text
VALIDATION_SCAN_LIMIT_REACHED
```

rather than incorrectly claiming `NO_USABLE_CANDIDATE`.

Cosine similarity orders only the VECTOR tier. It cannot change `EvidenceRankClass` or
`answer_eligible`.

## Evidence Ranking

Candidate Memory IDs are enriched through the merged S3-012
`rank_evidence_sources(...)` seam. The best ranked persisted source is exposed only as
typed metadata:

- `EvidenceRankClass`
- best `memory_source_id`
- current answer-eligibility summary

No evidence score is persisted or blended with retrieval score.

## Read-only / no-autoflush

Retrieval reads only committed database state through independent
`autoflush=False` sessions derived from the caller's engine. Caller pending/dirty ORM
state is not flushed or considered a candidate.

Provider I/O occurs before opening the VECTOR database read transaction.

## LLM fallback

This PR intentionally does not implement query rewrite. The typed result always records:

```text
LLM_ASSISTED_QUERY_FALLBACK = NOT_ATTEMPTED
```

No provider can return Memory IDs, Entity IDs, trust labels or answer text through S3-010.

## Out of scope

- Memory RAG / answer generation
- citation synthesis
- public retrieval endpoint
- persisted query vectors
- blended cross-tier scores
- OCR/Vision/image embeddings
- embedding backfill
