# Mini Program Advanced V2 Surfaces

Issue #162 productizes the merged V2 backend foundations in the WeChat Mini Program.
It does not create new backend authority, prompts, providers, trust scores, entitlement
rules, or payment behavior.

## Navigation

The Mini Program exposes one coherent **人生** area from Today:

```text
人生
├─ 人生事件
├─ 人生阶段
│  └─ 长期回顾
├─ 多年时间线
└─ 回忆录
   ├─ 年度电子回忆录
   └─ 人生回忆录
```

Person Known Duration stays in existing Person Detail.

Elder mode does not gain these advanced edit controls. The Life entry is hidden from the
elder-focused Today surface; direct navigation explains that advanced editing belongs to
normal mode.

## Canonical API mapping

| Product flow | Canonical API |
| --- | --- |
| LifeEvent CRUD | `/v1/life-events` |
| LifeEvent Memory evidence | `/v1/life-events/{id}/memories` |
| LifeStage CRUD | `/v1/life-stages` |
| LifeStage event links | `/v1/life-stages/{id}/events` |
| Person Known Duration | `/v1/people/{person_id}/known-duration` |
| Long-term Reasoning | `/v1/life-stages/{id}/reason` |
| Cross-year History | `/v1/life-history/timeline` |
| Annual Memoir | `/v1/memoirs/annual` |
| Annual photo continuation | `/v1/memoirs/annual/{year}/photos` |
| Life Memoir stage index | `/v1/memoirs/life/stages` |
| Life Memoir chapter | `/v1/memoirs/life/stages/{stage_id}` |

All calls use the authenticated server session. No request in this surface accepts a
client-authored user/owner ID, evidence authority, confidence, trust state, plan code, or
AI success flag.

## Typed parsing and fail-closed behavior

`src/services/advancedV2.ts` validates:

- UUID shape;
- strict event/stage/status enums;
- required and nullable fields;
- bounded strings and integers;
- timezone-aware timestamps;
- strict four-digit years;
- citation identity consistency;
- opaque cursor type;
- generated-result status/content consistency.

Unknown enums/statuses fail closed. AI prose cannot render from malformed responses.

## Deterministic vs AI-generated surfaces

Deterministic/stored surfaces do **not** get SEC-013 AI labels:

- LifeEvent;
- LifeStage;
- Person Known Duration;
- Cross-year Life History;
- Life Memoir stage index;
- timeline rows;
- annual verified photo items.

Actual AI-generated surfaces reuse SEC-013:

```text
Long-term Reasoning ANSWERED
→ INFERRED

EVIDENCE_INCOMPLETE
→ UNCERTAIN

no evidence / provider failure / malformed / invalid citation / evidence changed
→ UNAVAILABLE
```

Annual narrative maps its canonical Annual Summary status through the same contract.
Life Memoir chapter maps its canonical Long-term Reasoning status through the same
contract. Citations keep their own kind/source/trust identity.

## Evidence and explicit relationships

LifeEvent Memory links use the existing owner-scoped Memory picker. AI_INFERENCE Memory
is excluded from the explicit evidence picker. The UI never accepts a free-form Memory
UUID.

LifeStage event links use only loaded canonical LifeEvent rows. No title/date similarity
or automatic linking is performed.

## Stale/session authority

Every new surface captures:

```text
auth owner
auth session epoch
request generation
resource/range/year identity
```

before awaiting. Success and error revalidate the same snapshot.

Auth switch, page hide, resource switch, range/year switch, mutation, and generation
invalidate old request generations. Stale success/error/citation/AI label/cursor/photo
pages cannot republish current state.

## Pagination

Cross-year History, Annual photo continuation, Annual timeline continuation, and Life
Memoir stage index pass backend cursors through unchanged.

Changing range/year or refreshing from the root clears the previous cursor chain before
publication. Annual photos come only from the memoir photo endpoint; a selected verified
`media_id` may request one short-lived `/media/{media_id}/download` transfer for user
preview. There is no object-storage listing or bulk signing.

## Mutations and generation

Local synchronous single-flight gates cover:

- LifeEvent create/update/delete/link/unlink;
- LifeStage create/update/delete/link/unlink;
- Long-term Reasoning;
- Annual Memoir generation;
- Life Memoir chapter generation.

These gates prevent duplicate local clicks only. Server revision/conflict/idempotency
semantics remain authoritative.

## Destructive confirmation boundary

LifeEvent/LifeStage deletion and relationship unlink use the existing local
`Taro.showModal` confirmation pattern.

This does not implement the global SEC-014 confirmation standard. Account deletion,
data deletion, Family grants, emergency/location confirmation, and export disclosure
remain #167.

## Commercial boundary

No pricing, purchase, SKU, renewal, receipt validation, or client-owned plan gate is
implemented. Typed backend entitlement errors can be displayed safely, but the Mini
Program does not invent paid/free product authority.

## Remaining work outside #162

- Flutter advanced V2 parity: #163
- global SEC-014 confirmation standard: #167
- real public-server acceptance: #136
- commercial packaging/payment rollout
- V3 remains out of scope
