# JiYi Product Language V2

> Issue #177

## Principle

代码可以讲模型，界面必须讲人话。

用户文案只回答：
1. 发生了什么；
2. 这对我意味着什么；
3. 接下来可以做什么。

## Product promise

推荐的简洁承诺：

> **自动记录生活，需要时帮你找回来。**

需要解释机制时使用：

> 完成授权后尽可能自动记录。记录效果受系统权限、后台策略、网络和设备状态影响；可以在“记录状态”中查看最近记录、同步和已知空档。

品牌文案“你负责生活，我帮你记住。”可以保留，但不得作为“永不漏记”的技术保证。

禁止当前产品文案使用：

```text
个人 AI 第二记忆
AI 记住你的一切
100% 自动记录
永远不会漏记
完全不用打开 App
后台始终运行
全天持续记录
所有去过的地方都会被记录
```

AI 的推荐表达是“AI 帮你整理 / 回顾 / 总结”，必须建立在用户真实记录上；AI 不得被描述成个人事实来源。

## Forbidden user-visible vocabulary

非诊断/开发界面禁止直接展示：

```text
Memory
Evidence
Visit
retained Visit
Graph
LifeEvent
LifeStage
provider
provenance
citation
slot
cursor
revision
memory_id
life_stage_id
life_event_id
trust_state
source_type
server
backend
API
UUID
enum
```

## Canonical translations

| Internal | User-facing |
| --- | --- |
| Memory | 记忆 / 回忆 / 记录 |
| Memory evidence | 相关记忆 / 参考记录 / 依据 |
| Evidence | 参考记录 / 依据 |
| Visit | 到访 / 足迹 |
| retained Visit | 到访记录 |
| People Center | 重要的人 |
| Person Memory Timeline | 关于 TA 的记忆 |
| Person Relationships | 你们的关系 |
| Unified Graph | 记忆关联 / 相关的人和事 |
| LifeEvent | 人生经历 / 重要经历 |
| LifeStage | 人生阶段 |
| Known Duration | 认识多久 |
| Long-term Reasoning | 回顾这段时光 / AI 帮你整理 |
| Cross-year History | 人生时间线 / 多年回顾 |
| Annual Summary | 年度回顾 |
| Annual Memoir | 年度回顾 |
| Life Memoir | 人生故事 / 人生回忆录 |
| Citation | 参考记录 |
| CONFIRMED | 已确认（仅确有用户价值时） |
| EVIDENCE_SUPPORTED | 有记录支持 |
| INFERRED | AI 整理 · 基于你的记录 |
| UNCERTAIN | 依据还不充分 |
| UNAVAILABLE | 暂时无法整理 |

## Required rewrites

当前：
> 创建、编辑、删除，并关联真实 Memory 证据。

目标：
> 整理重要经历，并添加相关记忆。

当前：
> Memory 证据

目标：
> 相关记忆

当前：
> 这是服务端确定性投影，不是 AI 推断。游标按原值续传。

目标：
> 从 UI 删除。若确有说明价值，仅写“根据你的记录整理”。

当前：
> 证据槽位 M-003

目标：
> 不显示 slot，只显示“参考记录”+ 可理解日期/标题。

当前：
> 可信状态：confirmed

目标：
> 已确认

当前：
> 原始 Evidence 与编辑记录均已保留

目标：
> 已保存修改，原来的记录仍会保留。

当前：
> 没有可展示的 Evidence

目标：
> 暂时没有找到可参考的记录。

当前：
> 服务端返回的记忆版本不正确，请重新查询后再试

目标：
> 这条记忆刚刚发生了变化，请重新打开后再试。

PROVIDER_FAILED：
> 这次没有整理成功，可以稍后再试。

INVALID_CITATION：
> 这次整理的依据不够可靠，因此没有显示结果。

EVIDENCE_CHANGED_DURING_GENERATION：
> 整理过程中相关记录发生了变化，请重新生成。

## AI disclosure

推荐：

```text
AI 整理
基于你的记录
```

或：

```text
AI 帮你回顾
参考了 5 条记录
```

禁止：
- AI可信状态：INFERRED；
- provider provenance；
- model；
- citation slot。

## Empty states

避免：
> 无数据

使用：
> 这里还没有记忆  
> 记下第一件想留住的事吧。

避免：
> NO_ANSWERABLE_EVIDENCE

使用：
> 还没有足够的记录来整理这段回忆。

## Error states

网络：
> 网络有点慢，稍后再试一次。

登录：
> 登录状态已失效，请重新登录。

冲突：
> 内容刚刚发生了变化，请重新打开后再试。

权限：
> 你还没有权限查看这部分内容。

AI unavailable：
> 这次没有整理成功，可以稍后再试。

trust fail-closed：
> 依据还不够可靠，因此没有显示结果。

## Tone

必须：
- 克制；
- 温和；
- 清楚；
- 尊重用户；
- 不夸大 AI；
- 不制造确定性。

避免：
- 儿童化；
- 过度煽情；
- 过多感叹号；
- 技术炫耀；
- gamification。
