# Evidence Ranking Foundation

Issue #70 / S3-012 defines an internal deterministic trust ordering over existing
`MemorySource` evidence.

## Fixed trust order

The server-owned precedence is:

```text
USER_DIRECT > SENSOR_DIRECT > SYSTEM_DERIVED > AI_INFERENCE
```

Current `SourceType` mapping:

| Rank class | SourceType |
| --- | --- |
| USER_DIRECT | USER_TEXT, USER_VOICE, USER_PHOTO |
| SENSOR_DIRECT | GPS, PHOTO_EXIF |
| SYSTEM_DERIVED | SYSTEM_PLACE |
| AI_INFERENCE | AI_INFERENCE |

An unknown future source type fails closed until its trust class is explicitly reviewed.

## Same-class tie-break

Only evidence already inside the same rank class may use secondary ordering:

1. higher persisted `MemorySource.confidence`;
2. newer persisted `MemorySource.created_at`;
3. stable ascending `MemorySource.id`.

Confidence and recency can never move evidence across a rank-class boundary. For example,
an `AI_INFERENCE` source at confidence 0.99 still ranks below `USER_TEXT` at 0.50.

## Owner and lifecycle boundary

`rank_evidence_sources(...)` joins `MemorySource` through its backing `Memory` and requires:

- `Memory.user_id == trusted user_id`;
- `Memory.is_deleted == false`;
- optional candidate Memory IDs still remain constrained by the same owner predicate.

A source attached to another owner's Memory therefore cannot enter the ranking set, even if its
Memory ID is supplied as a candidate.

## Ranking is not confirmation

Rank class is derived from each persisted `MemorySource.source_type`, not from
`Memory.is_confirmed`.

This distinction is intentional. A Memory Pipeline result may remain an unconfirmed
`AI_INFERENCE` Memory while retaining direct original `USER_TEXT` evidence. That evidence may
rank as `USER_DIRECT`, but ranking does **not** promote the Memory to confirmed or make it
answerable.

Existing `/memory/query` and day-summary trust gates remain authoritative and unchanged.

## Read-only contract

S3-012:

- creates no migration;
- adds no table or ranking-score column;
- writes no Memory, MemorySource, Evidence, or trust state;
- adds no public ranking endpoint;
- does not call an LLM/provider;
- does not use embeddings or vector similarity;
- does not add reranking, RAG, or answer generation.

The evidence SELECT executes inside `Session.no_autoflush`, so a caller's unrelated pending or dirty ORM state is not flushed as a side effect of ranking. Pending `MemorySource` rows therefore do not enter the persisted ranking set merely because this read seam ran.\n\nThe service returns immutable in-memory `EvidenceRankedSource` metadata only.

## Future handoff

S3-010 may later combine retrieval candidates with this ranking seam, but retrieval similarity
must remain independent from Evidence trust class. S3-013 may define answer-state presentation;
S3-012 does not.
