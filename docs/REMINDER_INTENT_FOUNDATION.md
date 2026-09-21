# Reminder Intent Foundation

Issue #78 / S3-014 defines an inference-only reminder-intent candidate seam.

## Core invariant

```text
AI detects reminder intent
→ typed candidate only
→ user reviews/confirms
→ existing authenticated/idempotent Reminder create path
```

Never:

```text
AI output
→ Reminder row
```

## Typed states

- `NO_REMINDER_INTENT`
- `REMINDER_CANDIDATE`
- `AMBIGUOUS`
- `PROVIDER_FAILED`

Every positive candidate carries server-owned
`requires_user_confirmation=True`.

The provider contract has no confirmation field.

## Input/privacy boundary

Only the explicit current user text passed to the extractor is sent through S3-001
`AIGateway`.

The foundation does not scan or prompt with:

- Memory history;
- location/background data;
- photos;
- OCR/Vision output;
- RAG answers;
- other users' data.

The provider never receives user_id, Memory ID, Reminder ID, ReminderStatus, idempotency key, or
the persisted timezone.

## Strict provider output

The only accepted provider keys are:

```json
{
  "has_reminder_intent": true,
  "title_span": "literal source span",
  "content_span": null,
  "time_span": "literal source span"
}
```

Extra or missing keys are rejected. `has_reminder_intent` is a strict JSON boolean: strings such as `"true"` / `"false"` and numeric `1` / `0` are malformed and fail closed rather than being coerced.

Every non-null span must be copied verbatim from the explicit current user input. Provider output
containing IDs, status, timezone, confirmation authority, or any other extra field fails closed.

User text is explicitly treated as data, not as instructions for tools/actions.

## Server-owned time semantics

The provider returns only literal `time_span` text. It never returns an authoritative timestamp
or timezone.

The server loads the user's persisted IANA timezone through an independent
`autoflush=False` read Session and interprets time against an explicit timezone-aware `now`.

This first foundation deliberately supports only a narrow deterministic grammar:

- `N分钟后` (bounded);
- `N小时后` (bounded);
- `今天 HH:MM`;
- `明天 HH:MM`.

Anything else remains `AMBIGUOUS`; it is never guessed.

Local wall clocks are round-tripped through `zoneinfo`. DST ambiguous or nonexistent times are
rejected as `TIME_AMBIGUOUS_OR_NONEXISTENT`. Past/current times are not creatable candidates.

All resolved `remind_at` values are returned as aware UTC datetimes.

## Read/write boundary

Timezone lookup happens in a separate short-lived read Session. Caller pending/dirty ORM state is
neither autoflushed nor reused through its identity map.

The read Session is closed before provider I/O, so no DB lock/transaction is deliberately held
while waiting on the model.

Detection creates no:

- Reminder;
- Memory;
- MemorySource/Evidence;
- idempotency mutation;
- persisted inference state.

## Existing Reminder path stays authoritative

S3-014 does not import or call the existing Reminder create service or mutation helper.

After a future explicit user confirmation, product code must still construct the normal
`ReminderCreate` payload and use the existing write boundary, which continues to own:

- authenticated user identity;
- owner-scoped non-deleted Memory;
- future `remind_at`;
- stable idempotency key;
- duplicate/conflict handling;
- initial `PENDING` state.

This PR does not implement that confirmation UI/write handoff.
