# Flutter V2 Personal Memory Graph Parity

Issue: #163  
Priority: P1 / V2-CLOSE-P1-002  
Frozen baseline: `main = 3d7f2642e6dc6e498898dc85688c8ec4d5cc0f44`

## Scope

This document describes the Flutter productization layer for V2-001..V2-011 Personal Memory Graph parity.

Implemented product surfaces:

1. People CRUD + aliases
2. Person ↔ Memory links + recent interactions
3. Person Relationships
4. Unified Graph neighborhood
5. LifeEvent CRUD + Memory evidence
6. LifeStage CRUD + LifeEvent links
7. Person Known Duration
8. Evidence-backed Long-term Reasoning
9. Cross-year Life History
10. Annual Electronic Memoir
11. Life Memoir stage index + generated chapter

No backend authority, AI provider/prompt, entitlement, payment, SEC-014, production infrastructure, or V3 scope is added by #163.

## Navigation

The existing five-item mobile navigation remains unchanged.

The existing Timeline page exposes one non-Elder entry:

```text
个人记忆图谱
├─ 人物
│  ├─ People
│  ├─ Person detail
│  ├─ Relationships
│  ├─ Known Duration
│  └─ Graph
└─ 人生
   ├─ LifeEvent
   ├─ LifeStage
   │  └─ Long-term Reasoning
   ├─ Cross-year Life History
   └─ Memoirs
      ├─ Annual Memoir
      └─ Life Memoir
```

Elder mode does not expose the V2 graph entry. Account-delete recovery continues to use the existing AppShell recovery path and does not add a second V2 startup path.

## Canonical API mapping

Flutter uses only the merged server-owned V2 endpoints.

### People

```text
POST   /people
GET    /people
GET    /people/{person_id}
PATCH  /people/{person_id}
DELETE /people/{person_id}

POST   /people/{person_id}/memories/{memory_id}
PATCH  /people/{person_id}/memories/{memory_id}
DELETE /people/{person_id}/memories/{memory_id}
GET    /people/{person_id}/memories
GET    /people/interactions

POST   /people/relationships
GET    /people/relationships/{relationship_id}
PATCH  /people/relationships/{relationship_id}
DELETE /people/relationships/{relationship_id}
GET    /people/{person_id}/relationships

GET    /people/{person_id}/known-duration
```

### Graph

```text
GET /graph/neighborhood/{kind}/{entity_id}
```

### LifeEvent / LifeStage

```text
POST   /life-events
GET    /life-events
GET    /life-events/{life_event_id}
PATCH  /life-events/{life_event_id}
DELETE /life-events/{life_event_id}
GET    /life-events/{life_event_id}/memories
POST   /life-events/{life_event_id}/memories/{memory_id}
DELETE /life-events/{life_event_id}/memories/{memory_id}

POST   /life-stages
GET    /life-stages
GET    /life-stages/{life_stage_id}
PATCH  /life-stages/{life_stage_id}
DELETE /life-stages/{life_stage_id}
GET    /life-stages/{life_stage_id}/events
POST   /life-stages/{life_stage_id}/events/{life_event_id}
DELETE /life-stages/{life_stage_id}/events/{life_event_id}

POST   /life-stages/{life_stage_id}/reason
```

### History / Memoirs

```text
GET  /life-history/timeline
POST /memoirs/annual
GET  /memoirs/annual/{target_year}/photos
GET  /memoirs/life/stages
POST /memoirs/life/stages/{life_stage_id}
POST /media/{media_id}/download
```

The client never supplies a caller-authored `user_id`, trust/confidence, evidence authority, plan code, or AI status override.

## Typed contract and fail-closed parsing

V2 parsing lives under `mobile/lib/v2/`:

```text
v2_common.dart
people_models.dart
graph_models.dart
life_models.dart
memoir_models.dart
v2_api.dart
v2_authority.dart
```

The UI does not parse V2 `Map<String, dynamic>` values directly.

Strict validation includes:

- UUID format and endpoint identity
- enum membership
- required/null field combinations
- aware timestamps
- bounded strings and integers
- opaque cursors
- graph typed endpoint/edge/metadata consistency
- duplicate graph authority references
- citation identity
- citation trust
- duplicate citation slots
- AI provenance/status consistency
- Annual/Life Memoir status/result consistency

Malformed 2xx responses throw `ProtocolException` before the page publishes data, generated prose, citations, AI labels, or pagination state.

## Deterministic versus AI-generated surfaces

Deterministic surfaces are not marked as AI-generated:

- People
- Person aliases
- Person ↔ Memory links
- Person Relationships
- Unified Graph
- LifeEvent
- LifeStage
- Person Known Duration
- Cross-year Life History
- Annual timeline rows
- Annual photo records
- Life Memoir stage index

AI-generated surfaces are:

- Long-term Reasoning answer
- Annual Memoir narrative
- Life Memoir generated chapter

Citation rows keep their own canonical evidence identity and are not relabeled as AI-generated merely because the surrounding prose was generated.

## SEC-013 reuse

Long-term Reasoning uses the reviewed mapping exactly:

```text
ANSWERED                           → INFERRED
EVIDENCE_INCOMPLETE                → UNCERTAIN
NO_ANSWERABLE_EVIDENCE             → UNAVAILABLE
PROVIDER_FAILED                    → UNAVAILABLE
MALFORMED_PROVIDER_OUTPUT          → UNAVAILABLE
INVALID_CITATION                   → UNAVAILABLE
EVIDENCE_CHANGED_DURING_GENERATION → UNAVAILABLE
```

Long-term and Life Memoir citation rules:

```text
LIFE_STAGE
  stage required
  event/memory/source/trust null

LIFE_EVENT
  stage + event required
  memory/source/trust null

MEMORY
  stage + event + memory + source required
  trust ∈ {CONFIRMED, EVIDENCE_SUPPORTED}
```

Annual Memory citations allow only `CONFIRMED | EVIDENCE_SUPPORTED`. VISIT citations require null Memory trust. Duplicate slots fail closed.

The final #175 provenance matrix is preserved:

- `ANSWERED` requires provenance.
- `MALFORMED_PROVIDER_OUTPUT` and `INVALID_CITATION` require provenance.
- `NO_ANSWERABLE_EVIDENCE`, `EVIDENCE_INCOMPLETE`, and `PROVIDER_FAILED` forbid provenance.
- `EVIDENCE_CHANGED_DURING_GENERATION` accepts the canonical backend optional-provenance result.

## Owner/session/resource authority

`JiYiApiClient.requestV2Json()` reuses the existing authenticated-session snapshot:

```text
access token
+ authenticated user id
+ sessionVersion
```

After the HTTP response is decoded, the same snapshot is revalidated before publication.

V2 pages add `V2Authority` resource-generation identities for:

- People list/detail
- Person/Relationship mutations
- Graph entity
- LifeEvent
- LifeStage
- Long-term Reasoning generation
- history year range + cursor
- Annual Memoir target year + cursor
- signed media preview
- Life Memoir stage index + selected stage/chapter

Success and error paths both check the same owner/session/resource generation before publishing.

## Mutation/generation single-flight

`V2OperationFlight` is token and session scoped.

For the same owner/session, a second exact operation cannot start while the token is active.

If logout/account switch occurs while old work is pending:

1. the obsolete token is released;
2. the new owner/session can acquire a new token immediately;
3. the old result/error is stale;
4. the old `finally` cannot clear the new token.

This gate is used by People, Person-Memory, Relationships, LifeEvent, LifeStage, Long-term Reasoning, Annual Memoir, and Life Memoir chapter operations.

## Pagination authority

Cross-year History:

- cursor is opaque;
- start/end are server-returned and checked against the requested range;
- changing the range invalidates the old cursor chain;
- append requires the same owner/session/range identity.

Annual Memoir:

- timeline continuation uses the canonical history cursor;
- photo continuation uses `/memoirs/annual/{target_year}/photos`;
- changing the target year invalidates narrative, timeline cursor, photo cursor, and signed preview state.

Life Memoir:

- stage cursor is opaque;
- selected stage changes invalidate the old generated chapter;
- generated chapters are not restored across stage/owner/session changes.

## Offline boundary

#163 does not widen the existing offline queue.

New V2 CRUD and AI-generation operations:

```text
transport unavailable
→ explicit retryable error
→ no local authoritative success
→ no local-only People/LifeEvent/LifeStage row
```

Existing offline capture and location behavior remains under the existing `OfflineQueueStore` and `OfflineSyncCoordinator` contracts.

## Native location / privacy / account delete preservation

#163 does not create or initialize a second native location, sync, privacy, onboarding, or account-delete lifecycle.

The existing AppShell remains authoritative for:

- foreground/background location permission
- progressive permission prompts
- owner-scoped native location runtime
- Privacy Pause propagation
- offline location queue
- onboarding
- logout
- account-delete recovery
- local owner cleanup

The V2 entry is a route from Timeline after the existing AppShell has been established. It does not start native location or offline sync by itself.

## Destructive confirmation boundary

People, relationship, Person-Memory, LifeEvent, LifeEvent-Memory, LifeStage, and LifeStage-Event delete/unlink actions use explicit current mobile confirmation dialogs.

This is intentionally local product confirmation only. The global sensitive-operation standard remains #167 and is not implemented by #163.

## Accessibility and visual regression

V2 generated-state badges include semantic text containing both the label and explanatory disclosure; trust is not encoded by color alone.

The production pages use normal Material scrolling/controls and reusable `JiYiSectionCard`, `JiYiStatusBanner`, `JiYiEmptyState`, and V2 presentation widgets.

`mobile/test/visual_golden_test.dart` covers deterministic CJK-font baselines for:

- Person detail
- Graph neighborhood
- LifeEvent detail
- Long-term Reasoning ANSWERED
- Annual Memoir ready
- Life Memoir chapter ready
- AI unavailable/fail-closed state

## Explicit omissions after #163

Remaining work is intentionally outside this issue:

- #167 SEC-014 Sensitive Operation Confirmation Standard
- #136 real production DNS/TLS/object-storage/public-server acceptance
- commercial packaging/payment rollout
- V3 AI life assistant / graph reasoning / recommendations
- wearables/hardware
- new backend V2 authority
- new AI prompts/providers/models
- new trust/confidence scoring

## Formal review lock

Before #163 may leave Draft, exact-head evidence must prove:

```text
all 11 Flutter V2 flows exist
canonical APIs only
strict typed fail-closed parsing
no client-generated owner/trust/evidence authority
deterministic surfaces never mislabeled AI
real AI surfaces reuse SEC-013 exactly
citation trust/provenance exact
owner/session/resource/range/year stale success+error blocked
token-bound single-flight
offline queue not widened
native location/privacy/account-delete lifecycle unchanged
accessibility + committed goldens present
no #167/#136/commercial/V3 expansion
Mobile CI PASS
Mobile Visual Preview PASS
latest-main behind = 0
```
