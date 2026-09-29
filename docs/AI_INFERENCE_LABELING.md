# AI Inference Labeling V1

Issue #166 defines one shared user-facing presentation contract for **actual AI-generated
surfaces**. The contract must describe origin truthfully: deterministic retrieval or
server-side template formatting is not AI inference merely because it is evidence-backed.

It does not change Memory, Evidence, ObjectLocation, ranking, Family permission,
entitlement/quota, analytics, provider selection, or existing deterministic Query trust
semantics.

## Four AI presentation states

| State | Chinese product copy | Meaning |
| --- | --- | --- |
| `EXPLICIT` | 明确记录 | An authoritative stored record being shown as the record itself. |
| `INFERRED` | AI 推断（有证据支持） | AI-generated/synthesized output backed by canonical evidence. |
| `UNCERTAIN` | AI 推断（证据不足） | Backend explicitly reports an incomplete/partial AI result. |
| `UNAVAILABLE` | 暂不可用 | No safe AI-generated result can be shown. |

Color is never the only disclosure. AI labels use visible text; raw records and
deterministic retrieval responses must not be mislabeled as AI.

## Deterministic Memory Query is not an AI surface

Current canonical endpoint:

```text
POST /v1/memory/query
```

The current implementations are deterministic:

```text
FIND_OBJECT
confirmed ObjectLocation
→ deterministic location lookup
→ server template response

MEMORY_SEARCH
confirmed Memory rows
→ deterministic term scoring
→ server template response
```

Neither path calls AI Gateway or an AI provider. Therefore SEC-013 does **not** map
these responses to `INFERRED`.

Existing product trust presentation remains:

```text
can_answer=true + certainty=confirmed/evidence + canonical evidence
→ 有证据支持

canonical no-evidence
→ 没有足够证据
```

The clients still validate the response strictly. Contradictory, unknown, or malformed
Query payloads fail closed, but that parser validation does not assign AI origin.

`FIND_OBJECT` keeps its existing `certainty="confirmed"` backend semantic.
`MEMORY_SEARCH` keeps its existing evidence-backed semantic. A presentation task
must not rewrite those backend trust values just to fit an AI UI vocabulary.

## Evidence/source identity remains independent

Evidence provenance/source labels keep their canonical identity:

```text
USER_TEXT       → 用户文字记录
USER_VOICE      → 用户语音记录
USER_PHOTO      → 用户照片记录
GPS             → GPS 位置证据
PHOTO_EXIF      → 照片位置信息
SYSTEM_PLACE    → 系统地点识别
AI_INFERENCE    → AI 推测
```

No top-level presentation state may rewrite a source row into another provenance class.

## Trusted Summary mapping

Trusted Summary is an actual AI-generated surface and uses the four-state contract:

```text
DAILY_SUMMARY_READY
MONTHLY_SUMMARY_READY
ANNUAL_SUMMARY_READY
→ INFERRED

SUMMARY_INCOMPLETE
→ UNCERTAIN

NO_SUMMARIZABLE_EVIDENCE
PROVIDER_FAILED
MALFORMED_PROVIDER_OUTPUT
INVALID_CITATION
DATA_CHANGED_DURING_GENERATION
→ UNAVAILABLE
```

Unknown future status values fail closed. READY summaries keep canonical citations and
`trust_state` visible. Invalid or unavailable states never expose unvalidated generated
prose.

Flutter does not add a Summary page in #166; its shared helper retains the same mapping
for later #163 reuse.

## Cross-client origin rule

| Surface | Origin | Presentation |
| --- | --- | --- |
| Current FIND_OBJECT Query | deterministic retrieval/template | existing evidence trust UI, never AI INFERRED |
| Current MEMORY_SEARCH Query | deterministic retrieval/template | existing evidence trust UI, never AI INFERRED |
| Trusted Summary READY | AI-generated | `INFERRED` |
| Trusted Summary INCOMPLETE | AI-generated partial state | `UNCERTAIN` |
| Trusted Summary failure/invalid | AI surface unavailable | `UNAVAILABLE` |
| Explicit Memory record shown as itself | stored record | `EXPLICIT` |

Future Long-term Reasoning, Annual/Life Memoir, and other provider-generated surfaces
must reuse this contract only when their origin is genuinely AI-generated.

## What must never be labeled INFERRED

- deterministic `/v1/memory/query` FIND_OBJECT output;
- deterministic `/v1/memory/query` MEMORY_SEARCH output;
- a raw user-authored Memory;
- USER_VOICE / USER_PHOTO / GPS / PHOTO_EXIF / SYSTEM_PLACE evidence rows;
- malformed or unknown AI output;
- provider failure or invalid citation output.

## Stale/session safety

Query keeps its existing request generation plus authenticated owner/session guards.
Those guards remain useful even though Query is not an AI surface.

Trusted Summaries use their generation epoch:

```text
new generation / period switch / auth owner change / page hide
→ invalidate old generation
→ stale success/error cannot republish summary body or AI label
```

Flutter Query also clears already-published deterministic answer/evidence/trust UI on
owner/session changes.

## Scope boundary

#166 covers:

- shared EXPLICIT / INFERRED / UNCERTAIN / UNAVAILABLE semantics for actual AI surfaces;
- Mini Trusted Summaries;
- reusable Mini/Flutter presentation helpers for later real AI surfaces;
- strict fail-closed parsing;
- evidence/source independence;
- stale/session safety;
- documentation and focused regression coverage;
- explicit regression that deterministic Memory Query is **not** labeled AI.

It does not implement LifeEvent, LifeStage, Long-term Reasoning, Cross-year History,
new Memoir pages, payment/entitlement work, analytics, Family changes, SEC-014, or V3.

Future sequencing remains:

```text
#166 SEC-013
→ #162 Mini advanced V2 surfaces
→ #163 Flutter V2 parity
→ #167 SEC-014 confirmation standard
```
