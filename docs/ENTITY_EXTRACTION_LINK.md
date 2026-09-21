# Entity Extraction + Link Foundation

Issue #58 implements the S3-004 / S3-005 foundation as a candidate-only service boundary.

## Trust model

Extraction output is **AI inference metadata, not a personal fact**. The service never
writes Memory, MemorySource/Evidence, Object, Place or Person data. Person has no
persistence model in this line.

Model assistance is allowed only through the merged `AIGateway`. The provider receives
a fixed extraction instruction and may return only this JSON shape:

```json
{
  "entities": [
    {"kind": "OBJECT", "text": "护照"}
  ]
}
```

The parser is deliberately strict:

- top-level and candidate objects reject unknown fields;
- supported kinds are OBJECT / PLACE / PERSON / TIME / EVENT;
- candidate text must be a literal, trimmed substring of the source input;
- at most 20 candidates are accepted;
- provider-supplied IDs, owner IDs, confidence or link decisions are rejected;
- malformed or hallucinated output fails closed.

Each accepted candidate copies the AI Gateway provenance and keeps
`trust_class = inference`.

## Linking

Only OBJECT and PLACE candidates can link in this foundation.

The linker:

1. reads only the authenticated owner's existing Object / Place inventory;
2. applies deterministic lower-case + whitespace normalization;
3. links only when exactly one normalized match exists;
4. reports exact versus normalized match as metadata;
5. returns `UNRESOLVED / AMBIGUOUS` when duplicate names exist;
6. returns `UNRESOLVED / NO_MATCH` when no owner-scoped entity exists;
7. keeps PERSON / TIME / EVENT `UNRESOLVED / NOT_LINKABLE`.

There is no fuzzy matching and no second AI call for link selection. A model cannot
supply an entity ID, so it cannot redirect a link to another owner's row.

## Boundary with Memory Pipeline

This module is intentionally an internal service boundary. It does not modify Memory
Pipeline orchestration or persistence contracts. A later pipeline can consume these
candidate/link results while retaining its own Evidence and confirmation gates.
