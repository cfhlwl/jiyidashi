# JiYi Product Experience V2

> Issue #177  
> Branch: `feat/product-experience-v2-20260929`  
> Initial baseline: `7c7fe0e680c95892ebfd1cc321851026dfc0568e`  
> #163 / PR #176 is merged. This branch has been clean-replayed onto the current implementation baseline and is now the active UI/UX line.

## Product position

迹忆必须成为：

> **安静、温暖、可信、能够长期陪伴用户的私人记忆空间。**

它不是后台管理系统、数据库浏览器、CRUD 工具或 AI 技术演示。

核心体验：
1. 记录生活；
2. 回看生活；
3. 理解生活；
4. 珍藏生活。

## Approved visual direction

采用已确认参考稿体现的方向作为 Product Experience V2 主基线：

- 晨曦 / 夕阳 / 山水 / 湖面等时间意象；
- 大面积留白；
- 柔和浅色 surface；
- 大标题和编辑式排版；
- 照片优先；
- 柔和圆角卡片；
- 轻量 frosted / translucent hierarchy（只在可读性和性能允许时）；
- 蓝色主交互色；
- 家庭 / 地点 / 照片 / 提醒可有辅助语义色；
- 消费级 App 质感，而不是 SaaS dashboard。

禁止：
- 一页堆满功能卡；
- 默认 Material / 微信组件裸用；
- 每页自己发明颜色和 Badge；
- 技术术语直接进 UI；
- 为了效果图伪造统计或用户事实。

## Final IA

首选一级导航：

```text
今天
记忆
人生
家庭
我的
```

“记一下”是全局主动作，不必须占 Tab。

### 今天

```text
问候 / 日期 / 轻品牌氛围
→ 今日足迹
→ 今日记忆
→ 快速记录
→ 授权范围内的家庭动态
```

只显示有真实 authority 的数据。步数、天气、家庭互动数、心情百分比等没有 authority 时禁止展示。

### 记忆

承载：
- 问记忆；
- 最近记忆；
- 搜索；
- 照片；
- 重要的人；
- 相关的人和事；
- AI 帮助整理。

普通 deterministic query 不能整体包装成 AI。

### 人生

```text
我的人生
→ 人生时间线
→ 人生阶段
→ 重要经历
→ 年度回顾
→ 人生故事
```

首先讲故事，其次才是 CRUD。

### 家庭

承载已存在的 Stage 4 exact-grant 能力：成员、记忆、照片、位置授权、提醒、紧急位置共享。

### 我的

资料、隐私与记录、导出、家庭管理、帮助、账号安全、后续 entitlement。

未实现 backend authority 的“回收站 / 收藏 / 云恢复”不得仅凭设计稿上线。

## Flagship screens

必须正式重做并审查：

1. 今天；
2. 帮我记一下；
3. 问记忆；
4. 时间线；
5. 记忆详情；
6. 重要的人；
7. 人物详情；
8. 记忆关联；
9. 我的人生；
10. 人生经历；
11. 人生阶段；
12. 年度回顾；
13. 人生故事；
14. 家庭；
15. 家庭成员/权限；
16. 我的；
17. 隐私与记录控制；
18. 日/月/年回忆总结；
19. Empty / Loading / Error / Offline / Retry；
20. 代表性 Elder Mode 页面。

## Today

首页是“今天发生了什么”，不是功能目录。

推荐：
- 今日足迹作为主要生活内容；
- 今日记忆用照片/故事卡；
- 快速记录保持少而清楚；
- 家庭动态必须有授权和真实数据。

## Timeline

采用纵向 life stream：

```text
时间
标题
照片
地点
人物
可理解的主题/标签
摘要
```

禁止用户侧出现 retained Visit、confidence、source_type、cursor、UUID。

## Memory Detail

推荐：

```text
Hero media
标题
日期 / 时间 / 地点 / 人物
正文
照片
相关主题
位置摘要
相关的人与经历
合法的编辑 / 分享等动作
```

禁止 memory_id、edit_revision、raw trust enum、citation slot、provider provenance。

## Unified Capture / 帮我记一下

三类主要入口：

```text
语音
文字
照片
```

语音路径：

```text
录音
→ 转写
→ AI 帮你整理
→ 用户核对时间 / 地点 / 人物 / 摘要
→ 确认保存
```

AI 只能提出候选，不得静默升级成 confirmed fact。

## Query / 问记忆

用户语言优先：

```text
从我的记录里找
根据你的记录找到
相关记录
没有找到足够记录
```

只有真实生成式内容显示 SEC-013 AI disclosure。

## People

People Center → **重要的人**

Person Memory Timeline → **关于 TA 的记忆**

Person Relationships → **你们的关系**

人物详情优先：
- 头像/名字/别名；
- 关系；
- 认识多久；
- 相关记忆；
- 最近互动；
- authority 允许时的一起去过的地方/经历/相关的人。

## Graph

Unified Graph 不作为用户术语。

推荐：
- 记忆关联；
- 相关的人和事；
- 和这段记忆有关。

可视化图必须有可读列表替代，不要求用户理解 node/edge。

## Life / Memoir

LifeEvent 产品层可称：
- 人生经历；
- 重要经历。

LifeStage → 人生阶段。

Annual Memoir → 年度回顾。

Life Memoir → 人生故事 / 人生回忆录。

生成内容必须显示短而清楚的 AI disclosure，并把引用显示成“参考记录”。

## Family

可采用头像群组、权限卡片、家庭相关记录的视觉方式，但绝不突破 exact-grant。

产品用语：

```text
可查看我的记忆
可查看我的照片
位置需要单独授权
```

禁止 raw permission enum。

## AI presentation

内部状态：

```text
EXPLICIT
INFERRED
UNCERTAIN
UNAVAILABLE
```

用户层：

```text
EXPLICIT     → 明确记录 / 你记录的
INFERRED     → AI 整理 · 基于你的记录
UNCERTAIN    → 依据还不充分
UNAVAILABLE  → 暂时无法整理
```

不得用户侧显示：
ANSWERED、PROVIDER_FAILED、INVALID_CITATION、MALFORMED_PROVIDER_OUTPUT、EVIDENCE_CHANGED_DURING_GENERATION、CONFIRMED、EVIDENCE_SUPPORTED、INFERENCE_ONLY、NO_EVIDENCE。

## Reference-only features not yet authorized

参考稿中以下内容不得直接照搬上线：
- 情绪百分比；
- “最开心的一天”作为确定事实；
- 家庭互动次数；
- 步数/健康指标；
- 天气历史；
- 回收站恢复；
- 未实现收藏；
- 社交 feed。

如需要，另开 backend authority issue。

## Cross-client parity

Flutter 与 Mini 不要求逐像素一致，但必须统一：
- 名称；
- 信息层级；
- 色彩语义；
- typography hierarchy；
- spacing/radius scale；
- AI/trust presentation；
- Empty/Error/Loading；
- destructive copy；
- 核心交互顺序。

## Implementation order

```text
#163 继续开发，不停止
→ #163 合并
→ #177 clean replay 到 latest main
→ 保留 #163 parser / stale authority / tests
→ Flutter + Mini UI 实装
→ 分批 visual review
→ exact-head CI
→ final product review
```

## Definition of done

旗舰页必须同时满足：
- 清楚的信息层级；
- 现代消费级视觉；
- 无开发语言泄漏；
- 统一组件；
- 小屏通过；
- 大字通过；
- loading/error/empty/offline 完整；
- accessibility；
- 真实数据 authority；
- screenshot/golden 证据；
- formal product review PASS。
