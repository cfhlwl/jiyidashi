# JiYi Design System V2

> Issue #177

## Objective

Flutter + WeChat Mini Program 共享一套可识别的迹忆视觉语言。

不允许最终产品看起来像“默认平台控件 + 页面级 CSS 拼装”。

## Brand

核心视觉隐喻：

```text
时间
记忆
晨昏
山水
暖光
照片
私人空间
```

主交互强调：平静、清晰的蓝色。

辅助语义：
- 绿色：成功/记录/媒体等正向状态；
- 橙色：地点/暖色 highlight；
- 紫色：人物/家庭/AI 辅助；
- 红色：危险/错误。

必须全部 token 化。

## Required token families

```text
color.brand.primary
color.brand.secondary
color.background
color.surface
color.surfaceElevated
color.surfaceSoft
color.text.primary
color.text.secondary
color.text.tertiary
color.border
color.divider
color.action.primary
color.action.secondary
color.success
color.warning
color.error
color.info
color.ai
color.family
color.location
color.media
```

Spacing 推荐统一到：

```text
4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48
```

Radius 只保留语义档：
- control；
- card；
- large-card；
- pill；
- sheet/dialog。

Typography：
- display；
- pageTitle；
- sectionTitle；
- cardTitle；
- body；
- bodySecondary；
- caption；
- button；
- badge。

## Surface hierarchy

只保留少量清楚层级：
1. app background；
2. primary content surface；
3. elevated/interactive surface；
4. sheet/dialog。

禁止无理由同时堆 border + shadow + blur + gradient。

## Required shared components

### Layout
- AppScaffold / PageFrame
- HeroHeader
- SectionHeader
- Section
- BottomNavigation

### Content
- MemoryCard
- PersonCard
- TimelineItem
- PhotoStoryCard
- StatItem
- ReferenceCard
- MediaGrid
- MapSummary

### Identity
- Avatar
- AvatarGroup
- Tag
- SemanticBadge
- AiDisclosure

### State
- LoadingState
- Skeleton
- EmptyState
- ErrorState
- OfflineState
- RetryState
- StatusBanner

### Actions
- PrimaryButton
- SecondaryButton
- TextButton
- DangerButton
- IconButton
- FloatingCaptureAction

### Navigation
- SegmentedTabs
- FilterTabs
- BottomSheet
- ConfirmDialog
- SearchField

### Forms
- ProductTextField
- Date/TimePickerRow
- PlacePickerRow
- PersonPickerRow
- MediaPicker

## Rules

- 视觉等价组件不得页面级重复实现；
- Mini 必须减少 raw magic colors/radius/spacing；
- Flutter 继续以 JiYiTheme 为单一事实源，并扩充 V2 semantic theme；
- 页面专属组件只有在拥有独特产品语义时才允许存在。

## Typography

- 中文优先；
- 大标题有编辑感但不能压迫；
- 长记忆正文要舒适行高；
- metadata 不得过小；
- Elder Mode 放大后保持层级而不是整体机械放大。

## Photos

- 照片是一等内容；
- 列表用缩略图；
- 稳定 aspect ratio；
- loading/placeholder 统一；
- 不用高分辨率原图充当列表 thumbnail；
- 生产数据必须来自真实用户媒体。

## Icons

- 每个平台一个统一 icon family；
- 重要动作 icon + 文案；
- 禁止仅靠 emoji；
- 单色/无色环境仍可理解。

## Motion

只使用克制动画：
- page transition；
- card expansion；
- capture feedback；
- loading；
- success acknowledgement。

禁止持续装饰性动画。

## Navigation

首选：

```text
今天
记忆
人生
家庭
我的
```

active 状态不能只靠颜色。

## AI visual language

AI 是辅助能力，不是整个品牌。

真实生成内容可使用：
- 轻量 AI icon；
- “AI 整理”；
- “基于你的记录”。

确定性页面禁止被统一染成 AI 风格。

## Accessibility

至少：
- 合理 touch target；
- semantic labels；
- 状态不只靠颜色；
- dynamic text；
- large font；
- Elder Mode larger targets；
- 合理 contrast；
- focus order。

## Fidelity requirement

正式视觉 review 必须对照已批准参考方向检查：
- spacing rhythm；
- hierarchy；
- photo prominence；
- card geometry；
- header treatment；
- navigation clarity；
- density；
- calmness；
- default-widget leakage。

目标不是机械复制效果图像素，而是使用真实业务语义达到**同等级或更高的产品完成度**。
