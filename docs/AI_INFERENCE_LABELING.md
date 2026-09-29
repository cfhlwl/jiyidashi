# AI Inference Labeling V1

Issue #166 defines one shared presentation contract for Mini Program and Flutter.
It is a user-facing trust/presentation contract only; it does not change Memory,
Evidence, ranking, Family permission, Entitlement/quota, analytics, or provider
authority.

## Four states

| State | Chinese product copy | Meaning |
| --- | --- | --- |
| `EXPLICIT` | 明确记录 | An authoritative stored record being shown as the record itself. |
| `INFERRED` | AI 推断（有证据支持） | Generated/synthesized output backed by canonical evidence. It is not the raw record. |
| `UNCERTAIN` | AI 推断（证据不足） | Backend explicitly reports an incomplete/partial AI result. |
| `UNAVAILABLE` | 暂不可用 | No safe generated result can be shown. |

Color is never the only disclosure. Mini and Flutter render visible text labels;
Flutter also exposes a semantic label for the Query state.

## Memory Query mapping

Canonical surface:

```text
POST /v1/memory/query
```

`INFERRED` is allowed only for the exact canonical shape:

```text
can_answer == true
answer is non-empty
certainty == "evidence"
evidence is non-empty
memory_ids is non-empty
```

Canonical no-evidence maps to `UNAVAILABLE`:

```text
can_answer == false
answer == null
certainty == "unknown"
evidence is empty
memory_ids is empty
```

Any contradictory or future/unknown combination fails closed at the client parser.
Generated prose from a malformed response is never rendered.

The backend FIND_OBJECT top-level Query response also uses `certainty="evidence"`
so the public Query contract is uniform. This does not alter ObjectLocation or
Memory/Evidence authority.

## Evidence/source identity is independent

The top-level answer state never rewrites citation truth.

Examples remain:

```text
USER_TEXT       → 用户文字记录
USER_VOICE      → 用户语音记录
USER_PHOTO      → 用户照片记录
GPS             → GPS 位置证据
PHOTO_EXIF      → 照片位置信息
SYSTEM_PLACE    → 系统地点识别
AI_INFERENCE    → AI 推测
```

Therefore an `INFERRED` answer can cite an explicit `USER_TEXT` Memory, and an
`AI_INFERENCE` evidence row remains visibly identified as AI-derived. Neither side
promotes the evidence into another provenance class.

## Trusted Summary mapping

Mini Program uses the same presentation vocabulary:

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

Unknown future status values fail the strict Trusted Summary parser. No generated
summary body is displayed after a parser failure. READY summaries keep canonical
citations and `trust_state` visible.

Flutter does not add Summary UI in #166, but its shared presentation helper implements
the same status mapping so #163 can reuse the contract without redefining semantics.

## Cross-client parity table

| Canonical backend state | Mini | Flutter |
| --- | --- | --- |
| Query evidence-backed answer | `INFERRED` | `INFERRED` |
| Query canonical no-evidence | `UNAVAILABLE` | `UNAVAILABLE` |
| Summary READY | `INFERRED` | `INFERRED` contract reserved for #163 |
| Summary INCOMPLETE | `UNCERTAIN` | `UNCERTAIN` contract reserved for #163 |
| Summary invalid/failure | `UNAVAILABLE` | `UNAVAILABLE` contract reserved for #163 |
| Explicit Memory record shown as itself | `EXPLICIT` | `EXPLICIT` |

No caller-provided `isAi`, `trusted`, `success`, or equivalent flag can override
these mappings.

## What must never be EXPLICIT

- AI Query prose, even when it cites confirmed Memory;
- Daily/Monthly/Annual generated summary prose;
- future Reasoning/Memoir prose;
- provider/model output.

## What must never be INFERRED

- a raw user-authored Memory merely because it appears under an AI answer;
- a USER_VOICE/USER_PHOTO/GPS/PHOTO_EXIF/SYSTEM_PLACE evidence row;
- malformed/contradictory Query output;
- unknown future Summary status;
- provider failure or invalid citation response.

## Stale/session safety

Mini Query keeps its existing query epoch + authenticated owner/session epoch.
Mini Trusted Summaries now use an equivalent generation epoch:

```text
new generation / period switch / auth owner change / page hide
→ invalidate old generation epoch
→ old success and old error cannot publish content or label
```

Flutter Query keeps the existing request generation and `JiYiApiClient` authenticated
session snapshot. A response from an old owner/session is rejected before publication,
and page disposal invalidates the widget generation.

The presentation label and generated body are always published from the same accepted
response epoch.

## Scope boundary

#166 changes only:

- Mini Query;
- Mini Trusted Summaries;
- Flutter existing Memory Query;
- shared presentation helpers/tests/documentation;
- the Query `certainty` normalization required to keep the frozen public contract
  coherent.

It does not implement LifeEvent, LifeStage, Long-term Reasoning, Cross-year History,
new Memoir pages, payment/entitlement work, analytics, Family changes, SEC-014, or V3.

Future sequencing:

```text
#166 SEC-013
→ #162 Mini advanced V2 surfaces
→ #163 Flutter V2 parity
→ #167 SEC-014 confirmation standard
```
