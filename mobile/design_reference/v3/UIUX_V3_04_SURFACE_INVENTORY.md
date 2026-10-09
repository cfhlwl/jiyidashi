# UIUX-V3-04 Consumer Surface Inventory

Status: first-round audit only
Branch: `codex/uiux-v3-04-consumer-full-refactor`
Base: `bceacead10902bd7297aca335769b6351bb8eb2d` (`origin/main`)
Scope: Consumer UI V3 refactor planning; no production implementation in this round.

## Authority and safety rules

- `mobile/design_reference/v3/*.png` and the Auth V3 design-reference files are immutable Design Authority inputs. This inventory does not edit, crop, resize, regenerate, or replace them.
- A surface is not marked `V3_ACCEPTED` merely because a screenshot exists. Acceptance requires a current production route/widget, truthful data authority, and a reviewed candidate or existing approval.
- Existing committed Goldens are regression evidence, not permission to redesign a surface or to bulk-update baselines.
- Map tile interiors remain third-party rendering; parity review must focus on map container geometry, labels, markers, privacy gates, and truthful data.
- UI work must preserve session fencing, evidence provenance, no-guess behavior, privacy/recording authority, and the existing real-data boundary.
- This file is the first-round deliverable. It intentionally does not claim that unreviewed Legacy or Partial surfaces are complete.

## Status taxonomy

| Status | Meaning |
| --- | --- |
| `V3_ACCEPTED` | Current production surface has passed the applicable V3 visual/functional review and is locked except for approved defect fixes. |
| `V3_PARTIAL` | Production behavior or parts of the visual contract exist, but the full V3 surface is not yet accepted. |
| `LEGACY` | Existing V1/V2 presentation remains the dominant production composition and requires a V3 migration decision. |
| `NEEDS_REFACTOR` | The surface has an authority target and/or functional contract, but current ownership/composition cannot reliably satisfy it without structural work. |
| `DEFERRED` | Explicitly out of the current implementation batch; no visual claim is made. |
| `FUNCTIONAL_ONLY` | Functional authority exists and is tested, but there is no dedicated current V3 visual acceptance evidence. |

## A. Complete surface inventory

| Surface | Status | Route / widget | Owner file and symbol | Existing Golden | Design Authority | Production data authority | Planned action | Existing evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| App shell | `V3_PARTIAL` | `JiYiApp` → `AppShell` | `mobile/lib/stage1_app.dart` — `JiYiApp`, `AppShell` | `design_authority_summary.png` and route candidates | Cross-surface V3 board; no single shell PNG | Session restore, `AuthRestoreStatus`, `JiYiApiClient` | Establish one shell contract, route registry, safe-area policy, and state ownership before page refactors | `widget_test.dart`, responsive/product-experience tests |
| Bottom navigation | `V3_ACCEPTED` for current Today/Memory shell contract | `AppShell.bottomNavigationBar` | `mobile/lib/stage1_app.dart` — `_JiYiBottomNavigation` | `design_authority_today.png`, `memory_v3_*` candidates | `01_today.png`, `02_memory.png` and shell evidence | AppShell selected index; no fabricated data | Keep five destinations and active-state semantics; extract only if behavior remains identical | Today/Memory visual fixtures |
| Top bars and transitions | `V3_PARTIAL` | `Navigator.push(MaterialPageRoute)` detail routes | `mobile/lib/stage1_app.dart`, page files | Route-specific goldens | Per-page PNG where present | Page API/session authority | Define shared back/top-bar/transition primitives without changing route authority | Page tests and visual candidates |
| Today | `V3_ACCEPTED` | `TodayPage` | `mobile/lib/today_footprint_page.dart` — `TodayPage` | Today V3 fixture/golden | `01_today.png` | `getTodayFootprint`, real AMap, real visits/place/coordinates | Locked; only regressions and approved accessibility fixes | Today B3/B4/B5 reviews, targeted tests |
| Memory query / Memory home | `V3_ACCEPTED` for reviewed V3 states | `MemoryQueryPage` | `mobile/lib/stage1_app.dart` — `MemoryQueryPage` | `design_authority_memory_query.png`, Memory V3 candidates | `02_memory.png` | `queryMemory`, query truth/evidence state, session fencing | Preserve truthful empty/loading/error/evidence semantics; refactor composition only after inventory | `memory_v3_visual_test.dart`, query tests |
| Memory evidence disclosure | `V3_ACCEPTED` as a contract, visual surface is `V3_PARTIAL` | `MemoryQueryPage` disclosure | `mobile/lib/stage1_app.dart` — `memory-query-evidence-disclosure` | Product Experience candidates | Derived from `02_memory.png`; no separate PNG | Evidence returned by `queryMemory`; no fabricated source | Keep key, expansion semantics, source/provenance, and no-guess gating while unifying card shell | Query/evidence tests, visual candidate |
| Timeline | `V3_PARTIAL` | `TimelinePage` | `mobile/lib/stage1_app.dart` — `TimelinePage` | `design_authority_timeline.png` | `06_timeline.png` | `getTimelineEvents` in `mobile/lib/api_client.dart`; trusted timeline models | Refactor page hierarchy and event cards against the authority; preserve date/order/trust parsing | Timeline visual/functional tests |
| Memory detail | `V3_PARTIAL` | `MemoryDetailPage` | `mobile/lib/memory_detail_page.dart` — `MemoryDetailPage` | `design_authority_memory_detail.png` | `07_memory_detail.png` | `getMemory`, update/delete, media evidence, session fencing | Refactor layout and states; preserve edit/delete/reminder semantics and media truth | `memory_detail_map_test.dart`, visual golden |
| Place detail | `V3_PARTIAL` | `PlaceDetailPage` | `mobile/lib/place_detail_page.dart` — `PlaceDetailPage` | `place_detail_loaded.png` | No dedicated V3 PNG; derived map/place contract only | `getPlaceDetail`, real coordinates and place data | Align detail shell and privacy/map states; explicitly review as derived, not a claimed Design Authority match | `place_detail_test.dart`, existing golden |
| Footprint detail | `FUNCTIONAL_ONLY` | `FootprintDetailPage` | `mobile/lib/footprint_detail_page.dart` — `FootprintDetailPage` | No dedicated V3 Golden | No dedicated V3 PNG | Footprint/visit data and real map authority | Decide whether to absorb into Timeline/Place Detail batch; do not invent visual acceptance | `footprint_detail_page_test.dart` |
| Capture entry | `V3_PARTIAL` | `CapturePage` | `mobile/lib/stage1_app.dart` — `CapturePage` | `design_authority_capture.png`, `capture_object.png` | `08_capture.png` | `UnifiedMediaCaptureSection`, `CaptureMediaDevice`, trusted capture service | Refactor entry/action hierarchy while preserving upload, offline capture, and media provenance | `unified_capture_section_test.dart`, capture visual tests |
| Unified capture section | `V3_PARTIAL` | Reusable capture section | `mobile/lib/unified_capture_section.dart` — `UnifiedMediaCaptureSection` | Capture candidates | `08_capture.png` | Trusted media/capture services | Extract stable capture actions and states; no backend/media authority redesign | `unified_capture_section_test.dart`, `offline_capture_test.dart` |
| Life home | `LEGACY` | `LifePage` | `mobile/lib/v2/life_page.dart` — `LifePage` | `life_home.png` | `03_life.png` | V2 life API/models | Replace composition in a dedicated Life batch after shared primitives are stable | `product_experience_responsive_test.dart`, life tests |
| Life experience / event detail | `LEGACY` | `LifeEventDetailPage` | `mobile/lib/v2/life_event_detail_page.dart` — `LifeEventDetailPage` | `v2_life_event_detail.png` | `10_life_experience.png` and `03_life.png` | V2 life event data, strict parsers | Migrate visual hierarchy without weakening event/evidence truth | V2 widget/functional tests |
| Year review / summary | `LEGACY` | `MemoirsPage`, summary route | `mobile/lib/v2/memoirs_page.dart` — `MemoirsPage` | `v2_life_memoir_chapter.png`, `design_authority_summary.png` | `09_year_review.png` | V2 memoir/year data | Treat as later Year Review batch; preserve chapter/order semantics | V2 widget tests, summary visual |
| Life history | `LEGACY` | `LifeHistoryPage` | `mobile/lib/v2/life_history_page.dart` — `LifeHistoryPage` | No complete V3 candidate | `09_year_review.png`, `10_life_experience.png` as applicable | `V2Api.getLifeHistory`, strict V2 models | Life/Year Review batch; keep chronology and reasoning provenance explicit | V2 functional/model tests |
| Life stages | `LEGACY` | `LifeStagesPage` | `mobile/lib/v2/life_stages_page.dart` — `LifeStagesPage` | No complete V3 candidate | `09_year_review.png`, `10_life_experience.png` as applicable | V2 life stage list API/models | Life batch: migrate stage navigation and empty/loading/error states | V2 functional tests |
| Life stage detail | `LEGACY` | `LifeStageDetailPage` | `mobile/lib/v2/life_stage_detail_page.dart` — `LifeStageDetailPage` | `v2_reasoning_answered.png` where applicable; no complete V3 candidate | `09_year_review.png` / `10_life_experience.png`; no dedicated detail PNG | Linked events, long-term reasoning, and stage mutation authority | Life batch: preserve linked-event identity, reasoning truth, and mutations; do not collapse into generic history | `v2_widget_test.dart`, reasoning tests |
| People list | `LEGACY` | `PeoplePage` | `mobile/lib/v2/people_page.dart` — `PeoplePage` | `people.png` | `11_people.png` | V2 people API and trusted person models | Migrate after shared cards and identity semantics are locked | `v2_widget_test.dart`, `people.png` |
| Person detail | `LEGACY` | `PersonDetailPage` | `mobile/lib/v2/person_detail_page.dart` — `PersonDetailPage` | `v2_person_detail.png` | `12_person_detail.png` | V2 person/family data | Refactor as People/Family detail batch; preserve permissions and identity authority | V2 widget tests |
| Family home | `V3_PARTIAL` | `FamilyPage` | `mobile/lib/v2/family_page.dart` — `FamilyPage` | `design_authority_family.png` | `04_family.png` | `FamilyApi`, family models, shared content authority | Audit shell and member cards; then migrate with permissions preserved | `family_v2_test.dart`, shared-content tests |
| Family member permissions | `NEEDS_REFACTOR` | Family permission surface | `mobile/lib/v2/family_page.dart`, `family_models.dart` | No dedicated committed V3 Golden | `13_family_member_permissions.png` | Family membership/permission API | Define explicit permission-state components and acceptance evidence before visual work | `family_shared_content_test.dart` |
| Profile | `V3_PARTIAL` | `ProfilePage` | `mobile/lib/stage1_app.dart` — `ProfilePage` | `design_authority_profile.png`, privacy goldens | `05_profile.png` | `getProfile`, privacy status, recording health | Refactor profile sections using shared state/action primitives; preserve privacy and health authority | profile/privacy/recording tests |
| Recording health | `FUNCTIONAL_ONLY` | Profile recording section | `mobile/lib/recording_health_section.dart` — recording health surface | No dedicated accepted V3 candidate | `14_recording_privacy.png` as related authority | `getRecordingHealth`, native location/recording status | Keep functional semantics; produce a dedicated candidate only in Recording & Privacy batch | `recording_health_surface_test.dart`, native location tests |
| Recording & privacy | `FUNCTIONAL_ONLY` | Profile privacy controls | `mobile/lib/stage1_app.dart` — `_AmapPrivacyControls` and related controls | `profile_privacy_error.png`, `profile_privacy_paused.png` | `14_recording_privacy.png` | `getPrivacyStatus`, AMap privacy gate, native location policy | Refactor presentation only after privacy states and acceptance matrix are documented | privacy/native tests |
| Auth | `V3_ACCEPTED` for current email-only production | `AuthPage` | `mobile/lib/stage1_app.dart` — `AuthPage`; `mobile/lib/auth_v3.dart` — `AuthCapabilities` | `auth_login.png`, `auth_v3_email_login.png` | Auth V3 authority/spec | Email-only current capability; phone/SMS/WeChat remain future | Locked for this UI V3 thread; no AUTH-02/03/04 work | Auth visual/functional tests |
| Loading, empty, error, offline | `V3_PARTIAL` | Shared state widgets | `mobile/lib/ui/jiyi_components.dart` — `JiYiLoadingState`, `JiYiEmptyState`, `JiYiErrorState`, `JiYiOfflineState` | `state_loading.png`, `state_empty.png`, `state_offline.png`, `state_map_unavailable.png` | Derived per page; no single state PNG authority | API/network/privacy/error truth from owning feature | Unify copy, spacing, semantics, and retry behavior without hiding uncertainty | state and responsive tests |
| Shared evidence | `V3_PARTIAL` | Evidence cards/disclosures | `mobile/lib/ui/jiyi_components.dart` — `JiYiEvidenceCard` | Evidence candidates | Derived from Memory/Timeline authorities | Canonical evidence/provenance from APIs | Keep source identity and certainty semantics; extract only presentation | evidence tests |
| Onboarding | `FUNCTIONAL_ONLY` | Onboarding flow | `mobile/lib/onboarding_flow.dart` and `stage1_app.dart` | No dedicated current V3 authority | No dedicated V3 PNG found | Session/profile setup and onboarding authority | Preserve flow; perform separate visual inventory before refactor | onboarding tests |

### Additional production user-visible surfaces

The following rows are separate because they are independently reachable, interactive, or high-risk. They must not be hidden inside a parent page row during later V3 planning.

| Surface | Status | Route / widget | Owner file and symbol | Existing Golden | Design Authority | Production data authority | Planned action | Existing evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Life events | `LEGACY` | `LifeEventsPage` | `mobile/lib/v2/life_events_page.dart` — `LifeEventsPage` | No dedicated V3 Golden | `03_life.png` / `10_life_experience.png`; no dedicated list authority | V2 life event list, create/edit, and place-binding APIs | Life batch: migrate list, create/edit entry, place binding, and mutation states separately from event detail | Life functional tests and V2 API tests |
| Life event editor dialog | `LEGACY` | Modal from `LifeEventsPage` | `mobile/lib/v2/life_editors.dart` — `LifeEventEditorDialog` | No dedicated V3 Golden | No dedicated dialog PNG; derived from `03_life.png` / `10_life_experience.png` | V2 life event mutation authority and place binding | Life batch: preserve validation, mutation, cancel, and failure semantics while replacing V2 presentation | Life editor tests |
| Life stage editor dialog | `LEGACY` | Modal from `LifeStagesPage` / detail | `mobile/lib/v2/life_editors.dart` — `LifeStageEditorDialog` | No dedicated V3 Golden | No dedicated dialog PNG | V2 life stage mutation authority | Life batch: migrate form and destructive/error states after stage detail contract is accepted | Life editor tests |
| V2 home hub | `LEGACY` | Timeline → “重要的人和人生故事” → `V2HomePage` | `mobile/lib/v2/v2_home_page.dart` — `V2HomePage` | No dedicated V3 Golden | No dedicated V3 PNG; hub composition derived from People/Life authorities | V2 People + Life APIs/models | Navigation/Life-People decision: retain hub, absorb into V3 navigation, or explicitly defer; do not leave as an orphan route | V2 home and navigation tests |
| Graph neighborhood | `LEGACY` | `GraphNeighborhoodPage` | `mobile/lib/v2/graph_page.dart` — `GraphNeighborhoodPage` | Existing V2 graph-neighborhood Golden/test evidence | No dedicated V3 PNG; derived from `11_people.png` / `12_person_detail.png` relationship authority | `V2Api.graphNeighborhood`, `V2Authority` | People/Life relationship batch; preserve graph trust, identity, and neighborhood scope | `v2_widget_test.dart`, graph neighborhood visual evidence |
| Person creation dialog | `LEGACY` | Modal from `PeoplePage` | `mobile/lib/v2/people_page.dart` — `_PersonDialog` | No dedicated V3 Golden | No dedicated dialog PNG; derived from `11_people.png` | V2 person create/update authority | People/Family batch: preserve identity validation, cancel, and mutation failure states | V2 people tests |
| Person edit dialog | `LEGACY` | Modal from `PersonDetailPage` | `mobile/lib/v2/person_detail_page.dart` — `_PersonEditDialog` | No dedicated V3 Golden | No dedicated dialog PNG; derived from `12_person_detail.png` | V2 person mutation authority | People/Family batch: preserve owner/identity binding and destructive hierarchy | Person detail tests |
| Memory link dialog | `LEGACY` | Modal from `PersonDetailPage` | `mobile/lib/v2/person_detail_page.dart` — `_MemoryLinkDialog` | No dedicated V3 Golden | No dedicated dialog PNG | V2 person-memory relationship authority | People/Family batch: preserve canonical memory identity and link/unlink semantics | Person detail tests |
| Relationship dialog | `LEGACY` | Modal from `PersonDetailPage` | `mobile/lib/v2/person_detail_page.dart` — `_RelationshipDialog` | No dedicated V3 Golden | No dedicated dialog PNG | V2 relationship mutation authority | People/Family batch: preserve relationship scope, validation, and failure states | Person detail tests |
| Family member shared page | `LEGACY` | Family member shared-content detail | `mobile/lib/v2/family_page.dart` — `_FamilyMemberSharedPage` | No dedicated V3 Golden | Derived from `04_family.png` / `13_family_member_permissions.png` | Family shared-content and membership authority | Family batch: preserve member scope, visibility, and owner/session fencing | `family_shared_content_test.dart` |
| Native location section | `FUNCTIONAL_ONLY` | Profile/location settings section | `mobile/lib/native_location_section.dart` — `NativeLocationSection` | No dedicated V3 Golden | Related to `14_recording_privacy.png`; no dedicated section PNG | Native location status, privacy gate, and sensitive-operation authority | Profile/Privacy batch; preserve automatic-location confirmation, fail-closed state, and platform policy | Native location and privacy tests |
| Account deletion | `FUNCTIONAL_ONLY` | Profile high-risk section | `mobile/lib/account_delete_section.dart` — `AccountDeleteSection` | No dedicated V3 Golden | Related to `05_profile.png`; no dedicated deletion PNG | Authenticated account/session binding, irreversible delete authority, local owner-scoped cleanup/fencing | Profile/Privacy/Settings batch; preserve confirmation phrase, irreversible warning, in-progress state, and retry/resume semantics | `account_delete_test.dart` |
| Sensitive operation confirmation | `FUNCTIONAL_ONLY` | Shared destructive/sensitive modal | `mobile/lib/sensitive_operation_confirmation.dart` — `showSensitiveOperationConfirmation`, `_SensitiveOperationDialog` | No dedicated V3 Golden | No dedicated modal PNG; derived per owning surface | Data export/delete, account delete, automatic location start, family permission/remove/leave, and reachable emergency/sensitive-location operations | Profile/Privacy/Settings batch; preserve destructive hierarchy, required phrase, scope, undo semantics, and fail-closed authority | `sensitive_operation_confirmation_test.dart`, family/native/account tests |
| Reminder management | `FUNCTIONAL_ONLY` | `AppShell` notification destination `reminder` → `ReminderPage` | `mobile/lib/reminder_page.dart` — `ReminderPage` | No dedicated V3 Golden | No dedicated V3 PNG | Existing reminder API/client contract | Profile/utility batch; establish a reviewed reminder visual contract without claiming V3 acceptance | `reminder_test.dart`, AppShell route wiring |
| Reminder creation dialog | `FUNCTIONAL_ONLY` | Modal from `ReminderPage` | `mobile/lib/reminder_page.dart` — `_ReminderCreateDialog` | No dedicated V3 Golden | No dedicated V3 PNG | Existing reminder create/update contract | Profile/utility batch; preserve schedule, validation, cancel, and retry behavior | `reminder_test.dart` |
| Memory edit dialog | `FUNCTIONAL_ONLY` | Memory Detail edit modal | `mobile/lib/stage1_app.dart` — `_MemoryEditDialog` | No dedicated Golden | Derived from `07_memory_detail.png`; no dedicated modal authority | `updateMemory`, owner/session fencing | Memory Detail batch; preserve validation, cancel/save semantics, and owner binding | Memory detail and edit interaction tests |

### Inventory interpretation

The statuses above are implementation planning statuses, not a promise that every listed surface is in the first code batch. In particular, `03_life.png`, `04_family.png`, `06_timeline.png`, `07_memory_detail.png`, `08_capture.png`, `09_year_review.png`, `10_life_experience.png`, `11_people.png`, `12_person_detail.png`, `13_family_member_permissions.png`, and `14_recording_privacy.png` are authority inputs that still require route-level production candidate review unless the row explicitly cites an accepted review.

The completeness pass covered production Dart under `mobile/lib/*.dart` and `mobile/lib/v2/*.dart`, including page classes, routed hubs, independently reachable dialogs, sheets/sections, destructive-operation confirmation, privacy/location controls, and nested detail surfaces. Pure models, API clients, parsers, and helper widgets were not promoted to standalone surface rows unless they own visible interaction or state. Every such promoted surface has an explicit status, route/widget, owner symbol, evidence/authority statement, data authority, planned action, and batch above.

## B. V3 tokens and components audit

### Token inventory

| Area | Current source | Decision | Reason / next action |
| --- | --- | --- | --- |
| Spacing | `mobile/lib/ui/jiyi_tokens.dart` — `JiYiSpacing` | `KEEP` | The 4–48 scale is already shared. Add semantic aliases only when a measured authority requires one; do not create page-local spacing constants. |
| Today geometry | `JiYiTodayGeometry` | `KEEP / LOCKED` | Today is accepted. Treat its 390×844 values as page-specific authority, not a global layout scale. |
| Radius | `JiYiRadius` | `KEEP` | Use shared control/card/sheet/pill roles; avoid per-page radius drift. |
| Product colors | `JiYiProductColors` | `KEEP, audit roles` | Existing semantic palette is the base for non-Today surfaces. Map new component roles to it rather than adding another palette. |
| Today colors | `JiYiTodayVisuals` | `KEEP, scope carefully` | Today remains locked. Its card/background/nav roles may be documented as semantic equivalents, but must not be globally recolored as part of another page refactor. |
| Typography | `jiyi_theme.dart`, Material text theme, page-local styles | `RESTRUCTURE` | Define shared V3 text roles with explicit locale, max-lines, and large-text behavior; do not flatten hierarchy to make screenshots fit. |
| Elevation/shadows | `jiyi_theme.dart`, component-local shadows | `RESTRUCTURE` | Consolidate surface depth roles and keep shadows subtle; preserve approved Today values. |
| Icon/tap targets | `JiYiIconSizes`, `JiYiTapTargets` | `KEEP` | Enforce 48/56 minimum interactive targets and semantic labels across new components. |
| Motion | `JiYiMotion` | `KEEP` | Reuse existing durations/easing. No animation should gate truthful state visibility or test determinism. |
| Semantic colors | `JiYiSemanticColors` | `KEEP` | Use for success/warning/info, with text semantics and contrast checks. |

### Existing component disposition

| Existing symbol | File | Disposition | V3-04 use |
| --- | --- | --- | --- |
| `JiYiPageFrame` | `mobile/lib/ui/jiyi_components.dart` | `KEEP / EXTEND CAREFULLY` | Base page padding/background/safe-area contract. |
| `JiYiSectionCard` | same | `KEEP` | Shared near-white/elevated surface; add no page-specific behavior. |
| `JiYiStatusBanner` | same | `REUSE LOGIC ONLY` | Preserve semantic state and action authority; unify visual wrapper later. |
| `JiYiEmptyState` | same | `KEEP / RESTRUCTURE VISUAL` | One truthful empty-state contract with page-specific copy supplied by owner. |
| `JiYiLoadingState` | same | `KEEP` | Shared loading semantics; no full-page loading for local image/API transitions unless the owning contract requires it. |
| `JiYiErrorState` | same | `KEEP / RESTRUCTURE VISUAL` | Preserve retry/error authority and accessible announcement. |
| `JiYiOfflineState` | same | `KEEP` | Preserve offline truth and retry affordance. |
| `JiYiEvidenceCard` | same | `REUSE LOGIC ONLY` | Canonical provenance and certainty remain unchanged; presentation can be aligned to V3 surfaces. |
| `JiYiSectionHeader` | same | `KEEP` | Shared section title/action alignment. |
| `JiYiActionCard` | same | `KEEP / AUDIT` | Use for capture, settings, and action rows where semantics match. |
| `V2TrustBadge`, `V2ErrorState`, `V2OfflineErrorState`, `V2KeyValue`, `V2TileSurface`, `V2SectionCard` | `mobile/lib/v2/v2_widgets.dart` | `REUSE LOGIC ONLY` | Preserve strict parsing/trust behavior; do not copy V2 visual structure into new V3 pages. |
| `_JiYiBottomNavigation` | `mobile/lib/stage1_app.dart` | `KEEP BEHAVIOR / RESTRUCTURE LATER` | It is the current navigation authority. Extraction must not change destinations, active state, or session gating. |

### Proposed shared V3 component vocabulary

These are planning names, not yet-created symbols:

- `V3PageScaffold`: safe-area, background, scroll boundary, title/back affordance, and state-hosting contract.
- `V3TopBar`: consistent title, back, action, and semantic navigation behavior.
- `V3SurfaceCard`: near-white surface, radius, subtle depth, and responsive padding.
- `V3SectionHeader`: section title, optional count/action, and predictable spacing.
- `V3MediaCard`: memory/photo/media treatment with truthful loading/error/offline states.
- `V3EvidenceDisclosure`: keyed expansion and provenance/certainty semantics shared by Memory, Timeline, and Life.
- `V3TimelineEventCard`: date/event/place layout built on trusted timeline models.
- `V3PersonCard` and `V3PermissionRow`: identity and member-permission presentation without changing authority.
- `V3CaptureActionGrid`: capture entry actions with shared tap targets and offline/error handling.
- `V3StateSurface`: loading/empty/error/offline/blocked variants with explicit semantic state.

No component should create data, infer missing evidence, bypass session fencing, or own backend/provider behavior.

## C. Shared component plan

1. Freeze and document the current token roles; do not add a second global token file.
2. Extract visual primitives only after comparing `JiYiPageFrame`, `JiYiSectionCard`, `JiYiSectionHeader`, and the current bottom navigation against accepted Today/Memory evidence.
3. Introduce `V3PageScaffold` and `V3SurfaceCard` behind one page at a time, retaining existing keys and semantic labels where tests or accessibility depend on them.
4. Use `V3EvidenceDisclosure` for Memory Query, Timeline, and Life only after confirming each owner’s evidence payload and expansion contract.
5. Migrate one route per batch; each batch must include responsive, large-text, empty/loading/error, truthful-data, and route-back checks.
6. Delete duplicate visual wrappers only after all consumers are migrated and their authority tests are updated to the current contract. Never delete strict data/trust helpers as visual cleanup.

## D. Navigation audit

### Current production contract

`AppShell` in `mobile/lib/stage1_app.dart` currently owns the five-tab mapping:

| Index | Label | Current page |
| ---: | --- | --- |
| 0 | 今天 | `TodayPage` |
| 1 | 记忆 | `MemoryQueryPage` |
| 2 | 人生 | `LifePage` |
| 3 | 家庭 | `FamilyPage` |
| 4 | 我的 | `ProfilePage` |

`_JiYiBottomNavigation` is the current selected-state and tap authority. The shell hides it for onboarding/account-deletion states. Today has a special shell/safe-area treatment; other pages use the existing `SafeArea` behavior. Detail pages currently use direct `Navigator.push(MaterialPageRoute(...))`.

### Risks to address without changing authority

- Index-based page selection makes destination ownership and deep-link behavior implicit.
- Direct `MaterialPageRoute` construction duplicates transition/top-bar behavior.
- Shell and page-level safe-area decisions can drift, especially around the bottom navigation and home indicator.
- Some legacy V2 pages are mounted through the current shell while their visual contracts remain unreviewed.
- A future route registry must not bypass session restore, account deletion, privacy gates, or evidence/session fencing.

### Proposed sequence

1. Record the existing index/label/page mapping as a compatibility contract.
2. Introduce typed destination metadata and a route factory without changing the five visible destinations.
3. Centralize detail-route transitions and back semantics while keeping each page’s current data authority.
4. Add explicit shell state for session/onboarding/account deletion and preserve current hidden-navigation rules.
5. Add deep-link/restoration tests only after the compatibility route map passes existing tests.
6. Extract bottom navigation visually only after Today and Memory shell evidence remains unchanged.

## E. Responsive, accessibility, and truthful-data audit

### Responsive behavior

- `390×844` remains the primary visual review viewport for existing authorities; it is not permission to hard-code every new surface to one size.
- Small screens must scroll or reflow; they must not clip text, hide actions, or move evidence out of reach.
- Large text must preserve content hierarchy and action reachability. Do not solve overflow by reducing type below the semantic role or by truncating evidence.
- Flexible dimensions: outer card width, list height, text wrapping, image crop inside an explicitly reviewed box, and inter-section whitespace within the documented tolerance.
- Stable dimensions/relationships: touch target minimums, navigation destination order, key surface hierarchy, evidence disclosure identity, and any page-specific locked geometry.

### Accessibility

- Every interactive control requires a useful label or visible text; icon-only controls need semantic labels.
- Preserve stable keys used as production contracts, including `memory-query-evidence-disclosure` and `auth-v3-register-entry` where applicable.
- Verify focus/order, contrast, dynamic text, semantics, and 48/56dp tap targets on every refactored route.
- Loading, blocked, offline, empty, and error states must be distinguishable to assistive technology, not only by color.

### Truthful data

- UI may render only data supplied by the owning API/model or an explicitly documented empty/error state.
- Never fabricate visits, routes, coordinates, memories, people, permissions, recording health, weather, steps, or activity.
- Evidence must retain canonical identity, source/provenance, certainty semantics, owner/session fencing, and fail-closed behavior.
- Real AMap and privacy/accept gates remain production authorities; illustrated maps are not substitutes for production map behavior.
- Provider/auth work is out of scope. Current production Auth acceptance is email-only; Phone/SMS/WeChat fixtures remain future design previews.

## F. Data authority index

| Capability | Current authority |
| --- | --- |
| Profile | `JiYiApiClient.getProfile` |
| Today footprint | `JiYiApiClient.getTodayFootprint` |
| Memory create/read/update/delete | `createTextMemory`, media upload methods, `getMemory`, `updateMemory`, `deleteMemory` |
| Timeline | `JiYiApiClient.getTimelineEvents` and trusted timeline models |
| Place detail | `JiYiApiClient.getPlaceDetail` |
| Recording health | `JiYiApiClient.getRecordingHealth` |
| Privacy | `JiYiApiClient.getPrivacyStatus` plus AMap/native privacy gate |
| Memory query/evidence | `JiYiApiClient.queryMemory` and evidence payload; no-guess gate |
| Reminder management | Existing reminder API/client contract, including create/update/delete scheduling operations |
| Account deletion | Authenticated session/account binding, irreversible delete operation, and owner-scoped local cleanup/fencing |
| Sensitive operations | Owning operation authority plus required confirmation phrase/scope and fail-closed result |
| Family/people/life | Existing `mobile/lib/v2/*_api.dart` and strict V2 models until their V3 migration batch replaces presentation only |
| Graph neighborhood | `V2Api.graphNeighborhood` with `V2Authority` and canonical person/relationship identity |
| Life events/stages | Existing V2 life APIs/models, mutation contracts, linked-event identity, and long-term reasoning authority |
| Session/shell | `AuthRestoreStatus`, `JiYiApiClient.restorePersistedSession`, `JiYiApp` session state |

## G. Implementation batching plan

The first implementation after this inventory must be independently reviewable. No batch may silently include AUTH, backend, provider, native, migration, or Design Authority changes.

| Batch | Scope | Required evidence / exit gate |
| --- | --- | --- |
| 0 | Inventory, token/component audit, navigation contract | This file reviewed; clean scope; no PNG/Golden changes |
| 1 | Shared V3 tokens/components and state surfaces | Token role audit, component tests, responsive/large-text/state checks |
| 2 | Navigation shell, route transitions, and V2 Home hub decision | Five destinations unchanged, selected state/back/session gates pass; `V2HomePage` is retained, absorbed, or explicitly deferred |
| 3 | Timeline + Memory Detail + Memory edit/reminder entry points | `06_timeline.png` / `07_memory_detail.png` candidates, truthful event/memory tests, empty/loading/error states, reminder route ownership documented |
| 4 | Place Detail + People/Person Detail + Graph neighborhood | Derived place evidence plus `11_people.png` / `12_person_detail.png` and graph candidates; identity, relationship, and permission truth preserved |
| 5 | Life home, Life Events, Life Experience, Life History, Life Stages, Stage Detail, Year Review | `03_life.png`, `09_year_review.png`, `10_life_experience.png` candidates; strict reasoning/evidence, event/stage mutation, and linked-record behavior retained |
| 6 | Capture | `08_capture.png` candidate; capture/offline/media provenance tests |
| 7 | Family + member permissions | `04_family.png`, `13_family_member_permissions.png`; shared-content and permission invariants pass |
| 8 | Profile + Reminder management + Account Delete + Sensitive Confirmation + Recording & Privacy | `05_profile.png`, `14_recording_privacy.png`; reminder, irreversible deletion, confirmation, privacy/health/native authority tests pass |
| 9 | State/accessibility/responsive hardening | Small screen, large font, semantics, dynamic-state, and no-overflow evidence |
| 10 | Visual audit and acceptance | Per-surface candidate/overlay/diff package; exact failure classification; no bulk Golden update |

The current round stops at Batch 0. Timeline, Memory Detail, and Place Detail implementation may begin only after this inventory is accepted as the scope baseline.

## H. Review and acceptance checklist

- [ ] Every requested Consumer surface has one inventory row and an explicit status.
- [ ] Every row names a real route/widget, owner file/symbol, data authority, and existing evidence or explicitly says none.
- [ ] No surface is called accepted solely because a Design Authority PNG exists.
- [ ] Shared tokens/components have one owner and no duplicate palette/spacing system is introduced.
- [ ] Five-tab navigation mapping remains compatible until a reviewed migration changes it.
- [ ] Responsive, accessibility, and truthful-data checks are part of every batch.
- [ ] Candidate screenshots are labeled candidate; Design Authority PNGs and committed Goldens remain unchanged unless a later, explicit review authorizes a precise Golden update.
- [ ] Exact-head CI is run after implementation batches, not used to justify unreviewed visual changes.

## First-round change boundary

This inventory is documentation-only. It does not modify production Dart, tests, workflows, `mobile/design_reference/v3/*.png`, committed Golden baselines, backend, native code, provider configuration, or AUTH branches.
