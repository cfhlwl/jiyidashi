<!-- [人工注释][DOC-PROGRESS-001] 本文件是迹忆项目长期维护的唯一开发进度总表；每次功能开发、修复、审查或合并后都必须同步更新状态。 -->
<!-- [人工注释][DOC-PROGRESS-025] PR #9 已完成 latest-main clean replay、最终 Mini Program CI 与 replay-after-clean 核验，并合并 main=9722635f；C 工作线第一阶段正式完成，S1-005 转 ✅，S1-004 继续保持进行中，真实音频上传/ASR/Evidence 留待 S1-007。 -->
<!-- [人工注释][DOC-PROGRESS-026] D1/PR #12 与 D2/PR #13 已分别完成正式审查、latest-main replay 与最终 CI 并合并；PR #13 先合并为 main=3b43574a，PR #12 随后 clean replay 到该 main 并合并为 main=f1d9baef。Issue #10/#11 已自动关闭。 -->
<!-- [人工注释][DOC-PROGRESS-027] Stage 1 第三批 A/B/C/D 第一阶段全部完成；Stage 1 本身仍未完成，下一阶段继续 S1-004/S1-007、S1-017、S1-008、S1-018、S1-021、S1-022、S1-025、S1-026；Stage 2 继续明确未开始。 -->
<!-- [人工注释][DOC-PROGRESS-028] Stage 1G / Issue #16 Product UI & Design System 已基于 main=677b6ce9 启动；第一阶段先冻结 Flutter UI 审查清单、design token 与组件边界，S1-027 标 🔵，Stage 2 继续未启动。 -->
<!-- [人工注释][DOC-PROGRESS-029] Stage 1G Flutter 第一阶段已完成 G1~G6：生产 Theme/token/共享组件、5 个核心页面产品化、Evidence/隐私/离线状态视觉、Golden 显式重基线、完整 CJK/MaterialIcons 确定性字体门禁及 Android/iOS 最终验收均通过；S1-027 转 🟠，等待正式 UI 审查与合并，Stage 2 继续未启动。 -->
# 迹忆开发进度总表

> 最后更新：2026-09-17  
> 当前阶段：Stage 1「记得住」继续推进；第三批 A/B/C/D 第一阶段已全部完成并合并，下一步进入 Stage 1 第二阶段收口；Stage 2 未开始  
> 当前生产代码基线：`main=f1d9baefd88a43c3da27378b5d87664221edf527`（PR #12 合并后；本文件随后仅产生 docs-only 更新）  
> 当前开发重点：`S1-027` G 线 Product UI / Design System 已启动；功能侧仍优先 `S1-004 + S1-007` 语音/ASR 与 `S1-017` 离线自动同步/服务端幂等，之后进入 `S1-008` 统一入口及数据删除/注销等收口任务

## 状态规则

| 标记 | 状态 | 使用规则 |
| --- | --- | --- |
| 🔵 | 进行中 | 正在开发、修复或执行验收 |
| 🟠 | 待审查 / 待合并 | 代码已实现并通过当前自动测试，但尚未完成正式审查或尚未合并 `main` |
| ✅ | 已完成 | 已合并 `main`，并完成对应验收 |
| ⬜ | 未开始 | 尚未进入开发 |
| ⏸ | 延后 | 已确认需要，但当前阶段暂缓 |
| 🚫 | 当前版本不做 | 明确不进入当前版本范围 |

> **完成定义：** 只有“代码完成 + 自动测试通过 + 正式审查通过 + 合并 main + 必要验收完成”后，才能标记为 ✅。

---

## 0. 当前总览

| ID | 模块 | 当前状态 | 说明 |
| --- | --- | --- | --- |
| FND-000 | V1 Foundation 总体 | ✅ | PR #1 已通过最终复核并合并 `main` |
| S1-M1 | Stage 1 第一批“记录 → 找回 → 相信”闭环 | ✅ | PR #2 已通过第二轮正式复审并合并 `main` |
| S1-M2 | Stage 1 第二批“纠错 → 删除 → 暂停/恢复” | ✅ | PR #3 已通过三轮正式审查并合并；最终 HEAD 三端 CI 全部 SUCCESS |
| S1-M3 | Stage 1 第三批“多媒体记录 + 离线 + 数据控制” | 🔵 | A/B/C/D 第一阶段均已合并；语音完整链、离线自动同步/幂等及后续 Stage 1 收口任务仍未完成，因此本阶段整体继续进行中 |
| CI-001 | Backend CI | ✅ | A/D1 均通过 Ruff、SQLite/PostgreSQL migration、`alembic check`、ObjectLocation invariants 与 full pytest；PR #12 replay CI `35203341989` SUCCESS |
| CI-002 | Flutter Android CI | ✅ | 标准 Android analyze/tests/APK 持续通过；PR #13 最终标准 Mobile CI `35201294079` SUCCESS |
| CI-003 | Flutter iOS CI | ✅ | iOS no-codesign 持续通过；PR #13 最终标准 Mobile CI `35201294079` SUCCESS |
| CI-004 | 微信小程序 CI | ✅ | PR #9 clean HEAD `5f8ac339` 的标准 Mini Program CI `35176991792` SUCCESS，并已合并 |
| CI-005 | UI Visual Preview / Golden Screenshot | ✅ | PR #13 已合并；固定 CJK + MaterialIcons、Golden mismatch 证明、视觉 artifact、dirty gate、Android/iOS 门禁均通过 |

---

# 1. Foundation：可信记忆与工程基础

| ID | 功能 / 需求 | 状态 | 验收要求 / 当前说明 |
| --- | --- | --- | --- |
| FND-001 | FastAPI 模块化单体基础工程 | ✅ | PR #1 合并 main |
| FND-002 | PostgreSQL / SQLite 开发数据库基础 | ✅ | PostgreSQL 已进入正式 CI |
| FND-003 | Redis 开发依赖基础 | ✅ | Docker 开发环境已配置 |
| FND-004 | Alembic migration baseline | ✅ | SQLite / PostgreSQL 均执行 `upgrade head` |
| FND-005 | Memory 核心模型 | ✅ | Memory 为长期记忆主对象 |
| FND-006 | MemorySource / Evidence 模型 | ✅ | 查询事实必须验证 Evidence |
| FND-007 | `NO EVIDENCE -> NO MEMORY` 强制规则 | ✅ | 服务端 Evidence gate 强制执行 |
| FND-008 | AI inference 与事实隔离 | ✅ | AI 推断不得直接成为 confirmed fact |
| FND-009 | 服务端可信等级所有权 | ✅ | 客户端不能提交 confidence / confirmed 权限 |
| FND-010 | Object / ObjectLocation 历史模型 | ✅ | 保留历史，不覆盖旧记录 |
| FND-011 | 每个 Object 最多一个 CURRENT | ✅ | 应用事务 + DB partial unique index；PostgreSQL 实库验收 PASS |
| FND-012 | 离线旧位置晚到防回滚 | ✅ | 根据 `recorded_at` 决定 CURRENT / STALE；失效水位边界已回归 |
| FND-013 | 删除 Memory 与 ObjectLocation 联动失效 | ✅ | 删除后不得继续从对象位置查询回答 |
| FND-014 | Location `client_uuid` 幂等 | ✅ | 离线重传不得产生重复位置点 |
| FND-015 | 隐私暂停服务端最终门禁 | ✅ | 暂停期间自动数据不得入库 |
| FND-016 | 隐私暂停历史区间 | ✅ | 恢复后补传暂停期间 GPS 仍拒绝 |
| FND-017 | 用户时区自然日边界 | ✅ | timeline / summary 使用用户 timezone |
| FND-018 | 中文基础记忆查询 | ✅ | 无空格中文查询有正向回归 |
| FND-019 | Dev Auth fail-closed | ✅ | production/prod 无条件硬关闭 |
| FND-020 | Flutter Android/iOS 标准工程 | ✅ | Android/iOS 真实构建 PASS |
| FND-021 | Taro 微信小程序标准工程 | ✅ | production WeChat build PASS |
| FND-022 | 三端 CI 基线 | ✅ | backend / mobile / miniprogram 均真实验收 |
| FND-023 | Location 时间戳时区健壮性 | ✅ | 拒绝 naive datetime |
| FND-024 | PostgreSQL ObjectLocation 真实数据库不变量 | ✅ | migration、单 CURRENT、`FOR UPDATE` 均 CI 验证 |
| FND-025 | 正式 API 文档协议同步 | ✅ | `capture_source` / Evidence / timezone 协议对齐 |
| FND-026 | ObjectLocation 显式时间戳时区约束 | ✅ | naive `recorded_at` 422 且 CURRENT 不变 |

---

# 2. Stage 1：记得住

目标：完成“记录 → 保存 → 找到 → 相信 → 纠错/删除/暂停”的 V1 主闭环，并把主动文字/图片/语音、离线恢复和用户数据控制做成日常可用能力。

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S1-001 | 正式用户注册 / 登录 | ✅ | Argon2、限速/退避、dummy verify、migration drift gate 已通过复审 |
| S1-002 | 用户资料与时区设置 | ✅ | trim-before-validation、IANA timezone |
| S1-003 | 文字记忆录入 | ✅ | Flutter / 小程序接真实 Memory API，仅声明 `USER_TEXT` |
| S1-004 | 语音记忆录入 | 🔵 | PR #9 已完成小程序录音 UI、权限和 Recorder session ownership；真实音频上传、ASR、Evidence 尚未实现 |
| S1-005 | 图片记忆录入 | ✅ | PR #7 后端媒体/Evidence + PR #9 小程序真实拍照/选图上传链均已审查、CI、clean replay 并合并 |
| S1-006 | COS / OSS 对象存储直传 | ✅ | 私有 staging→final、短时签名、owner gate、图片签名验证与 commit-safe staging 清理已落地 |
| S1-007 | ASR 语音转写 | ⬜ | 下一阶段优先；原始音频必须保留为 Evidence，禁止假转写 |
| S1-008 | “帮我记住”统一入口 | ⬜ | 待 `S1-005 + S1-007` 协议稳定后，统一文字 / 语音 / 图片 Memory Pipeline |
| S1-009 | “东西在哪”物品录入 | ✅ | Object create 并发竞争已幂等兜底 |
| S1-010 | “东西在哪”查询 | ✅ | 返回真实 Evidence `source_type` / `memory_source_id` |
| S1-011 | 物品位置失效 / “已经不在那里” | ✅ | 唯一最具体 Object、UNKNOWN 失效水位、锁与重叠名称回归均通过 |
| S1-012 | 基础记忆搜索 | ✅ | 普通 Memory Evidence 返回真实来源且不降低 gate |
| S1-013 | “问记忆”客户端页面接真实 API | ✅ | Flutter / 小程序已接真实 API |
| S1-014 | 答案展示 Evidence / 来源 / 时间 | ✅ | 客户端展示来源、证据类型、时间、可信度 |
| S1-015 | 客户端本地 SQLite | ✅ | PR #6 已合并；版本化 SQLite、账号隔离、重启恢复完成 |
| S1-016 | 离线记忆队列 | ✅ | PR #6 已合并；状态机、稳定 UUID、取消/重试、仅 TransportException fallback 均通过正式审查 |
| S1-017 | 离线同步与幂等 | ⬜ | 下一阶段优先；服务端 `client_uuid` 幂等必须覆盖 response-loss / unknown-commit 后再允许自动重发 |
| S1-018 | 单条 Memory 编辑 | ⬜ | 编辑后 Evidence 与审计语义需明确 |
| S1-019 | 单条 Memory 删除 | ✅ | 服务端 DELETE、删除后查询失效及 ObjectLocation 联动均已合并 |
| S1-020 | 数据导出 | ✅ | PR #12 已合并；owner 隔离、JSON v1、媒体敏感字段保护、5000 上限/413、删除位置 tombstone 均通过正式审查 |
| S1-021 | 全部数据删除 | ⬜ | DB / Cache / Storage 一致删除；必须先于注销账号完成 |
| S1-022 | 注销账号 | ⬜ | 依赖 `S1-021` 全量删除闭环 |
| S1-023 | 暂停记忆 30 分钟 / 1 小时 / 3 小时 / 今天 | ✅ | 单一 reference timestamp + DST 时区回归通过 |
| S1-024 | 手动恢复记录 | ✅ | resume 保留 PrivacyPauseInterval 历史，延迟上传门禁通过 |
| S1-025 | 基础提醒模型 | ⬜ | 仅从记忆产生提醒，不做完整 Todo |
| S1-026 | 首次使用引导 | ⬜ | 待统一入口稳定后，目标 3 分钟内完成“记住 → 找回”Aha Moment |
| S1-027 | Product UI / Design System | 🟠 | PR #17 Flutter 第一阶段开发与自动验收完成；Theme/token/共享组件、5 个核心页面、Evidence/隐私/离线状态、Golden/CJK/MaterialIcons、Android/iOS 均已验证，等待正式 UI 审查与合并；Stage 2 未启动 |

## 2.1 Stage 1 第三批 A/B/C/D 第一阶段收口

| 工作线 | 范围 | PR / 最终结果 | 状态 |
| --- | --- | --- | --- |
| A：Backend Media | `S1-006` + `S1-005` 后端媒体/Evidence | PR #7 已合并；媒体协议 staging→final、签名、Evidence、图片验证与安全边界通过正式审查 | ✅ |
| B：Flutter Offline | `S1-015` + `S1-016` | PR #6 已合并；SQLite + 离线队列 + transport/protocol 分类通过正式审查 | ✅ |
| C：Mini Capture | `S1-005` 小程序主动图片 + `S1-004` 录音 UI/权限壳 | PR #9 clean HEAD `5f8ac339`，标准 Mini Program CI `35176991792` SUCCESS；merge commit `9722635f` | ✅ 第一阶段 |
| D1：Data Export | `S1-020` | PR #12 在 PR #13 合并后的 main 上 clean replay 为 `8181127f`，Backend CI `35203341989` SUCCESS；merge commit `f1d9baef` | ✅ |
| D2：Visual Quality | `CI-005` | PR #13 最终 HEAD `3a9409d9`；Visual CI `35201294030` + Mobile CI `35201294079` SUCCESS；merge commit `3b43574a` | ✅ |

### 已关闭的关键审查问题

| ID | 级别 | 结果 |
| --- | --- | --- |
| S1-PR6-FIX-001 | P1 | catch-all 客户端异常误入 SQLite offline fallback；已改为仅 TransportException 可入队并随 PR #6 合并 |
| S1-PR7-FIX-001~005 | 3×P1 + 2×P2 | commit-safe staging、production HTTPS、真实图片校验、模型导入、公共 ETag 泄露均关闭并随 PR #7 合并 |
| S1-PR9-FIX-001 | P1 | Recorder session owner 固定，late start/stop/error 不再污染新页面；已关闭并随 PR #9 合并 |
| S1-PR9-FIX-002~004 | P2 | 图片预读、人工注释、微信真实 COS/OSS 合法域名验收说明均关闭 |
| S1-PR12-FIX-001 | P1 | deleted Memory 的 ObjectLocation 不再通过 export 泄露位置；改为 STALE redacted tombstone，已关闭 |
| CI-PR13-FIX-001 | P1 | Golden 固定 CJK 字体，中文不再为缺字方框 |
| CI-PR13-FIX-002 | P2 | worktree dirty gate 改为真正 fail-closed |
| CI-PR13-FIX-003 | P1 | Golden 显式加载固定 MaterialIcons，导航图标真实且互不相同 |

## 2.2 下一阶段推荐并行工作线

<!-- [人工注释][S1-PLAN-002] 以下是第三批第一阶段完成后的 Stage 1 收口顺序；这里只记录计划，不代表任务已开工。未创建分支/Issue 前状态继续保持 ⬜。 -->

| 优先级 | 工作线 | 对应任务 | 当前状态 | 说明 |
| --- | --- | --- | --- | --- |
| 1 | E：Voice Pipeline | `S1-004 + S1-007` | ⬜ | 音频上传、ASR、原始音频 Evidence、失败/重试语义；完成后才能把 S1-004 转 ✅ |
| 1 | F：Offline Sync | `S1-017` | ⬜ | 服务端幂等 + Flutter 自动 flush；必须覆盖服务端已提交但响应丢失的 unknown-commit 场景 |
| 1 | G：Product UI / Design System | 正式 UI 设计与组件规范 | 🟠 | Flutter 第一阶段已完成并等待正式 UI 审查/合并；微信小程序视觉同步仍属后续独立工作，Stage 2 未启动 |
| 2 | Unified Capture | `S1-008` | ⬜ | 等语音协议稳定后统一文字/图片/语音入口 |
| 2 | Memory Edit | `S1-018` | ⬜ | 独立 Backend/客户端 PR |
| 3 | Data Delete | `S1-021` | ⬜ | DB / Cache / Storage 全删除，明确对象存储删除和失败恢复语义 |
| 4 | Account Delete | `S1-022` | ⬜ | 必须建立在 S1-021 完整闭环之上 |
| 5 | Reminder | `S1-025` | ⬜ | 基础提醒，不扩展成 Todo 产品 |
| 6 | Onboarding | `S1-026` | ⬜ | 统一入口稳定后设计首次 Aha Moment |

### 硬规则

- 一个任务组一个独立分支、一个独立 PR；禁止大而全的 Stage 1 分支。
- 手工新增/修改的语义代码块继续使用 `[人工注释][TASK-ID]`。
- 公共 API/schema/Evidence 协议只允许一个 PR 定义，其他端只消费。
- 每个 PR 合并前都必须基于最新 `main` 做最终 replay / CI。
- `S1-021 → S1-022` 顺序不可反。
- Stage 2 后台定位、CoreLocation、Location Bridge、Visit clustering 等继续保持 ⬜，不得提前侵入 Stage 1 PR。

---

## 2.2 Stage 1 G：Product UI / Design System

| 工作线 | 范围 | 当前结果 | 状态 |
| --- | --- | --- | --- |
| G：Product UI / Design System | `S1-027`；Flutter 第一阶段 | PR #17；G1~G6 开发、Golden 重基线、最终视觉 artifact、Android/iOS 验收完成，等待正式 UI 审查与合并 | 🟠 |

# 3. Stage 2：自动记

> **当前明确未开始。继续完成 Stage 1 剩余能力后，再单独评审是否进入后台定位。**

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S2-001 | Android 原生后台定位模块 | ⬜ | 低功耗、权限分阶段申请 |
| S2-002 | iOS CoreLocation 后台定位模块 | ⬜ | 适配系统后台限制 |
| S2-003 | Flutter 统一 Location Bridge | ⬜ | `start / stop / pause / status` |
| S2-004 | 运动状态识别 | ⬜ | 静止 / 移动状态切换 |
| S2-005 | 智能定位采样策略 | ⬜ | 不允许固定 5 秒高频上传 |
| S2-006 | Location Point 批量同步 | ⬜ | 后端入口已有 foundation，客户端未接 |
| S2-007 | Visit 聚类 | ⬜ | 从原始位置点生成停留事件 |
| S2-008 | Place 模型与地点库 | ⬜ | 名称、地址、类别、访问次数 |
| S2-009 | Place 自动命名 | ⬜ | 地图 POI / 地址解析 |
| S2-010 | Place 用户纠正 | ⬜ | 用户可纠正“家 / 公司 / 医院”等 |
| S2-011 | 自动时间轴 | ⬜ | 地点事件 + 主动记忆统一时间轴 |
| S2-012 | 今日足迹 | ⬜ | 今天去了哪里 |
| S2-013 | 地点详情 | ⬜ | 首次、最近、累计次数、相关记忆 |
| S2-014 | 原始位置生命周期 | ⬜ | 原始点短期保存，长期保存 Visit |
| S2-015 | 定位耗电监控指标 | ⬜ | 核心质量指标 |
| S2-016 | 定位权限渐进式引导 | ⬜ | 不能首次启动一次索取全部权限 |

---

# 4. Stage 3：懂生活 / AI Memory

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S3-001 | AI Gateway | ⬜ | 客户端不得直接调用模型厂商 API |
| S3-002 | Memory Pipeline | ⬜ | Capture → Normalize → Extract → Classify → Evidence → Store |
| S3-003 | Intent Router | ⬜ | FIND_OBJECT / FIND_PLACE / FIND_EVENT 等 |
| S3-004 | 实体提取 | ⬜ | 人物 / 地点 / 物品 / 时间 / 事件 |
| S3-005 | Entity Link | ⬜ | 新记录关联已有 Object / Place / Person |
| S3-006 | OCR | ⬜ | 图片文字提取 |
| S3-007 | Vision 图片理解 | ⬜ | 只作为证据辅助，不能凭空制造事实 |
| S3-008 | pgvector | ⬜ | 语义检索基础 |
| S3-009 | Embedding 生成与索引 | ⬜ | Memory 文本 / 结构化描述 |
| S3-010 | Structured First 检索 | ⬜ | 结构化 > 关键词 > Vector > LLM |
| S3-011 | Memory RAG | ⬜ | 只从用户自己的可用 Evidence 回答 |
| S3-012 | Evidence Ranking | ⬜ | 用户主动 > GPS/EXIF > 系统识别 > AI 推断 |
| S3-013 | “已确认 / 有证据 / AI推测”答案状态 | ⬜ | 前端必须明确展示 |
| S3-014 | Reminder 意图提取 | ⬜ | 用户确认后才创建提醒 |
| S3-015 | Daily Summary | ⬜ | “今天发生了什么” |
| S3-016 | 月度回忆 | ⬜ | 月度事件整理 |
| S3-017 | 年度回忆 | ⬜ | 年度报告 |
| S3-018 | 记忆纠错 / 用户确认反馈 | ⬜ | AI 整理结果可正确 / 修改 / 删除 |
| S3-019 | False Memory Rate 指标 | ⬜ | 最高优先级质量指标之一 |

---

# 5. Stage 4：连接家庭

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S4-001 | 家庭邀请 | ⬜ | 用户主动邀请 |
| S4-002 | 家庭成员绑定 | ⬜ | 本人 / 家庭成员基础角色 |
| S4-003 | 家庭权限矩阵 | ⬜ | 默认全部关闭，逐项授权 |
| S4-004 | 查看当前位置授权 | ⬜ | 独立权限 |
| S4-005 | 查看足迹授权 | ⬜ | 独立权限 |
| S4-006 | 查看个人记忆授权 | ⬜ | 默认关闭 |
| S4-007 | 查看照片授权 | ⬜ | 默认关闭 |
| S4-008 | 紧急位置共享 | ⬜ | 用户明确授权 |
| S4-009 | 到家提醒 | ⬜ | 家庭安全场景 |
| S4-010 | 微信小程序家庭端 | ⬜ | 以查看和快速操作为主 |
| S4-011 | 长辈模式 | ⬜ | 大字体、大按钮、语音优先 |
| S4-012 | 长辈模式“帮我记一下” | ⬜ | 一键语音入口 |
| S4-013 | 长辈模式“我想找东西” | ⬜ | 优先语音问答 |
| S4-014 | 长辈模式“今天去了哪里” | ⬜ | 简化足迹查看 |
| S4-015 | 家庭隐私审计 | ⬜ | 谁在什么时候查看过什么 |

---

# 6. V2：个人记忆图谱

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| V2-001 | Person 人物模型 | ⬜ | 名称、关系、别名、备注 |
| V2-002 | 人物相关记忆 | ⬜ | 见过谁 / 什么时候见过 |
| V2-003 | 人物关系图谱 | ⬜ | 人与事件、地点、物品建立关系 |
| V2-004 | Place / Person / Object / Event 统一图谱 | ⬜ | Personal Memory Graph |
| V2-005 | 人生事件模型 | ⬜ | 旅行、就医、聚会、工作等 |
| V2-006 | 人生阶段 | ⬜ | 工作、家庭、旅行等长期阶段 |
| V2-007 | 长期记忆推理 | ⬜ | 必须有证据链，不允许模型脑补 |
| V2-008 | “我认识某人多久了” | ⬜ | 基于最早 Evidence 回答 |
| V2-009 | “过去几年发生了什么” | ⬜ | 跨年长期检索 |
| V2-010 | 年度电子回忆录 | ⬜ | 图文年度总结 |
| V2-011 | 人生回忆录 | ⬜ | 长期高级能力 |

---

# 7. V3：AI 人生助手与硬件扩展

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| V3-001 | AI 人生助手 | ⬜ | 跨多年记忆查询与整理 |
| V3-002 | “过去十年”总结 | ⬜ | 长期时间范围分析 |
| V3-003 | 家庭数字档案 | ⬜ | 需要更严格的权限与继承设计 |
| V3-004 | 记忆按钮 / AI 挂件 | ⏸ | APP 验证需求后再做 |
| V3-005 | 可穿戴快捷语音记录 | ⏸ | 不等于 24 小时录音 |
| V3-006 | 实体回忆录打印 | ⏸ | 商业化扩展 |

---

# 8. 隐私、安全与合规（贯穿所有阶段）

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| SEC-001 | HTTPS / TLS | ⬜ | 上线前强制；对象存储 production 自定义 endpoint 已单独强制 HTTPS |
| SEC-002 | 对象存储私有桶 | 🟠 | 代码已按私有桶 + 服务端 key + fail-closed 设计实现；仍需真实 provider 部署验收 |
| SEC-003 | 临时签名下载 URL | 🟠 | 短时 PUT/GET 已实现；微信 API + signed PUT 合法域名及真实 COS/OSS 真机闭环仍需部署验收 |
| SEC-004 | 敏感数据权限隔离 | ⬜ | 位置 / 健康 / 家庭 / 生物识别分级 |
| SEC-005 | 服务端访问审计 | ⬜ | 敏感数据查询留痕 |
| SEC-006 | 数据导出 | ✅ | PR #12 已合并；当前认证用户可导出版本化 JSON，严格 owner 隔离且不泄露内部 Storage 字段 |
| SEC-007 | 数据彻底删除 | ⬜ | 对应 S1-021；DB / Cache / Storage 一致删除 |
| SEC-008 | 账户注销 | ⬜ | 对应 S1-022；与删除策略联动 |
| SEC-009 | 位置权限单独同意 | ⬜ | 按平台规则实施 |
| SEC-010 | 家庭查看逐项授权 | ⬜ | 默认关闭 |
| SEC-011 | 记忆暂停 | ✅ | 暂停/恢复、PrivacyPauseInterval 历史门禁与时区边界均已合并 |
| SEC-012 | AI 不知道就说不知道 | 🟠 | Evidence gate 已实现；完整 AI 层尚未进入 |
| SEC-013 | AI 推断显式标记 | ⬜ | UI 层尚未实现 |
| SEC-014 | 敏感操作二次确认 | ⬜ | 导出 / 删除 / 家庭授权等 |
| SEC-015 | 安全事件与异常访问告警 | ⬜ | 上线前设计 |

---

# 9. 商业化与增长

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| BIZ-001 | 免费版权益 | ⬜ | 基础记录 / 基础搜索 / 有限历史 |
| BIZ-002 | 个人会员 | ⬜ | 长期记忆 / AI 搜索 / 图片语音等 |
| BIZ-003 | 家庭会员 | ⬜ | 家庭共享 / 长辈模式 / 到家提醒 |
| BIZ-004 | 高级会员 | ⬜ | 长期档案 / 人生报告 / 大容量存储 |
| BIZ-005 | 年度回忆报告 | ⬜ | 可作为会员核心价值 |
| BIZ-006 | 实体年度回忆录 | ⏸ | 后续增值服务 |
| BIZ-007 | 北极星指标：成功找回记忆数 | ⬜ | 需要埋点系统 |
| BIZ-008 | D1 / D7 / D30 留存 | ⬜ | 上线后持续监控 |
| BIZ-009 | Memory Retrieval Success | ⬜ | 核心产品指标 |
| BIZ-010 | False Memory Rate | ⬜ | 核心安全指标 |

---

# 10. 明确后置 / 当前不做

| ID | 功能 | 状态 | 原因 |
| --- | --- | --- | --- |
| DEF-001 | 24 小时持续录音 | 🚫 | 隐私、合规、耗电与审核风险高 |
| DEF-002 | 自动人脸识别 | 🚫 | 生物识别敏感信息，V1 不做 |
| DEF-003 | 医疗诊断 | 🚫 | 产品定位不是医疗器械 / 诊断工具 |
| DEF-004 | 老年痴呆诊断或治疗建议 | 🚫 | 不进入医疗诊断范围 |
| DEF-005 | 自动全量扫描相册 | 🚫 | V1 只支持主动拍照 / 主动选择 |
| DEF-006 | 社交社区 | 🚫 | 与核心“记住 / 找回”无关 |
| DEF-007 | 新闻资讯 | 🚫 | 与核心目标无关 |
| DEF-008 | 商城 | 🚫 | V1 不引入 |
| DEF-009 | 广告系统 | 🚫 | V1 优先建立信任 |
| DEF-010 | AI 数字人 | ⏸ | 长期方向，非当前核心 |

---

# 11. 每次开发必须同步执行的项目规则

1. 开始新任务时：把对应 ID 从 `⬜` 改为 `🔵`。
2. 代码完成并通过当前自动测试后：改为 `🟠`。
3. 只有正式审查通过、合并 `main` 并完成必要验收后：改为 `✅`。
4. 发现新需求时：先加入本表并分配 ID，再开始实现。
5. 发现缺陷时：新增修复项或 Bug ID，不允许只改代码不记录。
6. 每次新增或修改人工维护的源代码，都必须遵守 `docs/CODE_ANNOTATION_RULES.md` 的 `[人工注释]` 标记规范。
7. 自动生成文件、lockfile、二进制资源不得为了加注释而破坏格式；通过提交记录和本表追踪。
8. Stage 2 及以后功能不得提前侵入当前 Stage 1 PR，除非先更新本表并明确变更范围。
9. 并行开发必须保持独立分支/独立 PR；共享协议由单一 PR 定义，其他工作线只消费。
10. 每条工作线在最终合并前都必须重新确认最新 `main`、clean replay、精确 HEAD CI 和最终净 diff。
