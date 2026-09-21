# Vision Foundation

Issue #65 introduces a narrow, user-triggered image-understanding boundary for S3-007.

## Contract

```text
authenticated user
  -> POST /v1/media/{media_id}/vision
  -> owner-scoped READY + completed + IMAGE gate
  -> bounded read of the private final object
  -> AIGateway image inference (purpose=vision.observe)
  -> strict kind + controlled-code parser
  -> server-owned display label
  -> post-I/O Media revalidation
  -> deletion-generation guarded commit
  -> inference-only VisionResult
```

The public endpoint accepts only the authenticated request context plus the path
`media_id`. Storage keys, URLs, provider/model selection, credentials, confidence,
trust labels, entity IDs, and persistence choices are not client-controlled.

## Observation boundary

Provider output deliberately has no arbitrary descriptive-text field:

```json
{
  "observations": [
    {"kind": "SCENE", "code": "INDOOR"},
    {"kind": "OBJECT", "code": "BAG"},
    {"kind": "ACTIVITY", "code": "PERSON_SITTING"}
  ]
}
```

The server validates each kind/code pair against a fixed safe vocabulary and maps it to
the public label. A model therefore has no provider-controlled label field where it can
hide a person's identity, precise address, OCR text, motives, relationships, sensitive
traits, confidence, trust level, or entity ID.

Extra fields, unsupported/mismatched codes, duplicates, oversized output and malformed
JSON fail closed. The service, not the provider, assigns display labels, indices and
`trust_class=inference`.

## Privacy semantics

The vocabulary intentionally stays coarse:

- a person may be observed only as generic `PERSON` or a generic visible activity;
- scene codes describe visual scene type, never a real-world precise location;
- there are no identity, relationship, medical, political, religious, race/ethnicity,
  sexual-orientation, intent or motive fields/codes;
- uncertainty does not become confidence: Vision exposes no confidence field.

This foundation can lose detail rather than invent or expose a forbidden inference.

## OCR separation

OCR and Vision remain separate user actions:

- OCR answers what visible text is present.
- Vision returns safe coarse scene/object/activity candidates.
- Vision never calls OCR and its provider schema has no text-transcription field.
- Neither feature writes directly to Memory Pipeline or Store.

A future multimodal integration must define its own Evidence and trust transition.

## Transaction and deletion boundary

The service deliberately splits work into three phases:

1. lock and snapshot the authoritative Media row, then commit;
2. perform private object read and model I/O with no long-running DB transaction;
3. lock/revalidate Media, then make a read-only guarded commit.

The final guarded commit rechecks the account/data-deletion generation. A request admitted
before destructive deletion therefore cannot return a stale inference after that boundary
changes.

## Persistence

Vision creates or modifies none of:

- Memory / MemorySource
- Object / Place
- Visit
- Reminder
- Entity Link state

A Vision-only result therefore does not make `/memory/query` answerable; the existing
`NO EVIDENCE -> NO MEMORY` rule remains unchanged.

## Media formats

This foundation accepts JPEG, PNG, and WebP. HEIC/HEIF fails closed until a trusted
server-side conversion boundary is introduced.
