# UI/UX V2 Acceptance Gate

> Issue #177

## Dependency

正式大规模 UI 实装前：

```text
#163 merged
→ #177 clean replay latest main
→ behind main = 0
```

UI 改造不得替换/弱化 #163 typed parsers、authority、stale guards、tests。

## Flagship screenshot set

必须有真实生产实现 + screenshot/golden review：

```text
Today
Timeline
Memory Detail
Unified Capture
Query
People
Person Detail
Related / Graph-derived content
Life
LifeEvent
LifeStage
Annual Memoir
Life Memoir
Family
Family permissions/member
My/Profile
Privacy
Memory Summary
AI unavailable
Offline
Empty
Elder Mode representative screen
```

## Product-language audit

用户代码中不得无理由出现：

```text
Memory
Evidence
retained Visit
Graph
LifeEvent
LifeStage
citation
slot
cursor
revision
provider
provenance
trust_state
source_type
memory_id
UUID
```

所有例外必须 review 注明理由。

## Design-token audit

旗舰页不得散落重复：
- raw brand colors；
- semantic colors；
- arbitrary radius；
- arbitrary spacing；
- duplicate button/card style。

## Component duplication audit

Flutter 与 Mini 都要检查重复视觉模式并收敛。

## Flutter visual gate

Required:
- deterministic committed goldens；
- fixed font；
- fixed viewport；
- normal scale；
- elevated text-scale regression；
- intentional mismatch proof；
- Android debug/release；
- iOS no-codesign；
- clean worktree。

## Mini visual gate

Required:
- deterministic visual-review artifacts / screenshots；
- narrow/common/large width 代表性覆盖；
- production WeChat build；
- 主操作不裁剪；
- 无页面级随机视觉漂移。

## State gate

每个核心 read surface 至少有：

```text
loading
success
empty
retryable network error
fail-closed protocol error
auth/session invalid
permission denied where applicable
offline where applicable
```

AI additionally:
- inferred；
- uncertain；
- unavailable。

## Small-screen gate

覆盖：
- ~320 width；
- ~390 width；
- large phone。

必须：
- 标题不裁剪；
- 主按钮可见；
- 无 horizontal overflow；
- tab 可操作；
- touch target 合格。

## Large-font gate

代表性旗舰页面提高 text scale。

PASS：
- 关键标签可见；
- 按钮可点击；
- card 自然增长；
- 无文字重叠；
- nav 可理解。

## Elder Mode

至少验证：
- Today；
- Capture；
- Query；
- Family/Profile 代表页。

保持相同 authority，只调整可读性和交互尺寸。

## Trust / AI gate

直接 FAIL：
- deterministic Query 被标 AI；
- raw backend enum 可见；
- AI prose 没 SEC-013 disclosure；
- citation/slot/provenance 可见；
- unavailable/uncertain 状态展示旧生成文本。

## Privacy regression gate

不得回归：
- Privacy Pause；
- Family exact grants；
- Location permission；
- Account Delete；
- Data Delete；
- owner/session switch；
- signed media。

## Performance gate

检查：
- scroll jank；
- image thumbnail loading；
- blur/elevation cost；
- rebuild churn；
- photo-heavy screen memory。

列表不得在 thumbnail 可用时加载 full-res。

## Required exact-head CI

```text
Mobile CI             PASS
Mobile Visual Preview PASS
Mini Program CI       PASS
Backend CI            PASS if backend touched
latest-main           behind = 0
```

## Formal review

仍采用：

```text
P0 / P1 / P2 = 0 / 0 / 0
Overall = PASS / READY
```

UI/UX-001 的完成定义：

```text
真实 production components
+ 真实数据
+ 用户语言
+ accessibility
+ visual regression
+ exact-head CI
+ formal product/visual review
+ merged main
```

“效果图很好看”本身不算完成。
