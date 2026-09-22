# Memory RAG Foundation

Issue #77 / S3-011 adds an internal read-only answer-generation seam on top of merged
S3-010 Structured First Retrieval, S3-012 Evidence Ranking, S3-013 Answer Trust State,
and S3-001 AI Gateway.

It does not add a public RAG/chat endpoint and does not change existing `/memory/query`.

## Core invariant

```text
NO EVIDENCE
→ NO MEMORY
→ NO ANSWER
```

Retrieval rank, vector similarity, provider confidence, or provider wording can never
promote a Memory into an answerable fact.

## Flow

```text
trusted user_id + question
→ S3-010 retrieve_memories
→ reject incomplete bounded retrieval
→ S3-013 authoritative trust re-resolution
→ keep only CONFIRMED / EVIDENCE_SUPPORTED
→ load current Memory.content + authoritative MemorySource reference
→ re-resolve trust before prompt construction
→ S3-012 trust-first ordering over authoritative source IDs
→ assign request-local E1/E2/... slots
→ bounded prompt
→ AIGateway inference
→ strict JSON parser
→ validate cited slots against server slot map
→ revalidate every prompt slot after provider I/O
→ only then honor validated provider citations
→ typed MemoryRAGResult
```

## Retrieval incomplete policy

Foundation behavior is conservative. Structured candidate overflow, vector validation scan
limits, and unsupported vector database paths never generate an answer.

A bounded partial search is never presented as complete recall.

Embedding-provider retrieval failure is typed separately as `PROVIDER_FAILED` with
provider stage `RETRIEVAL`.

## Trust authority

S3-010 candidate `answer_eligible` is diagnostic metadata only.

Immediately before prompt inclusion, S3-011 calls S3-013:

- `resolve_memory_answer_trust`
- `resolve_object_location_answer_trust`

Only current `CONFIRMED` and `EVIDENCE_SUPPORTED` state can enter the prompt.

`INFERENCE_ONLY` and `NO_EVIDENCE` are excluded even when a candidate has a high
keyword or vector score.

For edited Memory, S3-013 latest-content-edit semantics remain authoritative. The prompt
contains current `Memory.content`, and the internal citation binds the exact authoritative
`MemorySource.id` selected by S3-013.

## Evidence Ranking

S3-012 is used only after S3-013 has produced authoritative source IDs. Ranking decides
slot ordering only. It does not decide whether a Memory may answer and cannot promote trust.

## Prompt context

Provider-visible evidence slots contain only minimal server-owned fields:

- opaque slot: `E1`, `E2`, ...
- current text excerpt
- `occurred_at`
- server-derived trust presentation label
- whether the excerpt was truncated

Provider input excludes owner/user UUIDs, Memory IDs, source IDs, ObjectLocation IDs,
embeddings, retrieval scores, arbitrary metadata, storage keys, media URLs, authorization
fields, and secrets.

Bounds are fixed in the foundation:

- question: 4000 characters
- slots: 6
- per-slot excerpt: 1800 characters
- total evidence text: 9000 characters
- provider answer: 2000 characters
- citations: 6
- requested provider output budget: 512 tokens.

## Prompt-injection boundary

Evidence is serialized into the user/input payload as quoted JSON data. Evidence content
is never concatenated into the system instruction.

The static system instruction states that Evidence is untrusted user data, commands inside
Evidence are data rather than instructions, facts may come only from supplied slots, and
citations may name only server-issued slots.

## Provider output

The only accepted shape is exactly:

```json
{"answer":"...","citations":["E1","E2"]}
```

Validation is fail-closed:

- exact keys only;
- non-empty bounded answer;
- non-empty bounded citation list;
- citation strings only;
- duplicate citations rejected;
- unknown slot → `INVALID_CITATION`;
- malformed JSON / extra fields / empty citations → `MALFORMED_PROVIDER_OUTPUT`.

The provider cannot return `can_answer`, trust state, Memory IDs, source IDs, or owner IDs
as authority.

## Post-provider revalidation

Provider I/O occurs after all database read sessions used to build the prompt have closed.

Before provider output is parsed into trusted citations, every slot that was actually sent
to the provider is revalidated against current persisted state. Provider citations are not
accepted as proof of which context influenced generation.

Each prompt slot must still satisfy:

- same trusted owner;
- Memory still exists and is not deleted;
- S3-013 state still answerable;
- same authoritative MemorySource;
- structured ObjectLocation still CURRENT when applicable;
- same edit revision;
- same current content fingerprint;
- same `occurred_at`.

Any prompt-slot drift returns `EVIDENCE_CHANGED_DURING_GENERATION` with no answer or
citations, even if the provider omitted that changed slot from its citation list.

## Read/write boundary

S3-011 never writes Memory, MemorySource, MemoryEdit, MemoryEmbedding, Object,
ObjectLocation, Reminder, or generated answer state.

The caller's pending/dirty ORM identity map cannot enter the prompt because authoritative
reads use independent `autoflush=False` sessions.

## Out of scope

- open-ended chatbot orchestration
- public RAG endpoint
- web/global knowledge
- provider-selected Memory IDs
- trust promotion
- answer persistence
- reminder creation
- daily/monthly/yearly summaries
- UI trust badges
- multimodal answer generation
- arbitrary model tool calling.
