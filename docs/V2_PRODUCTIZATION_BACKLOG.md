# V2 Productization Backlog

Source: Issue #160 / `docs/V2_FINAL_CLOSEOUT.md`.

This backlog records only productization/operations gaps discovered by the V2 closeout. Existing canonical OPS/SEC/BIZ IDs are referenced rather than duplicated.

## P0 — required before any public production launch

### V2-CLOSE-P0-001 — Complete real production acceptance
- **Why it matters:** CI proves deployment code, but public DNS/TLS/object-storage/mobile-domain assumptions remain unverified.
- **Current evidence:** OPS-001 deployment stack and production CI are code-complete; real public-server acceptance is deliberately deferred.
- **Acceptance criteria:**
  - OPS-001 public host deploy succeeds from reviewed image.
  - SEC-001 real HTTPS certificate/DNS passes.
  - SEC-002 private bucket policy is verified against the chosen provider.
  - SEC-003 signed upload/download works through real client domain allowlists.
  - SEC-009 location permission behavior is accepted on target production builds.
  - backup/restore and rollback are exercised in the real environment.
- **Dependency:** canonical `OPS-001`, `SEC-001`, `SEC-002`, `SEC-003`, `SEC-009`.
- **Recommended phase:** Public Launch Gate.
- **GitHub follow-up:** do not create a duplicate; OPS-001/Issue #136 is the canonical work item.

### V2-CLOSE-P0-002 — Production Observability Foundation V1
- **Why it matters:** a public service cannot be safely operated with only health checks and feature-local audit rows.
- **Current evidence:** `/health`, AI provider request IDs and Family audit exist; no standard request ID middleware, structured application logging contract, metrics export, AI latency metrics, storage error metrics or unified deletion/security alert hooks were found.
- **Acceptance criteria:**
  - every HTTP request receives/propagates a stable request ID;
  - structured logs include request ID, route, status, latency and safe actor/resource identifiers without sensitive payloads;
  - AI gateway exports purpose/provider latency and token counts without prompt/output bodies;
  - storage and destructive-lifecycle failures emit structured operational events;
  - health/readiness can distinguish process-up from required dependency readiness;
  - metrics/logs have documented retention and redaction policy;
  - exact-head CI covers redaction and correlation behavior.
- **Dependency:** OPS-001; complements SEC-005 and SEC-015 but does not replace them.
- **Recommended phase:** Public Launch Gate.
- **GitHub follow-up:** create a focused Issue because no canonical observability Issue exists.

### V2-CLOSE-P0-003 — Security event alerting and anomaly response
- **Why it matters:** high-value family/location/destructive operations need actionable abnormal-access signals before public launch.
- **Current evidence:** Family access audit exists, but no alerting subsystem was found.
- **Acceptance criteria:**
  - define alertable security events and severity;
  - cover auth abuse, repeated sensitive-read denials, abnormal Family access, destructive-operation failures and storage capability abuse;
  - alerts contain correlation IDs but not sensitive content;
  - delivery/retry/runbook is documented and tested.
- **Dependency:** canonical `SEC-015`; production observability foundation.
- **Recommended phase:** Public Launch Gate.
- **GitHub follow-up:** no duplicate Issue; track under SEC-015 plus V2-CLOSE-P0-002 infrastructure.

## P1 — required before broad beta / paid rollout

### V2-CLOSE-P1-001 — Mini Program advanced V2 productization
- **Why it matters:** V2-005..011 backend value is not reachable from the Mini Program.
- **Current evidence:** Mini V2-A..D are complete; code search finds no LifeEvent/LifeStage/reasoning/known-duration/life-history/memoir services or pages.
- **Acceptance criteria:**
  - LifeEvent CRUD + Memory evidence linking;
  - LifeStage CRUD + Event linking;
  - Person Known Duration no-guess rendering;
  - stage reasoning with typed failure/citation UX;
  - cross-year explicit timeline with cursor pagination;
  - Annual Memoir narrative/timeline/photo continuation;
  - Life Memoir stage index + on-demand cited chapter;
  - preserve owner/session epoch guards and fail-closed response validation;
  - Mini CI exact-head green.
- **Dependency:** V2-005..011 merged APIs; SEC-013 for inference labeling.
- **Recommended phase:** Broad Beta.
- **GitHub follow-up:** create one coherent client deliverable Issue.

### V2-CLOSE-P1-002 — Flutter V2 Personal Memory Graph productization
- **Why it matters:** Flutter currently exposes no V2-001..011 user flow, causing major cross-platform capability divergence.
- **Current evidence:** `mobile/lib` has Stage1/2 capture/location/reminder/privacy/account-delete surfaces; no `/people`, `/graph`, LifeEvent/LifeStage, known-duration, life-history or memoir API usage was found.
- **Acceptance criteria:**
  - People, PersonMemory, PersonRelationship and Unified Graph usable flows;
  - LifeEvent/LifeStage explicit management;
  - V2-007..011 read/generation surfaces with typed statuses and citations;
  - preserve offline/native-location lifecycle and account-delete quiesce semantics;
  - mobile-ci + mobile-visual-preview exact-head green.
- **Dependency:** V2-001..011; SEC-013/014 UX standards.
- **Recommended phase:** Broad Beta.
- **GitHub follow-up:** create one coherent Flutter productization Issue.

### V2-CLOSE-P1-003 — Consistent AI inference labeling
- **Why it matters:** trusted evidence, explicit records and model inference must be distinguishable to users.
- **Current evidence:** backend trust classes/provenance exist, but a cross-client user-visible inference label is not complete.
- **Acceptance criteria:** define and render consistent explicit/inferred/uncertain states anywhere inference is shown; never label authoritative user records as AI-derived.
- **Dependency:** canonical `SEC-013`.
- **Recommended phase:** Broad Beta.
- **GitHub follow-up:** no duplicate; SEC-013 remains canonical.

### V2-CLOSE-P1-004 — Sensitive-operation second-confirm standard
- **Why it matters:** destructive/privacy-sensitive actions should have a consistent confirmation contract.
- **Current evidence:** some flows confirm intent, but export/delete/family/location-sensitive actions do not share one reviewed product standard.
- **Acceptance criteria:** inventory sensitive actions, define confirmation strength, add cancellation/retry semantics and client tests.
- **Dependency:** canonical `SEC-014`.
- **Recommended phase:** Broad Beta.
- **GitHub follow-up:** no duplicate; SEC-014 remains canonical.

### V2-CLOSE-P1-005 — Entitlement and quota foundation
- **Why it matters:** paid plans cannot be enforced from UI copy alone.
- **Current evidence:** V2/Family/Memoir capabilities exist, but no plan entitlement evaluation, storage quota, AI quota or paid feature gate exists.
- **Acceptance criteria:**
  - server-owned entitlement resolver;
  - free/personal/family/high-tier capability mapping;
  - storage and AI usage accounting;
  - fail-closed quota enforcement and typed client errors;
  - no client-authoritative plan state.
- **Dependency:** canonical `BIZ-001`..`BIZ-004`.
- **Recommended phase:** Paid Rollout.
- **GitHub follow-up:** no duplicate; BIZ IDs remain canonical.

### V2-CLOSE-P1-006 — Product analytics for retrieval and retention
- **Why it matters:** north-star retrieval success and retention cannot be measured from backend correctness tests.
- **Current evidence:** BIZ-010 False Memory Rate has a backend foundation; BIZ-007/008/009 have no analytics pipeline.
- **Acceptance criteria:**
  - privacy-reviewed event schema;
  - successful-memory-retrieval metric;
  - Memory Retrieval Success denominator/numerator;
  - D1/D7/D30 cohort calculation;
  - dashboards exclude Memory content and sensitive coordinates.
- **Dependency:** canonical `BIZ-007`, `BIZ-008`, `BIZ-009`; observability/analytics plumbing.
- **Recommended phase:** Broad Beta / Paid Rollout.
- **GitHub follow-up:** no duplicate; BIZ IDs remain canonical.

## P2 — important product completeness / UX / operations

### V2-CLOSE-P2-001 — Advanced list/search UX over bounded APIs
- **Why it matters:** server reads are bounded, but large accounts need ergonomic filtering/paging.
- **Current evidence:** V2-009/010/011 use keyset cursors; some CRUD list surfaces are bounded but basic.
- **Acceptance criteria:** define product paging/search UX without weakening server bounds; test empty/loading/conflict states.
- **Dependency:** Mini/Flutter productization.
- **Recommended phase:** Product Completeness.

### V2-CLOSE-P2-002 — Annual/Life Memoir presentation polish
- **Why it matters:** memoir APIs exist but the premium value depends on citation visibility, photo continuation and readable chapter navigation.
- **Current evidence:** backend Annual Memoir and Life Memoir are complete; no client surface exists.
- **Acceptance criteria:** citation affordances, photo loading states, chapter navigation, partial/empty state UX and accessibility.
- **Dependency:** V2-CLOSE-P1-001/002; canonical `BIZ-005`.
- **Recommended phase:** Product Completeness / Paid UX.

### V2-CLOSE-P2-003 — Operations dashboard/runbook consolidation
- **Why it matters:** deletion, storage, Family audit and AI provider states are currently observable through separate code/data paths.
- **Current evidence:** durable state exists, unified operator view does not.
- **Acceptance criteria:** documented operator queries/runbooks and optional dashboard after P0 observability data exists.
- **Dependency:** V2-CLOSE-P0-002.
- **Recommended phase:** Operations Hardening.

## Deferred — explicitly not required for V2 closeout

### Deferred-001 — Physical annual memoir
- Canonical reference: `BIZ-006` / `V3-006`.
- Remains deferred until digital memoir product value and paid demand are validated.

### Deferred-002 — V3-001+ AI life-assistant roadmap
- No V3 feature is started by closeout.
- Start only after an explicit post-closeout sequencing decision.

### Deferred-003 — PDF/EPUB/export/share/background memoir jobs
- Not required for V2 foundation or closeout.
- Any future implementation requires separate privacy/storage/entitlement review.
