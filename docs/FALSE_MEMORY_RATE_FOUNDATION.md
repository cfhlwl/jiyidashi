# False Memory Rate Foundation

Issue #87 / S3-019 defines a deterministic quality metric derived only from explicit
S3-018 Memory feedback.

## Metric unit

The unit is one judged Memory revision:

```text
(user_id, memory_id, memory_revision)
```

Feedback rows are first collapsed to that revision unit.

## Canonical adjudication

```text
if CORRECT exists:
    FALSE
else if CONFIRM exists:
    CONFIRMED_TRUE
else:
    UNJUDGED
```

Therefore:

- CONFIRM then CORRECT on the same revision counts once as FALSE;
- CORRECT then DELETE remains FALSE;
- CONFIRM plus DELETE remains CONFIRMED_TRUE;
- DELETE-only is not proof of false memory and is excluded from the judged denominator.

A CORRECT event's `result_revision` is not automatically judged. The new revision enters the
metric only after an explicit later CONFIRM or CORRECT.

## Result contract

```text
status
false_revisions
confirmed_true_revisions
judged_revisions
delete_only_revisions
false_memory_rate | null
```

`false_memory_rate = false_revisions / judged_revisions`.

When `judged_revisions == 0`, status is `NO_JUDGED_REVISIONS` and the rate is `null`, not 0%.

## Authority boundary

The service reads only persisted `MemoryFeedback` rows.

It does not inspect:

- Memory content;
- Memory confidence;
- Memory source_type;
- Memory is_confirmed;
- MemoryEdit rows;
- soft-delete state;
- Evidence Ranking;
- Answer Trust State;
- RAG citations;
- AI/provider output.

The owner filter is explicit in the feedback query.

A separate short-lived `autoflush=False` read Session prevents caller pending/dirty feedback from
becoming metric authority.

## Determinism

Aggregation is revision-scoped and insertion-order independent.

The SQL query groups by owner-filtered `memory_id + memory_revision`, then reduces each revision
through boolean presence of CORRECT / CONFIRM / DELETE.

Unknown persisted action values fail closed instead of being silently treated as unjudged.

## Privacy

The public result contains counts and one rate only. It returns no user IDs, Memory IDs, content or
raw feedback rows.

This foundation exposes no public HTTP endpoint.

## Deletion lifecycle

S3-018 Data Delete / Account Delete remains authoritative.

Once feedback rows are erased, subsequent metric computation no longer counts those judgments.
Real PostgreSQL coverage verifies both Data Delete and Account Delete transitions.

## Out of scope

- AI quality scoring;
- dashboard/UI;
- temporal cohorts;
- model retraining loop;
- ranking/RAG changes;
- new feedback actions;
- treating DELETE as FALSE;
- public analytics endpoint.
