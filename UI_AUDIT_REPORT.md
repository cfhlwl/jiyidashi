# 迹忆 App 三端前端 UI 审查与重构评估报告

> 审查范围：Flutter（iOS + Android）、微信小程序（Taro）
> 审查基线：当前分支 `trae/agent-P38FIV`（与 `chore/software-copyright-annotation-gate` 同一提交 `9b94201`）
> 审查日期：2026-09-25
> 参考文档：`docs/STAGE1_G_UI_AUDIT.md`、`docs/PRD-V1.md`、`docs/ARCHITECTURE.md`

---

## 0. 执行摘要

| 端 | 当前 UI 成熟度 | 是否需要重构 | 优先级 |
| --- | --- | --- | --- |
| Flutter（iOS/Android） | ★★★★☆ 设计系统已落地（Stage 1G） | **局部重构**（结构拆分 + 原生品牌化） | 中 |
| 微信小程序 | ★★☆☆☆ 无设计系统，样式散落 | **需要重构**（建立设计系统 + 组件库） | **高** |

**核心结论：**
- **Flutter 端**已经完成了 Stage 1G 设计系统改造（tokens / theme / components 三件套齐全），视觉一致性、状态反馈、Evidence 可信信息表达都达到产品级。**不需要推倒重来**，但存在一个明显的结构性债务：整个 App 的页面几乎都堆在单个 `stage1_app.dart`（>2200 行）中，应拆分为独立页面文件。此外原生层（启动屏、App 图标、App 名称）仍是 Flutter 默认模板，需要品牌化。
- **小程序端**明显落后于 Flutter：没有设计 tokens、没有组件库、颜色/圆角/间距全部硬编码在各页面 SCSS 中，状态反馈（成功/错误/空态/加载）只是带颜色的纯文本，Evidence 展示远弱于 Flutter。`STAGE1_G_UI_AUDIT.md` 第 10 行已明确「微信小程序后续独立同步视觉语言」——这一步尚未完成，**是本次重构的重点**。

---

## 1. Flutter（iOS / Android）端审查

### 1.1 设计系统现状（已完成）

项目已建立完整的设计系统三件套，位于 `mobile/lib/ui/`：

| 文件 | 职责 | 状态 |
| --- | --- | --- |
| [jiyi_tokens.dart](file:///workspace/mobile/lib/ui/jiyi_tokens.dart) | `JiYiSpacing`（4/8/12/16/20/24/32/40/48）、`JiYiRadius`（12/16/24）、`JiYiSemanticColors`（success/warning/info ThemeExtension） | ✅ 完整 |
| [jiyi_theme.dart](file:///workspace/mobile/lib/ui/jiyi_theme.dart) | `JiYiTheme.light()` 统一 InputDecoration / FilledButton / OutlinedButton / Card / NavigationBar / Dialog / Chip / Divider | ✅ 完整 |
| [jiyi_components.dart](file:///workspace/mobile/lib/ui/jiyi_components.dart) | `JiYiPageFrame`、`JiYiSectionCard`、`JiYiStatusBanner`、`JiYiEmptyState`、`JiYiEvidenceCard` | ✅ 完整 |

**品牌色：** seed `#446A57`（墨绿），背景 `#F7F8F6`（暖白灰），通过 `ColorScheme.fromSeed` 生成 Material 3 语义色。

**状态反馈矩阵（已统一）：**

| 状态 | 表现 |
| --- | --- |
| Loading | 按钮内 CircularProgressIndicator 或页面级 spinner |
| Success | `JiYiStatusBanner.success`，隐藏内部 UUID/ID |
| Error | `JiYiStatusBanner.error` + 重试按钮 |
| Empty | `JiYiEmptyState`（icon + 标题 + 解释 + 可选动作） |
| Offline pending | `JiYiStatusBanner.warning`，明确「已保存在本机」 |
| Evidence | `JiYiEvidenceCard`（摘要 + 来源/类型/时间/可信度分层） |
| Privacy | 明确 paused / active / stale 状态 banner + 人类可读时间 |
| Destructive | error 色按钮 + AlertDialog 二次确认 |

### 1.2 页面结构问题（核心债务）

**`mobile/lib/stage1_app.dart` 是一个 2200+ 行的巨型文件**，包含了：

- `JiYiApp` / `_JiYiAppState`（应用根）
- `AuthPage` / `_AuthPageState`（登录注册）
- `AppShell` / `_AppShellState`（底部导航 + 生命周期 + 离线同步 + 定位协调 + 账号注销编排）
- `TimelinePage` / `_TimelinePageState`
- `CapturePage` / `_CapturePageState`
- `MemoryQueryPage` / `_MemoryQueryPageState`
- `_MemoryEditDialog`
- `ProfilePage`
- `_PrivacyControls` / `_PrivacyControlsState`

只有 `TodayPage` 被拆到了独立的 [today_footprint_page.dart](file:///workspace/mobile/lib/today_footprint_page.dart)。

**风险：**
1. 单文件过大，合并冲突概率高，阅读和定位困难。
2. `AppShell` 同时承担导航、定位生命周期、离线同步、账号注销编排等多重职责，违反单一职责。
3. 页面之间共享私有类型（如 `_MemoryEditDraft`、`_captureStatusKind`），拆分时需注意可见性。

### 1.3 原生层品牌化缺失（iOS / Android）

| 项目 | iOS | Android | 问题 |
| --- | --- | --- | --- |
| 启动屏 | [LaunchScreen.storyboard](file:///workspace/mobile/ios/Runner/Base.lproj/LaunchScreen.storyboard) 居中一张默认 `LaunchImage`，背景白色 | [launch_background.xml](file:///workspace/mobile/android/app/src/main/res/drawable/launch_background.xml) 纯白色背景 | 均为 Flutter 默认模板，无品牌色、无品牌 logo、无 slogan |
| App 名称 | `CFBundleDisplayName = "Jiyidashi"` | `android:label = "jiyidashi"` | 未使用品牌名「迹忆」，且大小写不一致 |
| App 图标 | `AppIcon.appiconset` 多尺寸 | `mipmap-*/ic_launcher.png` | 需确认是否为品牌图标（当前为 Flutter 默认占位） |
| 深色模式 | 仅 `light()` theme，无 `darkTheme` / `themeMode` | 同左 | 不支持系统深色模式，夜间体验差 |
| 状态栏 | 未设置 `SystemUiOverlayStyle` | 未设置 `windowLightStatusBar` | 状态栏文字颜色可能与背景不协调 |

### 1.4 其他观察

- **字体：** [pubspec.yaml](file:///workspace/mobile/pubspec.yaml) 未声明自定义字体，使用系统默认中文字体。中文排版层级依赖 Material TextTheme 的 `displaySmall/headlineSmall/titleMedium`，在不同设备上字重表现可能有差异。
- **导航：** 使用 `setState` + `index` 管理底部导航，未使用命名路由；页面切换通过 `pages[index]` 直接替换，无转场动画。功能可用，但扩展性一般。
- **Golden 测试：** `test/goldens/` 已有 9 张基线图（auth_login、home_today、capture_media、memory_query、profile_privacy 等），`visual_golden_test.dart` 复用生产 Theme，视觉回归保护网健全。
- **无障碍：** 状态色始终配套文字/图标，不靠颜色单独表达状态，符合可访问性要求。

### 1.5 Flutter 端重构建议

| 优先级 | 项 | 说明 |
| --- | --- | --- |
| 高 | 拆分 `stage1_app.dart` | 按页面拆为 `auth_page.dart`、`timeline_page.dart`、`capture_page.dart`、`query_page.dart`、`profile_page.dart`，`AppShell` 提取为 `app_shell.dart` |
| 中 | 原生启动屏品牌化 | iOS LaunchScreen + Android launch_background 改为品牌色背景 + logo + slogan，与 Flutter 首屏无缝衔接 |
| 中 | App 名称统一为「迹忆」 | iOS `CFBundleDisplayName`、Android `android:label` |
| 中 | App 图标替换为品牌图标 | 替换默认 Flutter 占位图标 |
| 低 | 深色模式 | 实现 `JiYiTheme.dark()` + `JiYiSemanticColors.dark`，设置 `themeMode: ThemeMode.system` |
| 低 | 状态栏样式适配 | 根据主题设置 `SystemUiOverlayStyle` |

---

## 2. 微信小程序端审查

### 2.1 架构概览

- 框架：Taro + React + TypeScript（`.tsx`）
- 页面：`index`（今天）、`capture`（记一下）、`query`（问记忆）、`family`（家庭）、`profile`（我的）、`place-detail`（地点详情）
- 服务层：`services/api.ts`、`photoCapture.ts`、`voiceCapture.ts`、`placeDetail.ts`、`todayFootprint.ts`
- 全局样式：[app.scss](file:///workspace/miniprogram/src/app.scss)

### 2.2 核心问题：无设计系统

**小程序没有任何设计 tokens 或组件抽象。** 所有视觉值都是硬编码：

| 维度 | Flutter | 小程序 |
| --- | --- | --- |
| 颜色 | `ColorScheme.fromSeed` + 语义色 extension | 散落硬编码 hex：`#446a57`、`#f7f8f6`、`#1d2521`、`#68726c`、`#78817c`、`#dce3df`、`#eef1ef`、`#b3261e`、`#edf3ef`、`#294637`… |
| 间距 | `JiYiSpacing` token | 散落 rpx：`36rpx`、`30rpx`、`20rpx`、`18rpx`、`24rpx`、`22rpx`、`16rpx`、`12rpx`、`8rpx`、`6rpx`… |
| 圆角 | `JiYiRadius` token（12/16/24） | 散落：`24rpx`、`18rpx`、`16rpx`、`14rpx`、`999rpx`… |
| 卡片 | `JiYiSectionCard` 组件 | 每个页面手写 `.card` class，结构重复 |
| 按钮 | Theme 统一 FilledButton/OutlinedButton | 每个页面手写 `.primary-button` / `.secondary-button`，无统一组件 |
| 状态反馈 | `JiYiStatusBanner`（icon + 标题 + 消息） | 纯文本 + 颜色 class（`.status` / `.error`），无图标、无结构化容器 |
| 空态 | `JiYiEmptyState`（icon + 标题 + 解释） | 无组件，直接写文案 |
| Evidence | `JiYiEvidenceCard`（摘要 + 来源/类型/时间/可信度 chip） | 纯文本逐行展示，无分层、无 chip |

### 2.3 逐页问题

#### 今天（index）
- 足迹列表和地点列表用 `.card` + 手写 `.footprint-row` / `.place-row`，无统一列表项组件。
- 错误状态只是 `<View className='error'>` + 一个 secondary-button 重试，无图标、无错误容器。
- 底部有一张「V1 基础能力」说明卡，与 Flutter TodayPage 的产品化欢迎卡相比显得像开发占位。

#### 记一下（capture）
- 页面功能最完整（文字/图片/语音/物品位置），但 UI 全靠手写 class。
- 状态反馈：成功是绿色文字 `✓ ...`，错误是红色文字，无 banner 容器。
- 图片/语音上传阶段用 `.capture-state` pill（这部分做得相对好），但颜色仍是硬编码。
- 录音按钮 `.recording-button` 硬编码 `#8a3a32`。

#### 问记忆（query）
- **Evidence 展示明显弱于 Flutter：** 直接用 `<Text>` 和 `<View className='muted'>` 逐行拼 `来源/类型/时间/可信度`，没有分层、没有 chip、没有卡片容器。
- 答案、certainty、intent 直接堆在卡片标题和 muted 文本里，信息层级不清。
- 删除按钮是普通 secondary-button，无危险色区分。

#### 我的（profile）
- 隐私暂停状态只是一句 muted 文本 `自动记录已暂停，直到 ...`，**没有像 Flutter 那样的状态 banner**。
- 四个暂停时长按钮和恢复按钮视觉同级，主次不分。
- 加载态只是按钮文字变化。
- 错误只是 `.status` 文本。

#### 家庭（family）
- **纯占位页面**，只有一张「V1 基础能力」卡片，无任何功能。

### 2.4 与 Flutter 的功能/导航差异

| 维度 | Flutter | 小程序 |
| --- | --- | --- |
| 底部导航 | 今天 / 时间轴 / 记一下 / 问记忆 / 我的 | 今天 / 记一下 / 问记忆 / 家庭 / 我的 |
| 时间轴页 | ✅ 有 | ❌ 无 |
| 家庭页 | ❌ 无 | ⚠️ 占位 stub |
| 提醒管理 | ✅ ReminderPage | ❌ 无 |
| 新手引导 | ✅ OnboardingFlow | ❌ 无 |
| 账号注销 | ✅ AccountDeleteSection | ❌ 无 |
| 原生定位控制 | ✅ NativeLocationSection | N/A |
| Evidence 可信展示 | ✅ EvidenceCard 分层 | ❌ 纯文本 |
| 离线队列 | ✅ SQLite outbox | ❌ 无（在线为主） |

### 2.5 小程序端重构建议

**优先级：高。建议建立与 Flutter 对齐的设计系统。**

| 优先级 | 项 | 说明 |
| --- | --- | --- |
| **高** | 建立设计 tokens | 新建 `src/styles/tokens.scss`（或 CSS 变量），统一颜色/间距/圆角/字号，替换所有硬编码 |
| **高** | 建立基础组件库 | 新建 `src/components/`：`JiYiCard`、`JiYiButton`（primary/secondary/destructive）、`JiYiStatusBanner`、`JiYiEmptyState`、`JiYiEvidenceCard`、`JiYiField` |
| **高** | 对齐状态反馈 | 成功/错误/警告/空态全部改用 `JiYiStatusBanner` / `JiYiEmptyState`，不再用裸文本 |
| **高** | 强化 Evidence 展示 | query 页改用 `JiYiEvidenceCard`，与 Flutter 信息层级对齐 |
| 中 | 隐私控制状态化 | profile 页隐私区增加状态 banner（active/paused/unknown），对齐 Flutter |
| 中 | 统一列表项组件 | index 页足迹/地点列表提取 `JiYiListRow` |
| 中 | tabBar 配置图标 | 当前 tabBar 只有文字无图标，补充 icon + selectedIcon |
| 低 | family 页产品化 | 要么实现家庭共享功能，要么明确标注「即将开放」并使用 EmptyState |
| 低 | 深色模式 | tokens 支持 `prefers-color-scheme` |

---

## 3. 跨端一致性评估

### 3.1 视觉语言

- **品牌色一致：** 两端都使用 `#446A57` / `#F7F8F6`，但小程序的实现是硬编码而非 token。
- **圆角/间距不一致：** Flutter 用 12/16/24 逻辑像素，小程序用 rpx 且数值不统一（24rpx/18rpx/16rpx 混用）。
- **组件形态不一致：** Flutter 有统一的 SectionCard（带 outline + radius + surface），小程序的 `.card` 只有白底圆角无边框。

### 3.2 信息架构

- 导航结构有分叉（Flutter 有时间轴无家庭；小程序有家庭无时间轴）。
- 建议统一信息架构，至少保证核心入口（今天/记一下/问记忆/我的）一致。

### 3.3 可信信息表达

- Flutter 的 EvidenceCard 是产品的核心差异化（「NO EVIDENCE → NO MEMORY」），小程序的 Evidence 展示严重弱化，**这是体验上的最大短板**，应优先对齐。

---

## 4. 重构路线图建议

### 阶段一：小程序设计系统落地（高优先，预计 1-2 周）

1. 建立 `src/styles/tokens.scss`（颜色/间距/圆角/字号/阴影）
2. 建立 `src/components/` 基础组件（Card / Button / StatusBanner / EmptyState / EvidenceCard / Field / ListRow）
3. 逐页迁移：index → capture → query → profile → family → place-detail
4. 替换所有硬编码颜色为 token 引用

### 阶段二：Flutter 结构拆分（中优先，预计 3-5 天）

1. 将 `stage1_app.dart` 按页面拆分到 `lib/pages/`
2. 提取 `AppShell` 到 `lib/app_shell.dart`
3. 保持所有业务逻辑、API 调用、状态机不变（纯结构重构）
4. 运行 golden tests 验证无视觉回归

### 阶段三：原生品牌化（中优先，预计 2-3 天）

1. iOS LaunchScreen：品牌色背景 + logo
2. Android launch_background：品牌色 + logo（支持 Adaptive Icon）
3. App 名称统一为「迹忆」
4. 替换 App 图标为品牌设计
5. 状态栏样式适配

### 阶段四：能力对齐与增强（低优先，按产品排期）

1. 小程序补齐时间轴页（或 Flutter 补齐家庭页），统一导航
2. 小程序实现提醒管理、新手引导
3. 两端深色模式
4. 自定义品牌字体（可选）

---

## 5. 风险与注意事项

1. **Evidence 可信链不能因重构弱化：** 小程序重构 EvidenceCard 时，必须保留 source_type / kind / occurred_at / confidence 全部字段，不能只展示摘要。
2. **隐私状态表达不能降级：** 对齐 Flutter 的 active/paused/stale/unknown 四态，不能用颜色单独表达。
3. **Flutter 拆分不改变行为：** 阶段二是纯文件结构重构，所有 `[人工注释]` 标注的业务边界、幂等键、生命周期约束必须原样保留。
4. **小程序离线能力暂不补齐：** 当前小程序以在线为主，重构不引入 SQLite outbox，避免范围蔓延。
5. **品牌资产依赖：** 启动屏、App 图标需要设计师提供品牌 logo 和图标资源，开发无法独立完成。

---

## 6. 验收标准

- [ ] 小程序所有颜色/间距/圆角均来自 tokens，无硬编码 hex
- [ ] 小程序所有页面使用统一组件（Card/Button/StatusBanner/EmptyState/EvidenceCard）
- [ ] 小程序 Evidence 展示层级与 Flutter 对齐
- [ ] Flutter `stage1_app.dart` 拆分为独立页面文件，单文件不超过 500 行
- [ ] Flutter golden tests 全部通过，无意外视觉回归
- [ ] iOS/Android 启动屏、App 名称、App 图标完成品牌化
- [ ] 两端核心页面（今天/记一下/问记忆/我的）视觉语言一致
