# Memory Visual Parity Specification

本规格只定义 Consumer Memory V3 的 presentation 目标。`02_memory.png` 是本轮唯一视觉权威；它不提供真实 Memory、Photo、Place、Visit、Time 或 AI answer 数据。所有示例内容必须由真实 authority 驱动，缺失时使用诚实的 empty/unavailable 状态。

## Authority

- Visual authority: `mobile/design_reference/v3/02_memory.png`
- Business/data authority: `MemoryQueryPage`、`JiYiApiClient.queryMemory()`、Memory/Evidence/Visit/Place 服务端响应及现有 session/owner fencing。
- Primary viewport: 390 × 844 logical px, portrait, `zh-CN`, text scale 1.0.
- Secondary validation: small phone 320 × 640、large phone 430 × 932、text scale 1.3。
- `02_memory.png` 中的文字、照片、人物头像、日期、地点和答案均为设计示例，不得硬编码为用户数据。

## Reference Dimensions

| Region | Reference px | 390×844 target | Notes |
| --- | ---: | ---: | --- |
| Full screenshot | 853 × 1844 | 390 × 844 | PNG 为完整 iOS-style screenshot，包含 status bar 与 home indicator。 |
| Top system chrome | y≈0–93 | y≈0–43 | 平台拥有；Flutter Golden 不应直接承担这些像素。 |
| Page content / header | x≈36–820, y≈117–296 | x≈16–375, y≈54–136 | 标题、说明和留白组成首屏品牌入口。 |
| Query surface | x≈33, y≈315, w≈787, h≈107 | x≈15, y≈144, w≈360, h≈49 | 大圆角、白色、无工程表单边框。 |
| Suggestion row | x≈34–819, y≈450–524 | x≈16–374, y≈206–240 | 四个轻量胶囊；横向溢出时可滚动，不强行缩小文字。 |
| Recent section | y≈596–1220 | y≈273–559 | 标题、更多入口、两张记忆卡。 |
| Important people | y≈1290–1635 | y≈591–749 | 真实人物 authority 存在时展示；不存在时不伪造头像。 |
| Floating capture action | x≈724, y≈1545, d≈101 | x≈331, y≈708, d≈46 | 只保留真实 Capture 入口，受权限/能力状态约束。 |
| Bottom navigation | y≈1670–1844 | y≈765–844 | 固定；包含 Flutter content 与 system bottom safe area。 |

## Normalization

- Reference aspect ratio: `853 / 1844 ≈ 0.46258`.
- Target aspect ratio: `390 / 844 ≈ 0.46209`.
- Use uniform normalization; do not independently stretch x/y.
- Width-based scale is `390 / 853 ≈ 0.45721`; the corresponding height is approximately `843.1`, leaving a sub-pixel/rounding residual handled by normalized content bounds.
- Height-based scale is `844 / 1844 ≈ 0.45770`; the corresponding width is approximately `390.4`, so a centered crop of the fractional horizontal residual is acceptable for screenshot comparison.
- Implementation uses target logical geometry, not a runtime bitmap stretch. Cards, text, images and system chrome each use their own layout rules.
- The reference contains status bar and home indicator. A Flutter widget Golden is regression authority only. If it lacks system chrome, crop/mask the corresponding reference system regions before overlay/diff. Final parity uses a fixed iOS Simulator or real-device screenshot with real SafeArea/system chrome.

## Page Anatomy

1. Light warm page background.
2. Integrated top brand header: `记忆` and `从你留下的记录里找回来`.
3. Large natural query surface with search affordance.
4. Four suggested query chips.
5. `最近记下的` section with two real memory summaries.
6. `重要的人` section with real people authority, if available.
7. Floating capture action.
8. Fixed five-item bottom navigation with `记忆` active.

The content is a consumer memory home, not an admin dashboard. A query result may be inserted above or below the relevant section while preserving the shell and scroll context.

## Header

- Target left inset: 16–18 px; title ink begins around y=54–60.
- Title: `记忆`, large navy display text, approximately 34–38 px at target, bold/serif-like brand treatment if the approved font is available; otherwise use the existing brand-compatible text style without embedding a screenshot crop.
- Subtitle: `从你留下的记录里找回来`, approximately 18–20 px, muted blue-grey, one line at 390 px where possible.
- No settings/avatar/diagnostic action in the reference header.
- Header content is presentation only; it does not imply that example memories exist.

## Query / Search Surface

- One dominant rounded white surface, target x≈15, y≈144, w≈360, h≈49–52, radius≈18–22.
- Search icon is left-aligned and secondary; placeholder is `想找哪段回忆？` or equivalent approved consumer wording.
- Input must remain a real `TextField` connected to `queryMemory()`; no local fake search.
- Submit through search action/keyboard. Double submit remains blocked by `loading` and query-generation fencing.
- While loading, preserve the entered question and page shell; show only local progress/disabled submit affordance.
- The input must remain reachable and usable at text scale 1.3 and on 320 px width.

## Suggested / Recent Memory Surface

- Suggested chips are secondary shortcuts, not hardcoded query results. Suggested labels may be retained as product prompts, but their result content must come from the query authority.
- Target chip height ≈34–38 px, radius≈18–20 px, horizontal gap≈8 px.
- Use restrained semantic tints: cool blue for place/time, warm peach for family/photo, pale amber for object search.
- The recent section heading is approximately 28–32 px, bold navy; `查看全部` is a secondary navigation affordance.
- If recent-memory authority is not available in the current API, do not manufacture the two reference cards. Preserve the section rhythm with a truthful empty state or omit the section.

## Result State

Result hierarchy:

```text
用户问题
  ↓
迹忆回答
  ↓
必要的时间 / 地点 / 记忆线索
  ↓
查看依据
  ↓
查看、编辑、提醒或删除等进一步操作
```

- `can_answer == true` may show the answer, but only from `answer` and its structured evidence.
- `can_answer == false` must clearly say that there is not enough reliable evidence; never show “已找到” or a guessed answer.
- `certainty`, `intent`, `provenance` and source type remain available as trust disclosure, but should be secondary consumer language rather than a row of engineering badges.
- A late response is discarded when query generation, session version or authenticated owner no longer matches.

## Evidence Presentation

- Evidence remains available through a calm `为什么这样回答` / `查看依据` disclosure surface.
- Do not make evidence the dominant visual card in the first viewport.
- Exclude `AI_INFERENCE` from trusted evidence presentation as the current implementation does.
- `USER_EDIT` must remain visible as user-edited provenance when applicable.
- Missing evidence is represented as a warning/unavailable state; never create a fake evidence card.
- Evidence excerpts, source type and time must remain truthful and owner-scoped.

## Memory Cards

- Reference recent card 1: target x≈15, w≈360, h≈143–155; white surface, radius≈18–20, very light shadow.
- Reference recent card 2: target x≈15, w≈360, h≈95–108; white surface, radius≈18–20.
- Card 1 uses a right-side landscape photo; card 2 uses a left-side photo. This asymmetry is a layout cue, not permission to use the reference images as runtime data.
- Runtime media must come from `LocalMediaCache` and server-approved media authority. Missing media uses a neutral truthful placeholder/text state.
- Use `BoxFit.cover` only for an actual approved runtime image with an independently controlled focal point.
- Card title is primary navy text; metadata is secondary blue-grey; descriptive copy is limited to a readable preview and may expand for accessibility.
- Edit/delete/reminder actions remain reachable from result/detail/secondary action surfaces and are not required to occupy the primary card face.

## Empty State

- Empty recent memories: explain that there are no recorded memories available yet and offer real capture actions.
- Empty result: say that no reliable record was found; do not imply a search failure is a missing photo or map.
- Empty people: omit the people section or show a concise “还没有整理出重要的人” state; never use design-reference portraits as fake users.
- Empty media: retain card geometry only when useful, label the media as unavailable, and do not borrow `02_memory.png` photos.

## Loading State

- Keep header, query surface, suggestions and existing content visible.
- Use local progress in the query affordance and/or result slot; never replace the whole page with a spinner.
- Preserve the submitted question while the query is pending.
- Disable only actions that would violate the current loading/authority state.

## Error State

- Network/API errors use a local non-blocking error surface with retry through the same real authority.
- Protocol or malformed response errors fail closed with “查询结果无法验证，请稍后重试”.
- Map consent/configuration failure does not become a fake map or fake visit.
- Error copy must not expose provider, database, token or internal implementation details.

## Bottom Navigation

- Reuse the existing Today V3 five-item contract: `今天`, `记忆`, `人生`, `家庭`, `我的`.
- `记忆` is active with the same blue active treatment, icon scale, label spacing and indicator contract as Today V3.
- Bottom navigation is fixed; body scrolls behind/up to its boundary and must not add duplicate bottom SafeArea padding.
- Home indicator belongs to system chrome. Flutter Golden comparisons must mask/crop it when absent.

## Scroll Model

- Header, query surface and sections are in one vertically scrollable consumer page.
- Bottom navigation remains fixed.
- Query loading must not reset scroll position or rebuild the shell.
- Long answer/evidence/detail content can extend the scroll body; no content may be clipped or hidden behind navigation.
- At 390×844 the reference establishes first-viewport density, not a requirement to force all dynamic data into a fixed height.

## Geometry Table

| Element | Reference | 390×844 target | Tolerance | Notes |
| --- | ---: | ---: | ---: | --- |
| Page horizontal content inset | ≈33 px | 15 px | ±2 px | Query/cards use full inner width. |
| Header title block | x≈36, y≈117 | x≈16, y≈54 | ±3 px | Includes title/subtitle ink, not system chrome. |
| Query surface | x≈33, y≈315, 787×107 | x≈15, y≈144, 360×49–52 | ±3 px | Dominant input surface. |
| Suggestion chips | y≈450, h≈74 | y≈206, h≈34–38 | ±3 px | Horizontal scrolling permitted. |
| Recent heading | y≈596 | y≈273 | ±4 px | Dynamic section may move with content. |
| Recent card 1 | x≈33, y≈670, 787×315 | x≈15, y≈307, 360×143–155 | ±5 px | Photo-right asymmetric card. |
| Recent card 2 | x≈33, y≈1005, 787×212 | x≈15, y≈460, 360×95–108 | ±5 px | Photo-left asymmetric card. |
| Important people heading | y≈1290 | y≈591 | ±6 px | Only when authority exists. |
| People avatar diameter | ≈200 px | ≈92 px | ±4 px | Runtime asset required; no screenshot crops. |
| Floating capture action | d≈101 px | d≈46–48 px | ±3 px | Tap target may be larger than visual circle. |
| Bottom nav content | y≈1670–1775 | y≈765–813 | ±3 px | Fixed content region. |
| Bottom safe area | y≈1775–1844 | y≈813–844 | ±3 px | System-owned home indicator region. |

## Typography

| Role | Target size | Weight | Line height | Color | Alignment | Max lines |
| --- | ---: | --- | ---: | --- | --- | ---: |
| Page title | 34–38 px | 700–800 | 42–46 px | navy | left | 1 |
| Page subtitle | 18–20 px | 400–500 | 26–30 px | secondary blue-grey | left | 2 |
| Query placeholder | 18–20 px | 400–500 | 26–28 px | secondary blue-grey | left | 1 |
| Suggestion label | 15–16 px | 600 | 22–24 px | navy | center/left | 1 |
| Section title | 28–32 px | 700–800 | 36–40 px | navy | left | 1 |
| Section action | 16–18 px | 500–600 | 24–26 px | secondary blue-grey | right | 1 |
| Memory title | 18–21 px | 700 | 26–30 px | navy | left | 2 |
| Memory metadata | 15–17 px | 400–500 | 23–26 px | secondary blue-grey | left | 1 |
| Memory preview | 15–17 px | 400–500 | 23–27 px | secondary blue-grey | left | 3 |
| Result answer | 18–22 px | 500–700 | 28–32 px | navy | left | dynamic |
| Evidence disclosure | 15–17 px | 500–600 | 23–26 px | secondary blue-grey | left | 2 |
| Bottom nav label | 12–14 px | 500–600 | 18–20 px | muted/active blue | center | 1 |

Dynamic Chinese copy may wrap beyond the reference; accessibility takes precedence over clipping.

## Color

- Page background: warm ivory/off-white, approximately `#FAF8F3`; never use the reference screenshot as a color source at runtime.
- Primary navy text: approximately `#102A50`.
- Secondary text: approximately `#6D829F`.
- Active blue: approximately `#2378E8`, shared with Today V3 navigation.
- Primary card: near-white `#FEFDFE` / equivalent warm-white.
- Query surface: near-white with very light cool/warm separation from page background.
- Suggestion tints: pale blue, peach, amber and green; semantic and low contrast.
- Shadow: very light, broad, low opacity; no heavy border or dashboard panel treatment.

## Radius / Shadow

- Main card radius: 18–20 px target.
- Query surface radius: 18–22 px target.
- Suggestion pill radius: 18–20 px target.
- Photo radius: 10–14 px target.
- Floating action visual radius: circular; maintain a minimum accessible hit target of 48 px where possible.
- Shadow: subtle warm/cool neutral shadow, approximately 0–8 px blur and 0–2 px offset, opacity below 0.12.
- Do not add visible borders merely to create hierarchy.

## Imagery Treatment

- Runtime memory images are real owner-scoped media only.
- The reference lake photo, dinner photo and people portraits are not runtime fallback assets.
- `BoxFit.cover` is allowed for loaded runtime media, with card-specific focal alignment.
- Missing or unauthorized media must use a truthful neutral surface, not a screenshot crop or generated fake memory.
- No decorative image asset is required for the Memory shell unless a formal repository asset is later approved.

## Truth / Data Boundaries

The presentation may rearrange existing data but may not change authority or semantics:

- Query: real `queryMemory()` only.
- Answer: `answer` only when server `can_answer == true`.
- Evidence: real `evidence`; `AI_INFERENCE` is not trusted evidence.
- Memory identity: real `memory_ids`.
- Place/coordinates/visits: real `day_footprint` / `FootprintDay` and `JiYiFootprintMap` only.
- Map: initialize only after accepted `AmapPrivacyConsentAuthority`; no consent means no real map and no fake replacement.
- Memory detail/edit/delete/reminder: preserve `MemoryDetailPage`, revision checks, delete confirmation, reminder flows and media-cache invalidation.
- Session/owner: preserve `queryGeneration`, `sessionVersion`, `authenticatedUserId` fencing.
- Elder mode: keep existing accessible/business behavior; `02_memory.png` is consumer-mode authority only.

## Accessibility

- All query, chip, capture, navigation and management actions retain semantic labels and adequate hit targets.
- Text scale 1.3 must not overflow or hide the primary action.
- Color is never the sole state signal; pair unavailable, loading, error and trust states with text/icons.
- Elder mode remains a supported presentation path and is not replaced by the consumer screenshot composition.
- Small screens may scroll and wrap; they must not clip query input, answer, evidence or navigation labels.

## Screenshot Acceptance

- Primary final parity: fixed iOS Simulator or real-device screenshot at 390×844, DPR 1-equivalent review framing, `zh-CN`, text scale 1.0, with real system chrome.
- Flutter Golden: regression authority only; do not treat it as the final Design Authority screenshot.
- When system chrome is absent from a Flutter screenshot, crop/mask the matching reference status-bar and home-indicator regions before diff.
- Validate visual hierarchy for loaded/default, query input, loading, answerable result, no-answer, evidence, day footprint, map-consent blocked, error and active Memory navigation states.
- Do not update an old pre-V3 Golden by renaming it. New V3 Goldens must have explicit names and fixtures.

## Non-goals

- No backend, API, migration, provider, native auth, App ID or signing changes.
- No AUTH-02/Phone/SMS/WeChat work.
- No Life, Family, Profile, Timeline, Memory Detail, Capture, Year Review or other V3 page implementation.
- No change to Today V3 geometry, Hero, Auth UI, map/data authority or system-chrome acceptance rules.
- No fake data, fake photos, fake places, fake routes, fake timestamps, fake AI answers or fake evidence.
