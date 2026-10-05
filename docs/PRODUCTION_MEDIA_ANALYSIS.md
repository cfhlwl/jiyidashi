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
```

The analysis byte ceiling is intentionally materially lower than the original-media
ceiling. Production preflight rejects absent, invalid, or inconsistent values.

## Derivative pipeline

For JPEG, PNG, and WebP sources:

```text
owner-scoped READY media snapshot
→ bounded original object read using authoritative MediaAsset size/policy
→ verify declared MIME matches trusted decoder format
→ reject multi-frame images
→ header-level source pixel bomb guard
→ deterministic EXIF orientation
→ resize without upscaling to dimension/pixel policy
→ convert to JPEG and strip metadata
→ quality/size convergence
→ final <= AI_IMAGE_MAX_BYTES
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
- OCR/Vision and deletion/media-change regressions remain green;
- full backend and production config gates remain green.
