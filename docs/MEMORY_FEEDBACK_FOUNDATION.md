# Memory Feedback Foundation

Issue #83 / S3-018 adds explicit authenticated user feedback for a Memory revision.

## Actions

```text
CONFIRM
CORRECT
DELETE
```

The authority is always an explicit authenticated user action. AI/provider output has no path into
this service.

## Core transaction boundary

```text
authenticated user
+ stable Idempotency-Key
+ memory_id
+ expected_revision
        ↓
owner-scoped Memory FOR UPDATE
        ↓
current revision check
        ↓
revision-bound MemoryFeedback audit
        ↓
existing trusted mutation path when required
```

Old-revision feedback fails closed with `MEMORY_FEEDBACK_REVISION_CONFLICT`.

## CONFIRM

CONFIRM records one audit fact for the exact current revision.

It does **not** directly mutate `Memory.is_confirmed`, confidence, source_type or S3-013 answer
trust state. Therefore confirming revision N cannot silently authorize revision N+1 after a later
edit.

Repeated CONFIRM for the same owner/memory/revision is duplicate-safe and resolves to the same
audit event. Stable client-operation replay is protected by the existing ClientMutation fingerprint
boundary plus a PostgreSQL transaction-scoped advisory single-flight keyed by
`(user_id, operation_type, client_uuid)`.

The single-flight lock is acquired before `create_resource()`, so same-key concurrent CORRECT or
DELETE calls cannot race Memory revision/delete side effects. After the winner commits, an identical
loser replays the same feedback resource; a different payload with the same key deterministically
fails with `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST`.

## CORRECT

CORRECT does not contain a second edit engine.

It constructs the existing `MemoryUpdate` contract and calls `edit_memory(...)`. Therefore the
existing row lock, MemoryEdit history, USER_TEXT MemorySource semantics, revision increment and
embedding invalidation remain authoritative.

The feedback row records:
- `memory_revision`: the revision the user judged incorrect;
- `result_revision`: the new revision produced by the existing edit flow.

A fresh CORRECT request that makes no actual change is rejected so S3-019 cannot count a no-op as a
real correction.

## DELETE

DELETE uses the existing locked Memory plus `soft_delete_memory(...)`.

That preserves existing embedding invalidation, ObjectLocation staling and Reminder
cancel/detach behavior. The DELETE audit and soft delete commit in the same idempotent transaction.

After deletion, new confirm/correct requests see the same owner/deleted not-found boundary.

## Structured ObjectLocation boundary

The generic feedback seam rejects backing `OBJECT_LOCATION` Memory. Structured location truth
must continue through its dedicated structured flow instead of mutating a backing Memory shortcut.

## Audit / deletion lifecycle

`memory_feedbacks` stores only server-owned audit metadata:

- owner
- Memory ID
- stable client operation UUID
- judged revision
- optional correction result revision
- action
- creation time

It does not duplicate Memory content or MemoryEdit before/after payloads.

The table is included in Data Delete explicit inventory and deletion counts. Account Delete reaches
the same cleanup through the existing Data Delete-first lifecycle, with database FK cascade as a
final hard-delete guard.

## Out of scope

- AI auto-confirm
- model training/retraining loop
- S3-019 metric aggregation/dashboard
- ranking changes
- RAG trust promotion
- new generic Memory edit/delete semantics
