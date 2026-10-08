# Today Visual Parity Specification

本规格只定义 Consumer Today 的视觉还原目标。`01_today.png` 是唯一的视觉权威；它不授权伪造天气、运动、GPS 轨迹、照片来源或其它业务数据。所有几何数值均为从参考图的栅格和视觉边界推导出的估计值，不是对源设计文件的精密测量。

## 1. Authority

- Visual authority: `mobile/design_reference/v3/01_today.png`
- Reference image: 852 × 1846 px, portrait, 2.1846:1 height/width ratio.
- Primary acceptance viewport: 390 × 844 logical px, portrait, `zh-CN`, text scale 1.0.
- The example strings and images in the PNG are design examples, not business-data authority. In particular, `10月5日`, `2 个地点片段`, `书房`, `公园`, the route shape, the weather-like sunrise, and the two photos must not be hardcoded as product data.
- This document does not change any JiYi theme/token value and does not authorize Flutter implementation in this phase.

The visual language is a calm, light consumer surface: navy typography, warm ivory-to-white background, a full-bleed sunrise landscape, large white floating surfaces, real imagery, and a restrained blue/teal location accent. The page presents lived content first; recording diagnostics are not part of the primary composition.

## 2. Reference Dimensions

### 2.1 Raw reference geometry

The screenshot is 852 × 1846 px. The following boundaries are estimated from visible ink, surfaces, and safe-area landmarks:

| Region | Reference px | Measurement note |
| --- | --- | --- |
| Full viewport | x=0, y=0, w=852, h=1846 | Includes iOS status and home-indicator areas |
| Status bar | x=0, y=0, w=852, h≈88 | Native system area; icons are not page content |
| Header/title block | x≈44, y≈96, w≈530, h≈206 | Title, date, and one-line invitation over Hero |
| Hero landscape field | x=0, y≈0, w=852, h≈365 | Full-bleed atmospheric background; bottom fades into the page |
| Footprint card | x=28, y≈330, w=796, h≈522 | Large floating white surface; radius≈38 |
| Footprint map viewport | x≈46, y≈492, w≈760, h≈340 | Rounded inner map, radius≈26 |
| Memory section card | x=28, y≈880, w=796, h≈565 | Two equal photo stories in one surface |
| Memory photo row | x≈53, y≈994, w≈746, h≈255 | Two photos, gap≈20; each ratio≈1.44:1 |
| Quick-capture card | x=28, y≈1472, w=796, h≈208 | Three equal action cells |
| Bottom navigation | x=0, y≈1694, w=852, h≈152 | Includes the bottom safe area; visually fixed |
| Bottom home-indicator inset | x=0, y≈1798, w=852, h≈48 | Native system area; do not draw over the indicator |

### 2.2 Safe-area relationship

- The top system inset is approximately 88 reference px, or 40 logical px after normalization. The first title ink starts below it, around target y=46–48.
- The page content is allowed to paint the Hero behind the top inset only if the platform shell handles contrast and status-bar icon appearance correctly. Text begins inside the safe area.
- The bottom navigation owns the bottom safe area. The last navigation labels/icons sit above the home indicator; the page body must not place a second bottom inset between the quick-capture card and the navigation surface.
- The navigation surface is fixed above the body scroll layer. The quick-capture card ends immediately above the fixed navigation in the reference first viewport.

## 3. Normalization to 390×844

The reference aspect ratio is almost identical to the target (852/1846≈0.4615; 390/844≈0.4621). Use proportional normalization as the starting point, not a stretch or crop:

- x scale: `390 / 852 ≈ 0.4577`
- y scale: `844 / 1846 ≈ 0.4572`
- The difference is below 0.2%; preserve the target viewport and resolve the residual through safe-area/layout constraints.
- The target outer horizontal margin for the three major cards is approximately 13 px. The target card width is approximately 364 px.
- All target values below are logical px and remain estimates, generally within ±2 px for large boundaries and ±1–2 px for repeated gaps.
- The reference should never be passed through a direct image stretch as an implementation technique. The Hero and photo assets must be laid out with their own aspect-ratio/crop rules.

### 3.1 Screenshot authority and system chrome

There are three distinct screenshot authorities:

1. **Design Authority screenshot** — `01_today.png` is a flattened iOS-style screenshot that includes the status bar at the top and the home indicator/system bottom area. Those pixels are part of the reference framing, but the system chrome itself is platform-owned rather than Flutter page content.
2. **Flutter Golden** — a Flutter Golden is a regression authority for deterministic widget output only. It is not the final Design Parity screenshot authority and must not be treated as equivalent to a full iOS screenshot.
3. **Final Visual Parity screenshot** — use a fixed iOS Simulator configuration or a real-device screenshot with real SafeArea/system chrome. Compare it to the Design Authority through overlay and visual diff.

If a Flutter-level screenshot does not include system chrome, it must not be raw-pixel-compared with the full Design Authority. Mask or crop the corresponding reference status-bar and home-indicator regions first, and document the crop/mask in the diff artifact. A screenshot with a different system-chrome height must use normalized content bounds, not an unqualified pixel comparison.

## 4. Page Anatomy

### A. System / safe area

- Native status bar: target h≈40–44 px, black/navy content on the light Hero. Time and system icons are platform-owned.
- Page body begins visually around target y=44. Header title ink begins around y=47.
- Fixed bottom navigation: target y≈774, total visible h≈70 px plus the native bottom inset already included in the shell. Keep home-indicator space clear.
- The body is a portrait scroll view behind a fixed bottom navigation. The first viewport is intentionally composed to show the Hero, most of the footprint card, the complete memory card, quick capture, and navigation.

### B. Top header

- No separate opaque AppBar is visible. The header is integrated into the Hero atmosphere.
- Main title `今天`: target x≈20, y≈46, ink box≈72×40; estimated 32 px, weight 700–800, line height≈42 px, navy.
- Date line: target x≈20, y≈101, estimated 20 px, line height≈28 px, medium weight. It is server/user-timezone-derived at runtime.
- Invitation line: target x≈20, y≈127, estimated 20 px, line height≈29 px, secondary blue-grey. The copy may change or disappear truthfully; it must not reserve a fake event.
- There is no right-side action in the authority image. Do not add an avatar, notification, settings, or recording-health icon to this header.
- Header left alignment is shared by the card composition: target 20 px for text; major cards begin at 13 px; inner card content begins around 21 px.

### C. Hero / brand atmosphere

- The landscape is a full-width sunrise/mountain/lake scene, visible behind the header and fading into the first card. Target visual field is approximately x=0, y=0, w=390, h=167.
- Use a real approved landscape asset with `cover`; preserve a right-weighted focal point so the sun and mountain ridge remain visible. Do not use a plain gradient placeholder as the final experience.
- Apply a light warm atmospheric treatment: pale sunrise highlights near the upper-right, cool blue-green distant mountains, and a white/transparent bottom fade of roughly 28–40 target px.
- The footprint card floats over the lower fade. Its top edge begins around target y=151 while the atmosphere remains visible immediately above it. The visual overlap/floating relationship is approximately 12–16 target px; do not flatten the page into a normal list.
- Header text must remain readable without a dark engineering overlay. A subtle localized light scrim is acceptable only if it preserves the reference luminance and crop.

### D. Today footprint / map card

- Outer card: target x≈13, y≈151, w≈364, h≈239, radius≈18–19 px, white surface, very low warm-grey shadow, no strong border.
- Inner horizontal padding: approximately 16 px. Top padding is approximately 16–18 px.
- Title row: blue outlined location-pin icon around 28 px, title `今日足迹` around 24 px/30 px, weight 700–800, navy, and a right chevron around 26 px in muted blue-grey. The chevron is a detail affordance, not a fake data state.
- Supporting data: count line around 20 px/28 px; explanatory line around 16 px/24 px. Both are rendered only from the actual Today authority.
- Map viewport: target x≈21, y≈225, w≈348, h≈156, radius≈12–14 px. It is the dominant lower part of the card.
- Map presentation should use the real AMap adapter when both coordinates, consent, and platform configuration exist. Selected marker may use blue; subsequent visit marker may use teal/green. The reference colors are visual guidance, not permission to fabricate coordinates.
- The route-like connector is a visit-order connector between known markers, not a claim of the user’s exact GPS route. If exact route evidence is absent, do not draw a path that implies it.
- If the map cannot be truthfully rendered, preserve the card geometry and show a concise unavailable/coordinate-missing state. Do not replace the map with an invented map screenshot or fake marker.
- The loaded state in the reference is the visual target; empty, unavailable, and consent-blocked states are truthful alternate states and may occupy a taller card.

### E. Today memory / photo story

- Section/card begins around target y≈403, x≈13, w≈364, and ends around y≈666. It is one large white surface with radius≈18–19 px.
- Header row: image-outline icon around 27 px, title `今日记忆` around 24 px/30 px, navy and bold, right chevron aligned to the footprint header.
- Photo row: inner x≈24, target y≈454, w≈342; two equal cards of approximately 166–167 px width, gap≈9–10 px. Photo ratio is approximately 1.44:1, target photo height≈115–117 px.
- Photos use real memory media only. `BoxFit.cover` is expected, with approximately 12 px clipping radius. Do not use a generic icon tile in the loaded photo story state.
- Below each photo: title around 20 px/28 px, weight 700–800, navy; body around 16 px/24 px, secondary blue-grey; maximum two lines for each visible paragraph in the first viewport. Text height may expand for accessibility and then scroll.
- The reference has no engineering confidence, source, queue, or upload badges in this card. Keep provenance accessible through detail, not as primary visual chrome.
- A memory card without an actual media authority must degrade to a truthful text/empty state rather than borrowing the reference photos.

### F. Quick capture / 记一下

- Outer card: target x≈13, y≈674, w≈364, h≈94, radius≈18–19 px, white surface.
- Header: blue outlined pen icon≈27 px and `记一下` around 24 px/30 px, bold navy.
- Action row: three equal cells, target x≈22, y≈722, w≈108–110 px, h≈44–47 px, gap≈7–8 px. Cell radii≈14 px.
- Cell fills are semantic but light: blue-tinted `说一段`, warm amber `写下来`, and pale green `拍张照`. Use icon + short copy; do not add secondary engineering descriptions inside the first viewport.
- The actions invoke the existing capture flows. Their labels and order are part of this authority: `说一段`, `写下来`, `拍张照`.
- If a capability is unavailable, disable or hide it truthfully while preserving the remaining row rhythm; do not make the card appear successful by showing a fake completion state.

### G. Recording status

- No automatic-recording status appears in the Today authority image.
- Recording Health is a secondary settings/profile concern. It must not be placed between Hero, footprint, memory, or capture content, and must not become the Today page’s title/subtitle or dominant banner.
- If a future product decision requires a small status affordance, it must be a subordinate, user-readable state and be separately approved; internal terms such as `producer`, `authority`, `queue`, and `unknown gap` do not belong in this consumer composition.

### H. Bottom navigation

- Fixed five-item IA and order: `今天`, `记忆`, `人生`, `家庭`, `我的`.
- Target navigation content top≈774 and content height≈48–52 px above the bottom safe area; the bottom safe area is a separate native system region. The target bottom navigation content height is≈48 px, bottom safe area≈22 px, and total fixed region≈70 px.
- Each item occupies approximately 20% of width (78 px). Icons are≈24 px; labels are≈16 px/22 px.
- Active item: filled blue home/today icon, blue label, and a short blue underline/pill around 28×3 px centered below the label. The active background is visually quiet; avoid a large Material indicator pill.
- Inactive items: outlined navy/slate icons and muted blue-grey labels.
- Surface is white or near-white with a very soft top separation/shadow, not a heavy divider.
- The default Material NavigationBar may provide semantics/index handling, but its indicator, height, label metrics, and colors need visual restructuring to match this authority.

### I. Scroll model

- The body is vertically scrollable; the bottom navigation is fixed.
- The body scrolls behind/up to the bottom-navigation boundary; it must not scroll underneath the home indicator. The Bottom Navigation fixed region owns its content height and the platform bottom inset exactly once.
- Do not add a second `SafeArea` bottom padding on top of a Flutter `BottomNavigationBar`/`NavigationBar` or shell inset that already includes the bottom padding. Double application visibly raises the navigation and breaks the reference geometry.
- The home indicator belongs to system chrome, not to the Flutter navigation content. The final screenshot must retain it when validating full-screen parity.
- Hero and header scroll with the body. The Hero is not a fixed app-bar background.
- Hero-to-footprint layering is achieved in the first composition with a controlled overlap or negative spacing; later cards use ordinary vertical rhythm.
- At the reference viewport, the first screen shows the full Hero/title, full footprint card, full memory card, full quick-capture row, and fixed navigation. More content continues below if data or accessibility text expands.
- No floating action button is visible in the authority image. Do not add the current shell’s extended `记一下` FAB on top of this page.

## 5. Geometry Table

The footprint card and its nested map viewport are separate geometry objects. **Footprint card = title + metadata + descriptive copy + map viewport.** “Map height” must never be used as a substitute for the outer footprint-card height.

| Element | Reference px | 390×844 target | Tolerance | Notes |
| --- | --- | --- | --- | --- |
| Full viewport | 852×1846 | 390×844 | exact viewport | Portrait; preserve ratio, no stretch |
| Page horizontal padding | x≈28 from viewport edge for major cards | x≈13 from viewport edge | estimated ±2 | Card/page outer padding; header text has its own x≈20 inset |
| Top system inset | y=0–88 | y=0–40/44 | estimated ±2 | iOS status bar; system chrome |
| Header | x≈44, y≈96, w≈530, h≈206 | x≈20, y≈46, w≈243, h≈94 | estimated ±4 | Title, date, and invitation over Hero |
| Hero | x=0, y=0, w=852, h≈365 | x=0, y=0, w=390, h≈167 | estimated ±4 | Full bleed, atmospheric image, bottom fade |
| Hero content | x≈44, y≈96, w≈530, h≈206 | x≈20, y≈46, w≈243, h≈94 | estimated ±4 | Header content inside Hero; no opaque AppBar |
| Hero bottom | y≈365 | y≈167 | estimated ±4 | Fade endpoint / visual Hero field boundary |
| Footprint card | x=28, y≈330, w=796, h≈522 | x=13, y≈151, w=364, h≈239 | estimated ±3 | Outer white floating card; title + metadata + descriptive copy + map viewport |
| Footprint card title/metadata | x≈62, y≈366, w≈728, h≈115 | x≈29, y≈167, w≈332, h≈53 | estimated ±4 | Location title row, count, and descriptive copy |
| Map viewport | x≈46, y≈492, w≈760, h≈340 | x≈21, y≈225, w≈348, h≈156 | estimated ±3 | Nested real-map/fallback surface; radius≈12–14 target |
| Memory section title | x≈61, y≈914, w≈730, h≈62 | x≈28, y≈418, w≈334, h≈29 | estimated ±3 | Icon + `今日记忆` + chevron |
| Today Memory Card / outer section | x=28, y≈880, w=796, h≈565 | x=13, y≈403, w=364, h≈259 | estimated ±4 | One white surface containing both story cards |
| Memory photo 1 / story card 1 | x≈53, y≈994, w≈366, h≈430 | x≈24, y≈454, w≈167, h≈201 | estimated ±5 | Photo plus title/body; photo subframe≈167×117 target |
| Memory photo 2 / story card 2 | x≈437, y≈994, w≈366, h≈430 | x≈200, y≈454, w≈167, h≈201 | estimated ±5 | Same geometry; gap≈9–10 target |
| Memory photo row | x≈53, y≈994, w≈746, h≈255 | x≈24, y≈454, w≈342, h≈117 | estimated ±3 | Two equal photos; gap≈9–10 target |
| Memory/card body gap | ≈24 px | ≈11 px | estimated ±2 | Photo to title/text rhythm |
| Quick Capture Card | x=28, y≈1472, w=796, h≈208 | x=13, y≈674, w=364, h≈94 | estimated ±3 | White surface; title plus three actions |
| Quick action 1 `说一段` | x≈48, y≈1568, w≈242, h≈96 | x≈22, y≈722, w≈110, h≈44–47 | estimated ±3 | Blue-tinted cell |
| Quick action 2 `写下来` | x≈305, y≈1568, w≈242, h≈96 | x≈140, y≈722, w≈110, h≈44–47 | estimated ±3 | Warm amber cell |
| Quick action 3 `拍张照` | x≈562, y≈1568, w≈242, h≈96 | x≈258, y≈722, w≈110, h≈44–47 | estimated ±3 | Pale green cell |
| Bottom Nav content | y≈1694–1798, h≈104 | y≈774–822, h≈48 | estimated ±3 | Fixed Flutter navigation content, excluding home indicator |
| Bottom Safe Area | y≈1798–1846, h≈48 | y≈822–844, h≈22 | estimated ±2 | Native home-indicator/system region |
| Bottom total region | y≈1694–1846, h≈152 | y≈774–844, h≈70 | estimated ±3 | Bottom Nav content + Bottom Safe Area |

## Critical Geometry Constants

All values below are target logical px unless a Reference value is shown. They are estimated anchors for visual comparison, not production hardcoded values.

| Constant | Value | Reference anchor | Tolerance | Definition |
| --- | --- | --- | --- | --- |
| `PAGE_HORIZONTAL_PADDING` | ≈13 px | ≈28 px | estimated ±2 | Outer margin for major cards |
| `HERO_HEIGHT` | ≈167 px | ≈365 px | estimated ±4 | Full-bleed Hero visual field |
| `HERO_BOTTOM` | y≈167 | y≈365 | estimated ±4 | Hero visual bottom/fade endpoint |
| `FOOTPRINT_CARD_TOP` | y≈151 | y≈330 | estimated ±3 | Outer footprint card top |
| `FOOTPRINT_CARD_WIDTH` | ≈364 px | ≈796 px | estimated ±3 | Outer footprint card width |
| `FOOTPRINT_CARD_HEIGHT` | ≈239 px | ≈522 px | estimated ±3 | Outer footprint card height |
| `HERO_CARD_OVERLAP` | ≈16 px | ≈35 px | estimated ±2/4 | `HERO_BOTTOM - FOOTPRINT_CARD_TOP`; visual fade overlap |
| `MAP_VIEWPORT_HEIGHT` | ≈156 px | ≈340 px | estimated ±3 | Nested map/fallback viewport height |
| `MEMORY_SECTION_TOP` | y≈403 | y≈880 | estimated ±4 | Outer Today Memory Card top |
| `MEMORY_CARD_HEIGHT` | ≈259 px outer section; ≈201 px each story card | ≈565 px outer; ≈430 px each story | estimated ±4/5 | Explicitly distinguishes section from two inner stories |
| `QUICK_CAPTURE_HEIGHT` | ≈94 px | ≈208 px | estimated ±3 | Outer Quick Capture Card |
| `BOTTOM_NAV_CONTENT_HEIGHT` | ≈48 px | ≈104 px | estimated ±3 | Flutter navigation content only |
| `BOTTOM_SAFE_AREA` | ≈22 px | ≈48 px | estimated ±2 | Native home-indicator region |
| `BOTTOM_TOTAL_REGION` | ≈70 px | ≈152 px | estimated ±3 | Navigation content + native safe area |

### Explicit Hero / Footprint overlap anchors

- `HERO_BOTTOM_REFERENCE = y≈365 px` (estimated ±4 px).
- `FOOTPRINT_CARD_TOP_REFERENCE = y≈330 px` (estimated ±3 px).
- `HERO_CARD_OVERLAP_REFERENCE = ≈35 px` (estimated ±4 px), computed as `365 - 330`.
- `HERO_BOTTOM_TARGET = y≈167 logical px` (estimated ±4 px).
- `FOOTPRINT_CARD_TOP_TARGET = y≈151 logical px` (estimated ±3 px).
- `HERO_CARD_OVERLAP_TARGET = ≈16 logical px` (estimated ±2 px), computed as `167 - 151`.

## 6. Typography

Use the platform’s Chinese system sans or the project’s approved Chinese font family. The reference has a strong, dark navy display hierarchy; do not let the current default Material scale reduce it. Values are estimated target logical px.

| Role | Size / line height | Weight | Color / alignment | Max lines / overflow |
| --- | --- | --- | --- | --- |
| Page title `今天` | 32 / 42 | 700–800 | #0B2346, left | 1; no ellipsis |
| Date / greeting | 20 / 28–29 | 500–600 | #17345B then #6D86A2, left | 1–2; truthful wrap |
| Hero decorative copy | none beyond header | — | No extra badge/eyebrow | Do not add `迹忆 · 今天` |
| Section title | 24 / 30 | 700–800 | #0B2346, left | 1; keep title visible |
| Map card title | 24 / 30 | 700–800 | #0B2346, left | 1–2 for long localized place labels |
| Map count | 20 / 28 | 500–600 | #17345B | 1–2 |
| Map metadata | 16 / 24 | 400–500 | #6D86A2 | 2; wrap rather than invent |
| Memory card title | 20 / 28 | 700–800 | #0B2346 | 2; wrap |
| Memory body | 16 / 24 | 400–500 | #6D86A2 | 2 in first viewport; expand/scroll for accessibility |
| Capture label | 16–18 / 22–24 | 600–700 | Navy or semantic accent | 1 where possible |
| Bottom-nav label | 16 / 22 | 500; active 600–700 | Active #1976E8; inactive #71849C | 1; do not truncate common IA |
| Native status text | platform-controlled | platform | Navy/black on light Hero | System-owned |

Letter spacing is close to zero for Chinese body text. The large title may use a slight negative tracking, approximately -0.3 to -0.6 px, but this should be verified with the actual product font.

## 7. Color Roles

These are approximate visual samples/roles, not a request to edit `JiYiProductColors` in this phase.

| Role | Approximate HEX | Visual use | Semantic role |
| --- | --- | --- | --- |
| Page background | #FBF8F3, fading toward #FFFDFC | Warm surrounding canvas | Calm consumer background |
| Surface | #FFFFFF / #FFFEFD | Footprint, memory, capture, nav surfaces | Primary content surface |
| Primary navy text | #0B2346 | Page/section/card headings | High-priority readable content |
| Secondary text | #6D86A2 | Greeting, metadata, memory body | Supporting content |
| Primary blue | #1976E8 / #2A83F4 | Location icon, active navigation, capture blue | Brand/action accent |
| Active blue fill | #E7F1FF | Selected nav affordance or blue action cell | Non-blocking selection state |
| Warm sunrise | #FFE6BD, #F7D6C0 | Hero highlights | Decorative atmosphere only |
| Map tint | #EAF4FA, #DCEEF8 | Map water/road base | Location visualization |
| Map vegetation | #E4F1E9 | Map land/parks | Location visualization |
| Photo overlay | rgba(255,255,255,0.02–0.08) | Optional legibility treatment below text, not over photo detail | Image readability |
| Border | #EFF2F4 | Optional very-low-contrast surface edge | Separation, not emphasis |
| Shadow | rgba(20,45,75,0.06–0.10) | Large floating cards/nav | Depth only |
| Location/visit teal | #27A89A | Secondary marker and green capture action | Location/confirmed semantic accent |
| Warm capture amber | #E59117 / pale #FFF2DF | `写下来` action cell | Text capture affordance |

Do not use color alone for unavailable, pending, or error states. Those states require truthful text and accessible semantics.

## 8. Radius / Shadow / Layering

- Major cards: target radius 18–19 px; reference ≈38 px at 2×. All three major surfaces share this family.
- Map inner surface: target radius 12–14 px; it is visibly nested within the footprint card.
- Memory photos: target radius≈12 px; clip the image, not just its parent background.
- Quick-capture cells: target radius≈14 px, softer than a rectangular button but less circular than a pill.
- Navigation active mark: 3 px high, around 28 px wide, rounded/pill ends; do not use a large filled Material indicator.
- Card shadow: very soft, approximately y-offset 3–6 px, blur 14–22 px, opacity 6–10%. A faint border is acceptable only when needed on a white-on-white background.
- The dominant depth relationship is `Hero atmosphere → white floating footprint card → nested map surface`, followed by the memory and capture surfaces. Do not put a heavy elevation shadow on every child.
- The map card top must retain the floating/overlap feeling. Replacing it with a flat sequence of equally spaced SectionCards fails parity even if individual colors match.

## 9. Imagery Treatment

### Hero

- Real landscape/mountain/lake asset, `cover`, full width, right-weighted focal point.
- Preserve a readable warm sky, visible sun disk/right ridge, cool distant mountains, and a pale bottom fade. Crop vertically rather than distort.
- The final asset must be an approved product asset, not a screenshot crop of `01_today.png` and not a generic gradient placeholder.

### Memory photos

- Two independent, real photo memories in a 1.44:1 frame, `BoxFit.cover`.
- Keep the salient subject visible: left image’s board/table area and right image’s tree/lake/bench composition are examples of the intended balance, not data to hardcode.
- Clip corners at≈12 px. Do not add heavy dark gradients, photographer metadata, engineering badges, or fake timestamps over the image.
- The screenshot photos are design authority imagery. Runtime memory cards must use signed/validated media from the actual memory authority and must degrade truthfully when unavailable.

## 10. Map Treatment

- The screenshot’s pastel map is a visual composition reference: pale map base, soft green areas, blue water/roads, blue ordered connector, two distinct marker states, and white place/time labels.
- Runtime must use the actual AMap surface when privacy consent, SDK configuration, and complete place coordinates are available. `JiYiFootprintMap` already centralizes this boundary.
- Marker order is the server-provided visit order. The connector may connect those points in order for orientation, but it must be labeled conceptually as “visit order,” never as a precise GPS track.
- No coordinate means no map marker. Partial coordinates are invalid for drawing a point.
- Exact route, travel path, speed, distance, and continuous GPS history are NOT available authority for this card. Hide them.
- Consent-blocked, missing-key, and no-coordinate states must remain readable and preserve the surrounding card hierarchy. They must not silently render an illustrative route.
- Selected state may highlight the first/selected visit, but the selection must correspond to a real visit object.

## 11. Real Data Authority Mapping

| Visual Element | Required Authority | Current Availability | V3 Behavior |
| --- | --- | --- | --- |
| Today date | `/v1/today/footprint` `day` plus server/user timezone | AVAILABLE | Render the actual local day; never hardcode `10月5日` |
| Visit | Today Footprint response `visits[]` | AVAILABLE | Render only parsed server visits; empty/failure stays truthful |
| Place | `place_id`, `place_name`, optional address/category | AVAILABLE | Use returned place data; do not infer from device location |
| Place coordinates | Paired `place_latitude` + `place_longitude` | PARTIAL | Map only when both exist and are valid; otherwise show no-coordinate state |
| Map | AMap SDK + privacy consent + platform SDK key + coordinates | PARTIAL | Use real AMap when all prerequisites hold; otherwise explicit unavailable/fallback |
| Marker | Real mappable visit coordinate | PARTIAL | One marker per real mappable visit; never create a decorative marker |
| Visit order | Ordered `visits[]` from canonical day-footprint service | AVAILABLE | Use order for labels/connector semantics; do not call it a route |
| Exact route | Continuous GPS/route authority | NOT AVAILABLE | Hide; connector is only ordered-place orientation |
| Visit duration | `arrived_at_local` and optional `left_at_local` | PARTIAL | Show duration only when both timestamps exist and are valid; otherwise hide |
| Photo | Timeline `MEMORY` with `memoryType=PHOTO`, `mediaId`, validated media download/cache | PARTIAL | Show real photo story only for actual media; no reference-photo fallback |
| Memory | `/v1/timeline/events?day=...` parsed `TimelineReadItem` | AVAILABLE | Render actual title/content/time; unavailable/empty state is explicit |
| Recording Health | Recording-health endpoint plus native/queue evidence | AVAILABLE, secondary | Keep out of primary Today composition; expose in the existing secondary surface |
| Weather | No Today weather authority in current contract | NOT AVAILABLE | Hide |
| Steps | No Today steps authority in current contract | NOT AVAILABLE | Hide |
| Activity | No Today activity authority in current contract | NOT AVAILABLE | Hide |
| Family activity | Explicit family authorization/read authority, not Today owner data | NOT AVAILABLE for this card | Hide from Today; do not infer family movement |
| Hero image | Approved static product imagery | PARTIAL | Implement with approved asset matching the reference treatment; it is decorative, not personal data |

## 12. Existing Code Mapping

Read-only mapping against the current branch:

| Design Element | Current File/Symbol | Reusable | Replace / Restructure | Reason |
| --- | --- | --- | --- | --- |
| Today root/content lifecycle | `mobile/lib/today_footprint_page.dart` — `TodayPage`, `_TodayPageState` | Yes: session-aware loading, fail-closed parsing, memory read | Restructure visual shell | Existing root already protects server authority and handles stale sessions |
| App shell / safe areas | `mobile/lib/stage1_app.dart` — `_AppShellState.build`, `AppShell` | Partly | Restructure body/nav composition | Current `SafeArea` and fixed `NavigationBar` are useful boundaries; current layout also adds an extended FAB not present in authority |
| Hero | `mobile/lib/ui/jiyi_components.dart` — `JiYiHeroHeader`, `_JiYiHeroLandscapePainter` | Painter concept only | Replace/restructure | Current Hero is a gradient/CustomPaint illustration in a rounded box; authority requires a full-bleed real landscape with crop/fade and integrated header |
| Footprint section | `mobile/lib/today_footprint_page.dart` — `_TodayExperienceBody._footprintCard` | Data, tap-through, empty/error semantics | Replace geometry and content hierarchy | Current generic `JiYiSectionCard` is a normal list card and places a map plus pills, not the floating card composition |
| AMap surface | `mobile/lib/amap_footprint_map.dart` — `JiYiFootprintMap`, `_NativeFootprintMap` | Yes, strongly | Adapt visual host/height only | Privacy, key checks, coordinate filtering, marker order, camera fitting, and real connector logic are valuable nonvisual boundaries |
| Memory query/read | `mobile/lib/today_footprint_page.dart` — `_memorySection`, `TimelineReadItem` | Yes: authority and media identity | Replace card layout | Current section is a vertical list with 88×88 thumbnails; authority is a two-column photo story surface |
| Media presentation | `mobile/lib/media_presentation_cache.dart` — `LocalMediaThumbnail`, `LocalMediaCache` | Yes | Keep outside visual redesign | Cache, signed media, invalidation, and offline truth are independent of card geometry |
| Quick capture | `mobile/lib/today_footprint_page.dart` — `_quickCapture`, `_TodayQuickAction` | Callback wiring and actions | Replace geometry/copy hierarchy | Current actions are verbose vertical mini-cards; authority is a compact three-cell row |
| Capture flow | `mobile/lib/unified_capture_section.dart` — `CapturePage`, `TrustedMediaCaptureService` | Yes | No visual reuse from its page shell | Real text/photo/voice capture and cleanup behavior must remain authoritative |
| Bottom navigation | `mobile/lib/stage1_app.dart` — `NavigationBar` destinations and `index` | IA, semantics, routing | Replace visual metrics/indicator | Current five destinations are correct, but default Material height/indicator/icon treatment does not match the reference |
| Theme | `mobile/lib/ui/jiyi_theme.dart` — `JiYiTheme` | Existing central source | Future token-level visual work only | This phase must not modify ThemeData; current colors/radii are materially different from authority |
| Tokens | `mobile/lib/ui/jiyi_tokens.dart` — `JiYiSpacing`, `JiYiRadius`, `JiYiProductColors` | Centralization pattern | Future spec-driven adjustment | Do not edit tokens in this spec phase; map authority values first |
| Shared surfaces | `mobile/lib/ui/jiyi_components.dart` — `JiYiSectionCard`, `JiYiPageFrame` | Accessibility/semantics patterns | Do not copy geometry | Their generic padding, borders, radius, and list flow are the main visual mismatch for Today |
| Recording Health | `mobile/lib/recording_health_section.dart`, used from `stage1_app.dart` Profile area | Yes, as secondary logic/UI | Keep out of Today | The authority image contains no diagnostics and consumer content must remain primary |

## 13. Possible Archive Reuse

Read-only review of `archive/ui-neutral-rebuild-before-v3-20261006` found the following nonvisual logic worth preserving or consulting. The archive’s geometry, theme, Golden output, and visual hierarchy are not Design Authority and must not be copied.

| File / symbol | Why reusable later |
| --- | --- |
| `mobile/lib/api_client.dart` — `JiYiApiClient.getTodayFootprint` and authenticated request/session handling | Keeps Today bound to the server’s canonical day/timezone contract and avoids device-location substitution |
| `mobile/lib/footprint_models.dart` — `FootprintDay`, `FootprintVisit` | Strict parsing, paired-coordinate validation, visit order, timestamps, and finalized state are data boundaries rather than visual decisions |
| `mobile/lib/amap_privacy_consent.dart` — `AmapPrivacyConsentAuthority` and store/controller | Prevents native map construction before user disclosure/consent and supports revocation |
| `mobile/lib/amap_footprint_map.dart` — `JiYiFootprintMap`, camera fitting, marker and ordered connector adapters | Real map integration, marker creation, coordinate filtering, and no-fake-route behavior can survive the visual rebuild |
| `mobile/lib/media_presentation_cache.dart` — `LocalMediaCache`, authority validation, `LocalMediaThumbnail` | Keeps signed media, cache invalidation, offline behavior, and media identity truthful while card geometry changes |
| `mobile/lib/timeline_models.dart` — `TimelineReadPage` and `TimelineReadItem` | Provides strict memory/media/title/content/time parsing for the Today photo story |
| `mobile/lib/recording_health.dart` and `recording_health_section.dart` | Secondary recording evidence and action handling should remain available in Profile/settings, not migrate into the Today visual hierarchy |
| `mobile/lib/passive_memory_delivery.dart` — recovery/delivery coordinator | Background capture delivery is system behavior and should not be reimplemented as a visual Today status card |

No archive-only visual WIP is promoted to authority. In particular, do not reuse archive Golden geometry, generic SectionCard spacing, default navigation styling, or placeholder Hero treatment.

## 14. Responsive Behavior

### System chrome and responsive screenshot rules

- `390×844` is the primary normalized visual-parity target, but it is not the only physical screenshot configuration that may be validated. The Design Authority PNG remains the sole design reference; fixed iOS Simulator and real-device screenshots are the final parity evidence.
- The Design Authority includes iOS status-bar and home-indicator pixels. Flutter Goldens are regression-only artifacts and are not final system-chrome parity evidence.
- For a Flutter-level capture without system chrome, crop or mask the corresponding reference status-bar and home-indicator regions before overlay/diff. Never perform a raw full-frame pixel comparison between a chrome-less Flutter capture and the full Design Authority.
- Final parity captures must record device/simulator model, logical viewport, scale, locale, text scale, top/bottom insets, and whether system chrome was included. SafeArea geometry must be compared separately from system-owned pixels.

### Small screens

- Keep portrait composition, the 13–16 px outer margin family, the Hero-to-footprint overlap, and the fixed five-item navigation hierarchy.
- At a 320 px viewport, reduce outer margin to a minimum of 12 px and let the map surface shrink with the card; do not crop the map horizontally.
- Keep memory photos in two columns down to the smallest supported layout where each column remains at least approximately 128 px wide. If the platform cannot meet that minimum, a two-item horizontal story rail is preferable to unrelated full-width list cards, subject to accessibility review.
- Capture cells may reduce label size/padding within the defined range, but retain three equal cells and their semantic colors.

### Large font / accessibility

- Text blocks, memory titles, metadata, and unavailable states may grow vertically. Body scroll must continue; do not clip text to preserve the screenshot’s exact height.
- Preserve Hero visual ratio, map/card width, footprint-first hierarchy, memory-photo relationship, and fixed navigation IA. These are structural invariants.
- At text scale above 1.0, allow the greeting, map metadata, memory text, and capture labels to wrap. Keep page title and common nav labels readable rather than ellipsizing them.
- Minimum touch targets remain platform/accessibility compliant even if the visual icon is 24–28 px.

### Safe-area and long Chinese text

- Read top/bottom insets from `MediaQuery` once at the shell boundary; avoid double-applying SafeArea inside Today cards.
- Long place names and memory titles wrap within their card; they must not overwrite the chevron or map.
- Long memory content may continue below the first viewport. Do not shorten content with invented summaries.
- On unusual bottom insets, navigation height grows only enough to preserve the home-indicator clearance; it must remain visually subordinate to content.

## 15. Implementation Order

This is a plan for a later implementation phase only:

1. App shell / viewport: fixed bottom nav, top/bottom insets, scroll ownership, remove the Today FAB from this composition.
2. Hero: real approved asset, full-bleed crop, header placement, bottom fade, and overlap anchor.
3. Map Card geometry: outer surface, title/count/meta rows, nested map viewport, truthful fallback height.
4. Main content composition: memory photo story and vertical rhythm between major surfaces.
5. Bottom Navigation: five fixed destinations, active mark, icon/label metrics, shadow.
6. Typography: display/card/nav hierarchy using the approved Chinese font stack.
7. Spacing: normalize outer margins, inner padding, photo gap, action-cell gap, and viewport rhythm.
8. Imagery: approved Hero and real media thumbnails with crop/clip behavior.
9. Radius / Shadow: major surface hierarchy, nested map, photo corners, low-elevation depth.
10. Micro polish: chevrons, icon stroke weights, subtle gradient/fade, loading/empty/error transitions, and accessibility states.

## 16. Visual Acceptance Checklist

Future implementation is PASS only when all applicable items are satisfied:

- [ ] Overall silhouette matches the reference.
- [ ] First viewport composition matches: Hero, footprint, memory, capture, and fixed navigation are all present at the expected rhythm.
- [ ] Hero height and crop match; atmosphere is a real approved image treatment, not a plain gradient placeholder.
- [ ] Footprint card placement and width match.
- [ ] Hero/footprint overlap and floating depth match.
- [ ] Map viewport geometry and inner radius match.
- [ ] Memory card width, photo ratio, crop, and two-column rhythm match.
- [ ] Quick-capture card and three-cell action geometry match.
- [ ] Typography hierarchy, wrapping, and contrast match.
- [ ] Spacing rhythm and major radii match.
- [ ] Bottom navigation geometry, selected state, labels, and fixed behavior match.
- [ ] A real map is used when authority/configuration/consent exists.
- [ ] No fake exact GPS route is drawn or described.
- [ ] No unsupported fake weather, steps, activity, family activity, visit duration, photo, or memory data appears.
- [ ] Consumer Today contains no engineering/debug UI or recording-health diagnostics.
- [ ] A final Visual Parity screenshot is generated from a fixed iOS Simulator or real device with real SafeArea/system chrome, including status bar and home indicator.
- [ ] Flutter Golden output, if generated, is treated only as regression authority and is not substituted for the final parity screenshot.
- [ ] If the Flutter-level screenshot omits system chrome, the corresponding reference chrome regions are explicitly cropped or masked before comparison; no raw full-frame pixel diff is used.
- [ ] The screenshot capture records viewport, scale, locale, text scale, and top/bottom SafeArea values.
- [ ] A 50% reference/implementation overlay is generated.
- [ ] A visual diff is generated.
- [ ] The overlay/diff distinguishes system-owned chrome from Flutter-owned content bounds.
- [ ] Top mismatches are documented with measured coordinates.
- [ ] User manually approves the result.

## 17. Open Uncertainties

- The approved runtime Hero asset and its exact focal point are not identified by the PNG alone.
- The reference map is a stylized visual sample. Exact AMap styling, label density, and whether any route-like connector is shown for a given data state require product/runtime validation.
- The backend may return visits without paired coordinates; the visual fallback for that case must be approved alongside the loaded state.
- Timeline memory records and signed media availability may not produce two PHOTO cards on every day. The reference’s two-photo composition is not a requirement to fabricate or duplicate media.
- The exact product Chinese font and font metrics are not determinable from the flattened PNG; visual comparison must use the approved app font stack.
- Status-bar appearance and bottom safe-area height vary by device. The target values above describe the 390×844 acceptance model, not a hardcoded device frame.
- The reference shows no weather, steps, activity, family activity, or recording-health element. Their absence is intentional until a separate visual authority and data contract are approved.

TODAY SPEC READY FOR REVIEW
