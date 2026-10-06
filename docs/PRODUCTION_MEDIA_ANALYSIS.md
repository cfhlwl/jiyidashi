# AI Media Analysis Derivative V1

MEDIA-001 separates original user-media authority from transient AI analysis input.

## Authority

```text
READY MediaAsset + private original object
= authoritative user media

AI analysis derivative
= transient bounded provider input
= not a user original
= not Memory/Evidence/trusted fact
```

Uploading or completing media does not automatically invoke OCR or Vision.

## Production analysis policy

```text
MEDIA_MAX_IMAGE_BYTES=20971520
AI_IMAGE_MAX_BYTES=2097152
AI_IMAGE_MAX_DIMENSION=2048
AI_IMAGE_MAX_PIXELS=4000000
AI_IMAGE_PREPROCESS_GLOBAL_CONCURRENCY=2
AI_IMAGE_PREPROCESS_USER_CONCURRENCY=1
AI_IMAGE_PREPROCESS_PERMIT_LEASE_SECONDS=60
```

The analysis byte ceiling is intentionally materially lower than the original-media
ceiling. Production preflight rejects absent, invalid, or inconsistent values.

Image preprocessing has a separate PostgreSQL-backed shared concurrency budget. It is
claimed before the original object read and held only across bounded read, trusted decode,
orientation/resize/encode, and release of the original byte buffer. OCR and Vision share
the same `AI_IMAGE_PREPROCESS` service class. Provider concurrency remains a separate
resource budget and is claimed later by AIGateway.

The preprocessing lease is actively renewed while that RAM-heavy section is running.
Renewal is bound to permit id + secret token digest + service class and only succeeds
while the current lease is still live; an expired, forged, released, or replaced permit
cannot be resurrected. Heartbeat failure is fail-closed: the request does not proceed to
the AI provider. Production uses a 60-second lease with renewals multiple times per lease
period, so normal expiry cannot silently create an extra preprocessing slot.
Request cancellation also cannot release the slot while an already-started storage or
Pillow thread is still physically running: those workers are explicitly shielded and
drained to completion while the heartbeat remains active, and cancellation is propagated
only after the protected worker has stopped and the permit can be released safely.

## Derivative pipeline

For JPEG, PNG, and WebP sources:

```text
owner-scoped READY media snapshot
→ claim shared AI_IMAGE_PREPROCESS permit
→ bounded original object read using authoritative MediaAsset size/policy
→ verify declared MIME matches trusted decoder format
→ reject multi-frame images
→ header-level source pixel bomb guard
→ deterministic EXIF orientation
→ resize without upscaling to dimension/pixel policy
→ convert to JPEG and strip metadata
→ quality/size convergence
→ final <= AI_IMAGE_MAX_BYTES
→ release original bytes and AI_IMAGE_PREPROCESS permit
→ AI Gateway second-layer byte/type policy
→ provider
→ re-lock/revalidate original Media + deletion generation
```

The derivative exists only in process memory and is never uploaded, signed, exposed,
or persisted as a second media authority. The original private object remains unchanged.

HEIC/HEIF remain fail-closed with 415 until a reviewed trusted server decoder is
introduced. Animated/multi-frame inputs are rejected rather than multiplying decode
work.

## Privacy and deletion fencing

OCR/Vision keep the existing short-transaction authority model. Storage/decode/provider
I/O occurs after the initial media snapshot transaction is released, and the Media row
plus deletion generation is revalidated before returning inference. No OCR/Vision result
is automatically promoted to Memory or Evidence.

OPS-002 remains the sole stale-PENDING cleanup authority.

## Acceptance

Exact-head CI must prove:

- supported JPEG/PNG/WebP produce bounded JPEG derivatives;
- no derivative exceeds byte/dimension/pixel policy;
- small images are not upscaled;
- EXIF metadata is absent from provider-bound bytes;
- forged MIME and unsafe dimensions fail before provider disclosure;
- AI Gateway independently rejects bytes over AI_IMAGE_MAX_BYTES;
- preprocessing heartbeat keeps a real PostgreSQL slot live beyond its original lease;
- forged, expired, released/replaced permits cannot renew;
- renewal failure fails closed before provider disclosure;
- request cancellation keeps the permit/heartbeat alive until blocking storage/decode threads physically exit;
- OCR/Vision and deletion/media-change regressions remain green;
- full backend and production config gates remain green.
