<!-- 本文冻结 Stage 1G 第一阶段 Flutter Product UI / Design System 的审查基线、设计 token 与改造边界；后续实现必须以本文和 Issue #16 为准。 -->
# Stage 1G Flutter Product UI / Design System 审查与方案

## 1. 基线与范围

- Issue：#16 `Stage 1G: Product UI and design system`
- 开发分支：`feat/stage1-product-ui`
- 审查基线：`main=677b6ce9707b0a60e4581ac6cb95eefb94166677`
- 进度 ID：`S1-027`
- 第一阶段只覆盖 Flutter；微信小程序后续独立同步视觉语言。
- 不修改 Backend API、Evidence gate、SQLite schema、媒体协议、离线同步规则或任何 Stage 2 能力。
- PR #13 的 Golden / intentional mismatch / artifact / dirty gate 继续作为 UI 改版保护网。

## 2. 当前 UI 审查结论

当前 Flutter 已经具备完整的功能型骨架，但还不是可长期维护的产品级设计系统。核心 UI 几乎全部集中在 `mobile/lib/stage1_app.dart`，全局 Theme 只定义 Material 3、品牌 seed 与 Scaffold 背景；页面内部大量直接写 spacing、字体、Card、Input、Button 和状态样式。现阶段最重要的不是立即换颜色，而是先建立一个生产 Theme 单一事实源，再统一页面层级、状态反馈、Evidence 信息层级和隐私表达。

### 2.1 跨页面问题清单

| 领域 | 当前情况 | 产品风险 / 维护成本 | G 线处理方向 |
| --- | --- | --- | --- |
| Theme | 生产 Theme 只有 `useMaterial3`、`colorSchemeSeed=#446A57`、`scaffoldBackground=#F7F8F6` | Button/Input/Card/Dialog/Nav 仍依赖默认值，后续页面容易继续漂移 | 建立 `JiYiTheme`，统一 Material 组件主题；保留当前品牌 seed 作为起点 |
| Golden Theme | `visual_golden_test.dart` 重复声明 seed/background | 生产 Theme 改了而 Golden Theme 没改，会冻结错误视觉 | Golden 必须复用生产 Theme，只允许注入确定性测试字体 |
| Typography | 页面多处直接写 `17px + w700`、标题 `w700/w800` | 中文层级不稳定，后续改字号需要全局搜索 | 基于 Material `TextTheme` 固化品牌、页面标题、section、正文、metadata、label 层级 |
| Spacing | 直接出现 6/8/12/14/16/18/20/22/24/28/36/48 等数值 | 视觉节奏不统一，magic number 多 | 收敛到 4/8/12/16/20/24/32/40/48 token；例外必须有明确理由 |
| Radius / Surface | Card 多为 `elevation: 0`，边界依赖默认 Material | Surface 层级弱，卡片与背景容易混成一层 | 统一 Card/Container radius、outline、surfaceContainer 层级 |
| Button | Filled / tonal / outlined 混用但无产品级规则 | 主次操作与危险操作层级不稳定 | 用 Theme 统一高度/shape；定义 primary/secondary/destructive 使用规则，不为每个按钮再造 wrapper |
| Input | Auth 字段显式 `OutlineInputBorder`，Capture 部分字段不显式 border | 同一产品输入框外观不一致 | 统一 `InputDecorationTheme`，页面只提供 label/hint/helper/error |
| Loading | Auth/Query 改按钮文字；Profile 用圆形进度；Privacy 只禁用按钮 | 同一状态出现三套表达 | 建立统一 inline loading / page loading 规则 |
| Error | 红色裸文本、普通文本、Profile fallback 三种方式 | 错误重要性与恢复动作不清晰 | `JiYiStatusBanner.error` + 页面级 error/重试模式 |
| Success | 多处用字符串前缀 `✓`，甚至展示内部 Memory ID / client UUID | 客户可见开发信息过多，视觉层级弱 | 成功用统一 status banner；隐藏无产品意义的内部 ID，但不伪造成功状态 |
| Empty | Timeline/Today 用普通 InfoCard；Query 无结果嵌在答案卡 | 空态与普通内容无区分 | 建立 `JiYiEmptyState`，保留真实原因与下一步动作 |
| Evidence | `ListTile` 直接拼 `source_type/kind/occurred_at/confidence` | 最关键的可信信息可读性最弱，原始枚举/时间难理解 | 建立 EvidenceCard：摘要优先，来源/证据类型/时间/可信度分层，不隐藏任何可信信息 |
| Privacy | active/paused 主要靠一句文本；四个时长按钮视觉同级；raw `paused_until` | 隐私状态不够醒目，时间不友好 | 用明确状态 badge/banner + 人类可读时间；暂停/恢复仍严格沿用现有 API |
| Navigation | Material NavigationBar 可用，但 selected/unselected icon 只靠默认状态 | 产品辨识度和选中反馈较弱 | 统一 NavigationBarTheme；必要时为 selectedIcon 使用对应 filled icon，不改导航结构 |
| Dialog | 删除确认使用普通 FilledButton | 危险动作可能被误识别为主操作 | 统一 DialogTheme，删除动作使用 error/destructive 视觉但不改变二次确认逻辑 |
| Responsive | 固定手机 padding，Golden 仅 390×844 | 大屏/横屏后续容易出现过宽内容 | 第一阶段保持手机优先，PageFrame 增加一致 content inset；暂不擅自扩展平板布局 |
| Dark mode | 当前产品没有 darkTheme/themeMode 产品能力 | 半套深色主题会制造更多不一致 | 本 PR 不新增主题切换，只把 token 结构做成未来可扩展 |

### 2.2 当前页面逐页审查

| 页面 | 当前优点 | 主要问题 | 第一阶段目标 |
| --- | --- | --- | --- |
| 登录 / 注册 | 流程简单，错误和 loading 已有真实状态 | 品牌感弱；表单与其他页面输入样式不一致；页面上下留白依赖 magic numbers | 品牌 header + 统一表单 card/field/button；不改认证语义 |
| 今天 | 信息简单，无伪数据 | 客户直接看到“Stage 1”开发术语；只有普通 InfoCard，缺乏产品首页层级 | 改为正式产品文案和清晰欢迎/能力卡，不新增不存在的动态数据 |
| 时间轴 | 明确没有提前实现自动足迹 | 客户直接看到“Stage 2”；placeholder 与普通内容视觉相同 | 保留功能边界，用产品化 EmptyState 表达“自动足迹尚未开放” |
| 记一下 | 文字与物品位置流程都真实接 API；离线 pending 有事实来源 | 两张 Card 结构重复；字段边界不统一；成功/错误裸文本；内部 Memory ID/client UUID 对客户价值低 | 统一 section card + form field + status banner；业务方法保持不动 |
| 问记忆 | Evidence 真值完整；删除有确认 | 回答、certainty/intent、Evidence metadata 全挤在普通 Card/ListTile；枚举和时间可读性弱 | AnswerCard + EvidenceCard + destructive action；可信信息更清楚而不是更少 |
| 我的 / 隐私 | 资料与暂停 API 均是真实服务端状态 | 页面 loading/error 与其他页面不一致；Privacy active/paused 区分弱；`paused_until` raw | 统一 profile card、privacy status、loading/error；不改变暂停规则 |

## 3. Design Token 方案

### 3.1 Color

第一阶段继续以现有 `#446A57` 作为品牌 seed，避免为了“改版”随意更换品牌色。使用 `ColorScheme.fromSeed` 统一 primary/onPrimary/secondary/surface/error 等 Material 语义；额外的 success/warning/info 通过一个轻量 `ThemeExtension` 提供，并在实现时验证文字对比度。

- Brand seed：`#446A57`
- App background：沿用当前近白暖灰方向 `#F7F8F6`
- Surface：由 Material 3 surface / surfaceContainer 系列管理
- Error：使用 `ColorScheme.error`
- Success / Warning / Info：仅作为状态语义色，不替代正文颜色，也不得用颜色作为唯一状态提示

### 3.2 Spacing

| Token | 值 | 用途 |
| --- | ---: | --- |
| `space1` | 4 | icon/text 微间距 |
| `space2` | 8 | 紧凑控件内部/同行间距 |
| `space3` | 12 | field/按钮相邻间距 |
| `space4` | 16 | card padding / section 内标准间距 |
| `space5` | 20 | 页面水平 inset |
| `space6` | 24 | 页面主要 section 间距 |
| `space8` | 32 | 大区块间距 |
| `space10` | 40 | hero/header 间距 |
| `space12` | 48 | 仅品牌页顶部等大留白 |

原有 14/18/22/28/36 等散值在迁移时优先归一，不做机械“一刀切”；确有排版理由的例外要在代码旁标明。

### 3.3 Radius / Elevation

- `radiusControl = 12`
- `radiusCard = 16`
- `radiusLarge = 24`
- 普通内容 surface 优先 `elevation 0 + outline/surfaceContainer`
- 需要浮层感的交互 surface 才使用低 elevation；Dialog 使用 Material 标准 elevation

### 3.4 Typography

不再在页面直接写散落 `TextStyle(fontSize: 17, fontWeight: w700)`。第一阶段在生产 Theme 中明确：

- Brand：`displaySmall`，仅登录品牌标题等极少数位置
- Page title：`headlineSmall`，w700
- Section title：`titleMedium`，w700
- Primary body：`bodyLarge`
- Secondary body：`bodyMedium` + `onSurfaceVariant`
- Metadata / Evidence auxiliary：`bodySmall`
- Button / Chip：`labelLarge`

中文字体仍使用平台默认产品字体；PR #13 的仓库固定 CJK 字体只属于 Golden 测试，不进入生产 bundle。

## 4. 组件与文件边界

为避免把一个小型 App 过度抽象成几十个微组件，第一阶段只建立三个设计系统文件：

```text
mobile/lib/ui/jiyi_tokens.dart
mobile/lib/ui/jiyi_theme.dart
mobile/lib/ui/jiyi_components.dart
```

其中：

- `jiyi_tokens.dart`：spacing/radius/语义颜色 extension；禁止放业务规则。
- `jiyi_theme.dart`：生产 Theme 单一事实源，统一 Input/Button/Card/Dialog/NavigationBar/Chip。
- `jiyi_components.dart`：只放真正跨页面重复的 `JiYiPageFrame`、`JiYiSectionCard`、`JiYiStatusBanner`、`JiYiEmptyState`、`JiYiEvidenceCard`。
- TextField/Button/Dialog 优先通过 Theme 统一，不为“组件化”再包一层无价值 wrapper。

## 5. 状态视觉矩阵

| 状态 | 统一表现 | 不能发生的事 |
| --- | --- | --- |
| Loading | 页面级 spinner 或按钮内短 loading；保留当前真实禁用逻辑 | 不能显示假数据占位为“成功” |
| Success | success banner + 简短产品文案 | 不展示无产品价值的 DB/API 内部 ID |
| Error | error banner；有可恢复动作时提供重试/返回 | 不能吞掉服务端错误或降级成假成功 |
| Empty | icon + 标题 + 解释 + 可选下一步动作 | 不把“功能尚未实现”伪装成真实空数据 |
| Offline pending | info/warning banner，明确“已保存在本机”的事实 | 在 S1-017 完成前不能暗示已经自动同步 |
| Evidence | 摘要 + source + type + time + confidence 分层 | 不能隐藏 Evidence 或弱化 `NO EVIDENCE -> NO MEMORY` |
| Privacy paused | 明确 paused 状态、结束时间、恢复动作 | 不能把暂停期间自动数据说成仍在采集 |
| Destructive | error/destructive 颜色 + 二次确认 | 不能因改 UI 移除现有确认流程 |

## 6. Golden / Visual Regression 策略

1. 生产 Theme 改为唯一事实源；Golden 测试调用同一个 Theme builder，只用参数覆盖固定 CJK 测试字体。
2. Material Icons 固定字体继续只用于 Golden runner，不能进入生产 UI 依赖。
3. 普通 `mobile-visual-preview` 继续只验证 committed Golden，绝不自动 `--update-goldens`。
4. 每批页面改完后通过显式动作生成新 Golden，再人工打开五张核心页面确认。
5. intentional mismatch、artifact upload、dirty gate、Android APK、iOS no-codesign、standard mobile-ci 全部保留。
6. G 线至少保留登录、今天、记一下、问记忆、我的/隐私五张核心基线；如新增 error/paused 等状态 Golden，必须是确定性 fake API 输入，不能改业务组件来迎合测试。

## 7. 实施顺序

| 阶段 | 内容 | 业务语义 |
| --- | --- | --- |
| G0 | 本审查、token、组件边界、进度表 | 不变 |
| G1 | `JiYiTheme` / tokens / shared components；Golden 改为复用生产 Theme | 不变 |
| G2 | 登录/注册 + AppShell + Today/Timeline + PageFrame | 不变 |
| G3 | Capture 两组录入 + offline/status feedback | 不变 |
| G4 | Memory Query / Answer / Evidence / Delete visual hierarchy | 不变 |
| G5 | Profile / Privacy / loading/error/status | 不变 |
| G6 | 显式更新 Golden、人工检查 artifact、Android/iOS/standard CI、latest-main replay | 不变 |

## 8. 第一阶段验收清单

- [ ] `S1-027` 进度只允许 🔵 → 🟠 → ✅，未合并前不得标 ✅。
- [ ] 人工新增/修改的代码使用正常开发注释解释关键意图、约束和非显而易见的边界，不要求固定标签。
- [ ] Flutter analyze/tests PASS。
- [ ] Android debug APK PASS。
- [ ] iOS no-codesign PASS。
- [ ] 五张核心 Golden 显式更新并逐张人工确认。
- [ ] intentional mismatch / artifact / dirty gate PASS。
- [ ] UI diff 不包含 Backend/API/SQLite/media/Stage 2 代码。
- [ ] Evidence、隐私、错误状态在新 UI 中比当前更清楚，不能被美化隐藏。
- [ ] latest-main clean replay 后再次验证最终 SHA。
- [ ] 正式审查 + 合并 main 后才把 `S1-027` 标 ✅。
