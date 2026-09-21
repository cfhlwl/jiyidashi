# Answer Trust State Foundation

Issue #74 / S3-013 defines an internal, server-owned trust/presentation classification for
authoritative current Memory and Evidence state.

## Four states

```text
CONFIRMED
EVIDENCE_SUPPORTED
INFERENCE_ONLY
NO_EVIDENCE
```

These states are not retrieval tiers and are not model scores.

### CONFIRMED

This foundation uses CONFIRMED for a structured `CURRENT ObjectLocation` whose backing Memory
also satisfies the existing confirmed/non-AI/confidence/Evidence gates.

A stale/unknown historical ObjectLocation can never produce CONFIRMED.

### EVIDENCE_SUPPORTED

A generic current Memory resolves to EVIDENCE_SUPPORTED when all existing answerability gates
are satisfied:

- owner matches trusted server context;
- Memory is not deleted;
- Memory is confirmed;
- Memory source is not AI_INFERENCE;
- Memory confidence is at least the existing 0.6 threshold;
- the current text revision has qualifying non-AI MemorySource Evidence at confidence >= 0.6.

This intentionally preserves the existing public Memory-query presentation semantics
(`certainty="evidence"`).

### INFERENCE_ONLY

An unconfirmed or AI-derived Memory resolves to INFERENCE_ONLY even if it retains stronger
original Evidence for provenance.

That distinction is critical for Memory Pipeline output: a USER_DIRECT-ranked original
`USER_TEXT` source does not promote its unconfirmed AI Memory.

INFERENCE_ONLY is non-answerable.

### NO_EVIDENCE

Deleted/cross-owner/unavailable Memory, a failed existing confidence gate, missing qualifying
current Evidence, or non-current structured ObjectLocation resolves fail-closed to NO_EVIDENCE.

## Current edit semantics

If Memory content has been edited, the latest content-changing `MemoryEdit.memory_source_id`
is the only Evidence source allowed to prove the current text.

The resolver requires that source to be the USER_TEXT source produced by the trusted edit flow.
It never falls back to an old photo/voice/source if the current edit Evidence is missing or
malformed.

Title-only edits do not replace content Evidence.

## Separation from retrieval and Evidence Ranking

```text
retrieval tier / keyword score / vector similarity
!=
EvidenceRankClass
!=
AnswerTrustState
```

The Memory resolver accepts only:

- database Session;
- trusted `user_id`;
- authoritative `memory_id`.

It accepts no retrieval score, provider confidence, rank class or client-supplied trust state.
Arbitrary `metadata_json` fields are ignored.

S3-012 may describe the strength/order of Evidence, but cannot promote AnswerTrustState.

## Read-only / persisted-state boundary

The public resolver receives the caller Session only to locate the database Engine. It then opens
a separate short-lived `autoflush=False` read Session.

This is stricter than `no_autoflush` alone:

- caller pending/dirty ORM state is not flushed;
- caller identity-map mutations are not reused as authoritative rows;
- a dirty in-memory Memory cannot change persisted confirmation/source/confidence semantics;
- a dirty in-memory MemorySource cannot raise persisted Evidence confidence or source trust;
- only committed persisted state can choose AnswerTrustState.

S3-013 creates no migration, table, column, score or database write.

## Public compatibility

This initial foundation does not change public API schemas or routes.

It is designed to map later without semantic change:

- CONFIRMED → existing structured confirmed behavior;
- EVIDENCE_SUPPORTED → existing evidence behavior;
- INFERENCE_ONLY → `can_answer=false`;
- NO_EVIDENCE → existing unknown / `NO_EVIDENCE`.

S3-011 RAG and future UI presentation may consume this typed internal source of truth later.
