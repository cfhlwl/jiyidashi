| Mini V2-D | 小程序 Unified Graph Neighborhood V1 | ✅ | Issue #144 / PR #145：trusted read-only one-hop projection 已正式审查并合并；merge `ae7145c2e850ccf6df885ebac4b3e12fd5f499df` |<!-- 本文件是迹忆项目长期维护的唯一开发进度总表；每次功能开发、修复、审查或合并后都必须同步更新状态。 -->
<!-- PR #179 / #167 SEC-014 Sensitive Operation Confirmation Standard V1 已完成两轮正式 security review 并合并 main=2080174f。2026-09-30 production-launch audit 进一步确认：公开注册仍创建 LEGACY_FULL、用户认证仍为 7-day bearer-only、删除 durable state machine 缺少服务端自动 progression、备份默认同机、普通认证 API/AI provider 缺少统一瞬时滥用/并发门禁，并存在同步大导出、stale PENDING media、Security Alert 无人类通知、运行资源边界与真实容量 Gate 等上线前缺口。当前主线保持 ADMIN-001；其后先完成 Production Launch Hardening，再做 #136 最终真实生产验收。 -->
<!-- PR #9 已完成 latest-main clean replay、最终 Mini Program CI 与 replay-after-clean 核验，并合并 main=9722635f；C 工作线第一阶段正式完成，S1-005 转 ✅，S1-004 继续保持进行中，真实音频上传/ASR/Evidence 留待 S1-007。 -->
<!-- D1/PR #12 与 D2/PR #13 已分别完成正式审查、latest-main replay 与最终 CI 并合并；PR #13 先合并为 main=3b43574a，PR #12 随后 clean replay 到该 main 并合并为 main=f1d9baef。Issue #10/#11 已自动关闭。 -->
<!-- I：Memory Edit / PR #27 已完成正式复审并合并 main=24901d76；S1-018 转 ✅。J：Data Delete / PR #28 随后基于该新 main 完成 MemoryEdit 删除适配、0008 migration 顺延、单提交 clean replay 与 exact-head CI，并合并 main=3abc1366；S1-021 / SEC-007 转 ✅。 -->
<!-- Stage 1 第三批 A/B/C/D 第一阶段全部完成；Stage 1 本身仍未完成，下一阶段继续 S1-004/S1-007、S1-017、S1-008、S1-018、S1-021、S1-022、S1-025、S1-026；Stage 2 继续明确未开始。 -->
<!-- E：Voice Pipeline / Issue #14 已从 main=677b6ce9 启动；分支 feat/stage1-voice-asr 仅推进 S1-004 + S1-007，先完成真实音频上传、ASR provider 边界与原始音频 Evidence，Stage 2 继续未开始。 -->
<!-- E：Voice Pipeline / PR #18 初版实现生产/测试 HEAD=9ad68a3844，Backend CI 35216633743 与 Mini Program CI 35216633782 均 SUCCESS；第一轮正式审查随后 HOLD，发现 2×P1 + 1×阻塞 P2。 -->
<!-- PR #18 第一轮三个窄修已实现并通过精确 HEAD=eb29b0235a 验收：FIX-001 将 DB preflight/claim 与外部 storage+ASR I/O 真正分离；FIX-002 新增 durable media_asr_claims 租约并由真实 PostgreSQL 双 Session 验证 provider 单飞；FIX-003 用 httpx MockTransport 覆盖 OpenAIASRProvider HTTP adapter。Backend CI 35221916652 SUCCESS（含 PostgreSQL voice single-flight 与 77 passed），Mini Program CI 35221916739 SUCCESS。三项仍待第二轮窄范围正式复审，不标 ✅。 -->
<!-- PR #18 第二轮窄范围复审 PASS：S1-PR18-FIX-001~003 已正式关闭；生产/测试 HEAD=8ea2a1c7513f64f496f7cbaa1dfe8c36717d0bf8，Backend CI 35222923492 / #166 SUCCESS（PostgreSQL voice ASR single-flight PASS，77 passed），Mini Program CI 35222923466 / #154 SUCCESS。PR 进入最终 clean replay / exact-head CI Gate，S1-004/S1-007 与 E 线继续保持 🟠，待最终合并 main 后转 ✅。 -->
<!-- Stage 1G / PR #17 Flutter 第一阶段已完成 G1~G6，并在 latest main=a1962100（PR #18 合并后）做 clean replay；S1-027 与 G 工作线保持 🟠，等待正式 UI 审查、最终合并与必要验收；Stage 2 继续未启动。 -->
<!-- PR #17 第二轮极窄复审 PASS，最终 clean HEAD=d8373adc；标准 mobile-ci 35246026919 与 mobile-visual-preview 35246029602 均 SUCCESS，随后以 expected_head_sha 锁定合并，merge commit=d470f662；Issue #16 自动关闭，S1-027 与 G 工作线转 ✅，Stage 2 继续未启动。 -->
<!-- PR #18 / E Voice Pipeline 已完成 final clean replay、exact-head Backend/Mini CI 并合并，merge commit=a1962100；Issue #14 已关闭 completed，S1-004/S1-007 转 ✅。 -->
<!-- PR #20 / F Offline Sync 已完成两轮正式审查、final narrow Gate、latest-main single-commit replay 与三套 exact-head CI，并以 expected-head 锁定合并，merge commit=c4ee5734；Issue #15 已关闭 completed，S1-017 转 ✅。 -->
<!-- PR #22 / H Unified Capture 已完成多轮正式审查、recorder fail-closed 终止竞态收口、final clean replay 与四套 exact-head CI，并合并 main=1f0f9487；Issue #21 随 PR 合并完成，S1-008 转 ✅。Stage 1 最后一批 I/J/K/L 已以 Issue #23/#24/#25/#26 并行启动。 -->
<!-- L：Onboarding / PR #30 已完成正式独立复审（P0=0 / P1=0）、exact-head Mobile #325 与 Visual #181 全绿，并以审核通过 HEAD 7622136e 锁定 squash 合并；merge commit=a4f02cb5，S1-026 转 ✅。 -->
<!-- K：Reminder / PR #29 已完成 very narrow 最终确认并合并 main=b000e8db；S1-025 转 ✅。M：Account Delete / PR #32 随后完成两轮正式审查、latest-main 单提交、四套 exact-head CI，并 squash 合并 main=004ff28f；S1-022 / SEC-008 / S1-M3 转 ✅，Stage 1「记得住」正式收口。 -->
<!-- O：Location / Visit Foundation / Issue #35 / PR #36 已完成正式审查、latest-main Git Gate 与合并；owned S2-006/S2-007/S2-008/S2-014 转 ✅。 -->
<!-- N：Native Location Foundation / Issue #34 / PR #37 已完成正式审查并合并 main；owned S2-001/S2-002/S2-003/S2-016 转 ✅。Q 只消费其已合并原生定位基础，不记录 N 的瞬时 HEAD/CI。 -->
<!-- Q：Place & Timeline Product / Issue #39：PR #40 已完成并合并，S2-009/S2-010 转 ✅；Timeline Foundation / PR #42 已完成正式审查、exact-head Backend/Mini CI 与 Git Gate 并合并 main=27111542，S2-011 转 ✅；后续 S2-012/S2-013 已分别由 R/S 独立工作线完成。 -->
<!-- P：Motion & Smart Sampling / Issue #38 / PR #41 已完成两轮正式审查、latest-main clean replay、exact-head Mobile #418 / Visual #274 与 Git Gate，并 squash 合并 main=07f91dfc；S2-004/S2-005/S2-015 转 ✅。 -->
<!-- R：Today Footprint / Issue #43 / PR #45 已完成正式审查、exact-head CI 与 Git Gate，并合并 main=e2789eff；S2-012 转 ✅。 -->
<!-- S：Place Detail / Issue #44 / PR #46 已完成 Flutter + Mini Program 正式复审、latest-main single-commit clean replay、四套 exact-head CI 与最终 Git Gate，并 squash 合并 main=9e1b96da；S2-013 转 ✅。 -->
<!-- T：Unsigned iOS IPA CI / Issue #47 / PR #48 已完成 portable checksum sidecar、自校验、IPA artifact、exact-head 与 Git Gate 审查，并合并 main=ce9b9d90；无签名 IPA CI 正式完成。 -->
<!-- U：Software Copyright Annotation Gate / Issue #50 / PR #51 已完成正式审查并合并。 -->
<!-- V：Intent Router Foundation / Issue #54 / PR #55 已完成 typed contract、deterministic precedence、owner isolation、UNKNOWN fail-closed、旧可信链回归、Annotation Gate 与 exact-head Backend CI，并 squash 合并 main=8c0758bd；S3-003 转 ✅。 -->
<!-- Stage 3A：AI Gateway / Issue #53 / PR #56 已完成第一轮代码审查 PASS，当前只剩 latest-main replay / exact-head Backend / final Git Gate；只拥有 S3-001，不创建/修改 Memory、Evidence、Object、Place、Visit 或 Reminder。 -->
<!-- Stage 3C：Memory Pipeline Foundation / Issue #57 / PR #60 已完成正式审查、user-facing trust isolation 修复、exact-head Backend CI 与最终 Gate，并合并 main=d3f61b4d；S3-002 转 ✅。 -->
<!-- Stage 3F：OCR Foundation / Issue #62 / PR #64 已完成两轮 very narrow review、latest-main clean replay、exact-head Backend/Mini CI 与最终 Git Gate，并合并 main=b94c46f；S3-006 转 ✅。 -->
<!-- Stage 3E：Entity → Memory Pipeline Integration / Issue #61 / PR #63 已完成 trusted execution integration 并合并 main=1e28b975；Entity metadata 保持 inference-only internal annotations。 -->
<!-- Stage 3H：pgvector Foundation / Issue #66 / PR #67 已完成 PostgreSQL vector extension + SQLAlchemy 类型基础、真实 PostgreSQL CI、正式 review 与合并 main=b7579c4d；S3-008 转 ✅。 -->
<!-- Stage 3G：Vision Foundation / Issue #65 / PR #68：用户主动触发 owner-scoped READY IMAGE 可见场景/物品/活动候选观察；provider 仅可返回受控 kind/code，server-owned labels + trust_class=inference，不写 Memory/Evidence/Entity/Visit/Reminder；正式 review PASS，等待 latest-main exact-head Gate/合并。 -->
<!-- Stage 3J：Evidence Ranking Foundation / Issue #70 / PR #71 已完成实现、P2 no-autoflush 修复、正式 review、latest-main final Gate 与合并 main=f3c84899；S3-012 转 ✅。 -->
<!-- Stage 3K：Structured First Retrieval / Issue #73 / PR #76 已完成正式两轮审查、latest-main exact-head Gate 与合并 main=e9225739；S3-010 转 ✅。 -->
<!-- Stage 3L：Answer Trust State / Issue #74 / PR #75 已完成 latest edit-source fail-closed、persisted-state isolation、正式两轮审查与合并 main=a0636479；S3-013 转 ✅。 -->
<!-- Stage 3M：Memory RAG Foundation / Issue #77 / PR #80 已完成两轮正式审查；provider 后复核全部实际 prompt slots、uncited-slot PostgreSQL race gate 与 exact-head CI 均通过，并合并 main=1ad715b1；S3-011 转 ✅。Stage 3N：Reminder Intent / Issue #78 / PR #79 已完成 StrictBool fail-closed、final exact-head Gate 并合并 main=a7366e89；S3-014 转 ✅。 -->
<!-- Stage 3O：Daily Summary / Issue #82 / PR #84 已完成两轮正式审查、excluded-NO_EVIDENCE authority race 修复、latest-main exact-head Backend CI，并合并 main=9728d46b；S3-015 转 ✅。Stage 3P：Memory Feedback / Issue #83 / PR #85 已完成 same-key advisory single-flight 修复、latest-main clean replay、exact-head Backend CI，并合并 main=964723d4；S3-018 转 ✅。 -->
<!-- Stage 3Q：Monthly Summary / Issue #86 / PR #90 已完成 complete-month snapshot、all-raw-Memory authority、provider 前后完整重验、正式审查与 latest-main Gate，并合并 main=f6aa0fb3；S3-016 转 ✅。Stage 3R：False Memory Rate / Issue #87 / PR #89 已完成 revision-level canonical aggregation、DELETE-only denominator boundary、两轮正式审查与 exact-head CI，并合并 main=512e45db；S3-019 / BIZ-010 转 ✅。 -->
<!-- Stage 3S：Annual Summary / Issue #91 / PR #93 已完成 complete-year snapshot、512+1/256+1 bounded inventory、all-raw S3-013 authority、strict Y-slot provider boundary、provider 前后完整重验与 PostgreSQL Annual Gate，并合并 main=dd558913；S3-017 转 ✅，Stage 3 S3-001~S3-019 正式收口。 -->
# 迹忆开发进度总表

> 最后更新：2026-10-04  
> Stage 1「记得住」：✅ complete  
> Stage 2「自动记」：✅ complete  
> Stage 3「懂生活 / AI Memory」：✅ complete  
> Stage 4「连接家庭 / Elder V1」：✅ complete  
> Stage 4 final production baseline：`9576c7ad912823115e83e67608fdab408e484f1f`（PR #125 merge；before docs-only Stage 4 closeout）  
> 当前阶段：**UIUX-P0-002 / JiYi Consumer Visual Fidelity V1（Issue #204）**。SEC-016 / PR #203 已正式审查并合并；当前开始按 2026-09-29 用户确认的 8 张高保真参考图重构消费者端视觉，并同步收口真实高德地图体验与 owner-scoped 本机媒体缓存。Flutter 为首要视觉目标，Mini 同步视觉语言。CORE-004 真机长期认证继续暂缓，待视觉与客户端行为稳定后重新发起。

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
| S1-M3 | Stage 1 第三批“多媒体记录 + 离线 + 数据控制” | ✅ | A～M 全部完成正式审查、latest-main replay / 精确 HEAD CI 并合并；PR #32 合并后 Stage 1 第三批正式收口 |
| CI-001 | Backend CI | ✅ | PR #32 final reviewed HEAD `ba6270ab` 的 Backend CI `35444809518` / #313 SUCCESS：Lint、SQLite/PostgreSQL migration、schema drift、既有 PostgreSQL invariants、Account Delete durability 与 full pytest（110 passed）全部通过 |
| CI-002 | Flutter Android CI | ✅ | PR #32 final reviewed HEAD `ba6270ab` 的 Mobile CI `35444809482` / #354 SUCCESS：Analyze、117 Flutter tests、Android permissions、debug/release 全部通过 |
| CI-003 | Flutter iOS CI | ✅ | PR #32 final reviewed HEAD `ba6270ab` 的 Mobile CI `35444809482` / #354 SUCCESS：iOS no-codesign build 通过 |
| CI-004 | 微信小程序 CI | ✅ | PR #32 final reviewed HEAD `ba6270ab` 的 Mini Program CI `35444809464` / #222 SUCCESS：lockfile install、typecheck、capture tests、production WeChat build 均通过 |
| CI-005 | UI Visual Preview / Golden Screenshot | ✅ | PR #32 final reviewed HEAD `ba6270ab` 的 Mobile Visual Preview `35444809519` / #210 SUCCESS：Committed Goldens、intentional mismatch、artifact、Android/iOS 与 clean-worktree gate 全部通过 |
| CI-006 | 无签名 iOS IPA 测试产物 | ✅ | PR #48 已完成 portable checksum sidecar、自校验、IPA artifact、exact-head 与 Git Gate，并合并 `main=ce9b9d90` |
| MAINT-001 | 软件著作权注释门禁 | ✅ | Issue #50 / PR #51 已完成 9 个关键源码文件 comments-only 注释补强、Annotation Gate、Stage 2 文档收口、正式审查、exact-head CI 与 Git Gate，并 squash 合并 `main=7227fe18` |

---

# 1. Foundation：可信记忆与工程基础

| ID | 功能 / 需求 | 状态 | 验收要求 / 当前说明 |
| --- | --- | --- | --- |
| FND-001 | FastAPI 模块化单体基础工程 | ✅ | PR #1 合并 main |
| FND-002 | PostgreSQL / SQLite 开发数据库基础 | ✅ | PostgreSQL 已进入正式 CI |
| FND-003 | Redis 开发依赖基础 | ✅ | Docker 开发环境基础已配置 |
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
| S1-004 | 语音记忆录入 | ✅ | PR #18 已完成正式审查、final clean replay 与 exact-head Backend/Mini CI 并合并；原始音频 Evidence、ASR fail-closed 与 durable single-flight 均已验证；merge commit `a1962100` |
| S1-005 | 图片记忆录入 | ✅ | PR #7 后端媒体/Evidence + PR #9 小程序真实拍照/选图上传链均已审查、CI、clean replay 并合并 |
| S1-006 | COS / OSS 对象存储直传 | ✅ | 私有 staging→final、短时签名、owner gate、图片签名验证与 commit-safe staging 清理已落地 |
| S1-007 | ASR 语音转写 | ✅ | PR #18 已完成 transaction/I-O 分离、durable ASR claim/lease 单飞、OpenAI adapter contract tests、final exact-head CI 并合并；Issue #14 已关闭 completed |
| S1-008 | “帮我记住”统一入口 | ✅ | PR #22 已完成多轮正式审查、recorder fail-closed 生命周期/终止竞态收口、final clean replay 与四套 exact-head CI；已合并 `main=1f0f9487` |
| S1-009 | “东西在哪”物品录入 | ✅ | Object create 并发竞争已幂等兜底 |
| S1-010 | “东西在哪”查询 | ✅ | 返回真实 Evidence `source_type` / `memory_source_id` |
| S1-011 | “东西在哪”物品位置失效 / “已经不在那里” | ✅ | 唯一最具体 Object、UNKNOWN 失效水位、锁与重叠名称回归均通过 |
| S1-012 | 基础记忆搜索 | ✅ | 普通 Memory Evidence 返回真实来源且不降低 gate |
| S1-013 | “问记忆”客户端页面接真实 API | ✅ | Flutter / 小程序已接真实 API |
| S1-014 | 答案展示 Evidence / 来源 / 时间 | ✅ | 客户端展示来源、证据类型、时间、可信度 |
| S1-015 | 客户端本地 SQLite | ✅ | PR #6 已合并；版本化 SQLite、账号隔离、重启恢复完成 |
| S1-016 | 离线记忆队列 | ✅ | PR #6 已合并；状态机、稳定 UUID、取消/重试、仅 TransportException fallback 均通过正式审查 |
| S1-017 | 离线同步与幂等 | ✅ | PR #20 已完成服务端幂等账本、outbox-first、unknown-commit replay、auth/cancel/single-flight、时间水位与 retry 分类；final HEAD `c654e65c` 三套 exact-head CI 全绿并合并，merge commit `c4ee5734`；Issue #15 已关闭 completed |
| S1-018 | 单条 Memory 编辑 | ✅ | PR #27 已完成正式复审与四套 exact-head CI，并 squash 合并为 main=`24901d76`；原始 Evidence、USER_EDIT provenance、revision 并发门禁与 Flutter 编辑闭环均已验收 |
| S1-019 | 单条 Memory 删除 | ✅ | 服务端 DELETE、删除后查询失效及 ObjectLocation 联动均已合并 |
| S1-020 | 数据导出 | ✅ | PR #12 已合并；owner 隔离、JSON v1、媒体敏感字段保护、5000 上限/413、删除位置 tombstone 均通过正式审查 |
| S1-021 | 全部数据删除 | ✅ | PR #28 已完成正式收口、new-main clean replay 与 exact-head Backend CI，并 squash 合并为 main=`3abc1366`；durable DB/storage 删除、旧请求 generation gate、Presigned PUT expiry+quiet、MemoryEdit 审计清理均已验收 |
| S1-022 | 注销账号 | ✅ | M 线 / Issue #31 / PR #32 已完成两轮正式审查；durable Account gate、S1-021 复用、身份最终事务、恢复 token、旧 token fail-closed、本机 producer/sync/onboarding quiesce 与 purge-last-write 回归均通过；final reviewed HEAD `ba6270ab` 四套 exact-head CI 全绿并 squash 合并 `main=004ff28f` |
| S1-023 | 暂停记忆 30 分钟 / 1 小时 / 3 小时 / 今天 | ✅ | 单一 reference timestamp + DST 时区回归通过 |
| S1-024 | 手动恢复记录 | ✅ | resume 保留 PrivacyPauseInterval 历史，延迟上传门禁通过 |
| S1-025 | 基础提醒模型 | ✅ | PR #29 已完成第一轮修复、PR #30 overlap latest-main replay、四套 exact-head CI 与 very narrow 最终确认，并合并 main=`b000e8db` |
| S1-026 | 首次使用引导 | ✅ | L 线 / Issue #26 / PR #30：真实 Unified Capture → authoritative Memory ID → 同一 Memory + Evidence Aha flow 已通过正式独立复审与 exact-head Mobile/Visual CI，并 squash 合并为 main=`a4f02cb5` |
| S1-027 | Product UI / Design System | ✅ | PR #17 已完成两轮正式审查、latest-main clean replay、exact-head Mobile/Visual CI 并合并；Theme/token/共享组件、5 个核心页面、Evidence/隐私/离线状态及 Golden 均已验证；merge commit `d470f662`；Stage 2 未启动 |

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
| S1-PR18-FIX-001 | P1 | ✅ 第二轮关闭：DB preflight/claim 与 storage/ASR 外部 I/O 之间存在真实 transaction gap；storage/provider 执行时 `Session.in_transaction()==False` |
| S1-PR18-FIX-002 | P1 | ✅ 第二轮关闭：`media_asr_claims` durable lease/token 实现数据库级单飞；真实 PostgreSQL 双 Session 验证 provider calls=1 且 Memory/Source/Evidence 唯一 |
| S1-PR18-FIX-003 | P2 | ✅ 第二轮关闭：`OpenAIASRProvider` 真实 adapter 通过 MockTransport 覆盖 multipart、Authorization、logprobs、HTTP/timeout/malformed 错误路径 |
| S1-PR20-FIX-001~006 | 5×P1 + 1×P2 | ✅ 两轮审查与最终极窄 Gate 全部关闭：冻结 `occurred_at/recorded_at`、ObjectLocation immutable auth snapshot、deleted backing Memory replay fail-closed、5xx/429/auth retry 分类、F/G 单一生产 UI 集成，以及正常开发注释规范；final exact-head Backend/Mobile/Visual CI 全绿 |

## 2.2 下一阶段推荐并行工作线

<!-- 以下是第三批第一阶段完成后的 Stage 1 收口顺序；这里只记录计划，不代表任务已开工。未创建分支/Issue 前状态继续保持 ⬜。 -->

| 优先级 | 工作线 | 对应任务 | 当前状态 | 说明 |
| --- | --- | --- | --- | --- |
| 已完成 | E：Voice Pipeline | `S1-004 + S1-007` | ✅ | PR #18 已正式审查、clean replay、exact-head Backend/Mini CI 并合并；Issue #14 已关闭 |
| 已完成 | F：Offline Sync | `S1-017` | ✅ | PR #20 已两轮审查、final narrow Gate、single-commit replay 与三套 exact-head CI 后合并；Issue #15 已关闭 |
| 已完成 | G：Product UI / Design System | `S1-027` | ✅ | PR #17 Flutter 第一阶段已完成正式审查、最终 clean replay、exact-head CI 并合并；微信小程序视觉同步仍属后续独立工作 |
| 已完成 | H：Unified Capture | `S1-008` | ✅ | PR #22 已正式审查、final clean replay、四套 exact-head CI 后合并；main=`1f0f9487` |
| 已完成 I | Memory Edit | `S1-018` | ✅ | PR #27 已正式复审、四套 exact-head CI 全绿并合并 main=`24901d76` |
| 已完成 J | Data Delete | `S1-021` | ✅ | PR #28 已基于 PR #27 后的新 main 完成 MemoryEdit 删除适配、0008 migration、单提交 clean replay 与 exact-head CI，并合并 main=`3abc1366` |
| 已完成 M | Account Delete | `S1-022` | ✅ | Issue #31 / PR #32 已完成两轮正式审查、latest-main 单提交、四套 exact-head CI 并 squash 合并；merge commit=`004ff28f`，S1-022 / SEC-008 正式完成 |
| 已完成 K | Reminder | `S1-025` | ✅ | PR #29 已 latest-main clean replay、very narrow 最终确认并合并 main=`b000e8db`；Issue #25 随合并闭环 |
| 已完成 L | Onboarding | `S1-026` | ✅ | PR #30 已正式独立复审通过并 squash 合并，merge commit=`a4f02cb5`；真实 Unified Capture → target Memory → Evidence Aha flow 完整闭环 |

### 硬规则

- 一个任务组一个独立分支、一个独立 PR；禁止大而全的 Stage 1 分支。
- 人工新增/修改的代码使用正常开发注释解释关键意图、约束、风险和非显而易见的边界；不要求固定标签，也不为简单代码机械加注释。
- 公共 API/schema/Evidence 协议只允许一个 PR 定义，其他端只消费。
- 每个 PR 合并前都必须基于最新 `main` 做最终 replay / CI。
- `S1-021 → S1-022` 顺序不可反。
- Stage 1 PR 不得提前侵入 Stage 2；O（S2-006/S2-007/S2-008/S2-014）与 N（S2-001/S2-002/S2-003/S2-016）均已独立完成并合并；当前 Q 必须继续保持自己的产品层范围，禁止回写 O/N 的定位与派生协议。

---

# 3. Stage 2：自动记

> **Stage 2「自动记」已完成：O / Location & Visit Foundation、N / Native Location Foundation、P / Motion & Smart Sampling、Q / Place Naming + Timeline、R / Today Footprint、S / Place Detail 均已正式审查并合并。**

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S2-001 | Android 原生后台定位模块 | ✅ | N / PR #37 已完成正式审查并合并 main |
| S2-002 | iOS CoreLocation 后台定位模块 | ✅ | N / PR #37 已完成正式审查并合并 main |
| S2-003 | Flutter 统一 Location Bridge | ✅ | N / PR #37 已完成正式审查并合并 main |
| S2-004 | 运动状态识别 | ✅ | P / PR #41 已完成正式审查、latest-main clean replay、exact-head CI 与合并 |
| S2-005 | 智能定位采样策略 | ✅ | P / PR #41 已完成 motion/quality-aware cadence、stable UUID replay、FUTURE 422 retry 审查并合并 |
| S2-006 | Location Point 批量同步 | ✅ | O / PR #36 已完成正式审查、latest-main Gate 并合并 `main` |
| S2-007 | Visit 聚类 | ✅ | O / PR #36 已完成正式审查、latest-main Gate 并合并 `main` |
| S2-008 | Place 模型与地点库 | ✅ | O / PR #36 已完成正式审查、latest-main Gate 并合并 `main` |
| S2-009 | Place 自动命名 | ✅ | Q / PR #40 已完成正式审查、legacy seeded migration 与 automatic↔USER PostgreSQL race 验收并合并 main |
| S2-010 | Place 用户纠正 | ✅ | Q / PR #40 已完成 owner isolation、ClientMutation、Place FOR UPDATE、Export/Data Delete 与并发验收并合并 main |
| S2-011 | 自动时间轴 | ✅ | Q / Timeline Foundation / PR #42 已完成正式审查、exact-head Backend/Mini CI 与 Git Gate并合并 `main=27111542` |
| S2-012 | 今日足迹 | ✅ | R / Issue #43 / PR #45 已完成服务端 owner-timezone Visit-overlap 投影、Flutter/小程序同步、正式复审、exact-head CI 与 Git Gate，并合并 `main=e2789eff` |
| S2-013 | 地点详情 | ✅ | S / PR #46 已完成 Backend + Flutter + Mini Program 正式审查、原 P2 收口、latest-main single-commit clean replay 与四套 exact-head CI，并 squash 合并 main=`9e1b96da` |
| S2-014 | 原始位置生命周期 | ✅ | O / PR #36 已完成独立 maintenance / deletion serialization 审查与 latest-main Gate，并合并 `main` |
| S2-015 | 定位耗电监控指标 | ✅ | P / PR #41 已完成无坐标 metrics 审查、exact-head CI 与合并 |
| S2-016 | 定位权限渐进式引导 | ✅ | N / PR #37 已完成正式审查并合并 main |

---

# 4. Stage 3：懂生活 / AI Memory

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S3-001 | AI Gateway | ✅ | Issue #53 / PR #56 已完成正式审查、latest-main replay、exact-head Backend CI 与最终 Git Gate，并合并 `main=db2f7fcc` |
| S3-002 | Memory Pipeline | ✅ | Issue #57 / PR #60 已完成核心 Pipeline、Evidence/inference trust boundary、replay/idempotency、owner isolation、query/day-summary user-facing fail-closed、exact-head Backend CI 与最终 Gate，并合并 `main=d3f61b4d` |
| S3-003 | Intent Router | ✅ | Issue #54 / PR #55 已完成正式 very narrow review（P0/P1/P2=0/0/0）、typed contract、deterministic precedence、owner isolation、UNKNOWN fail-closed、Annotation Gate、既有 Object/Place/Memory 回归与 exact-head Backend CI `35507973659`，并 squash 合并 `main=8c0758bd` |
| S3-004 | 实体提取 | ✅ | Issue #58 / PR #59 已完成 candidate-only typed extraction、strict literal-span parser、AIGateway provenance、正式审查与 exact-head Backend CI，并合并 `main=da0662a7` |
| S3-005 | Entity Link | ✅ | Issue #58 / PR #59 已完成 owner-scoped deterministic Object/Place linking、ambiguous/no-match/cross-owner fail-closed、正式审查与 exact-head Backend CI，并合并 `main=da0662a7` |
| S3-006 | OCR | ✅ | Issue #62 / PR #64 已完成 user-triggered owner-scoped READY IMAGE OCR、AIGateway image boundary、strict parser/provenance、no-persistence/query regression、两轮正式审查、latest-main replay 与 exact-head CI，并合并 `main=b94c46f` |
| S3-007 | Vision 图片理解 | ✅ | Issue #65 / PR #68 已完成 controlled kind/code Vision、server-owned labels、no-persistence/query regression、正式审查与 exact-head CI，并合并 `main=d77dca2d` |
| S3-008 | pgvector | ✅ | Issue #66 / PR #67 已完成 PostgreSQL vector extension、SQLAlchemy pgvector seam、SQLite no-op migration、保守 downgrade、zero-VECTOR-column scope gate、真实 PostgreSQL CI 与正式审查，并合并 `main=b7579c4d` |
| S3-009 | Embedding 生成与索引 | ✅ | Issue #69 / PR #72 已完成 MemoryEmbedding 派生索引、VECTOR(1536)、HNSW cosine、owner-binding 复合 FK、编辑/删除/Data Delete 生命周期、正式两轮审查与 exact-head CI，并合并 `main=0766d027` |
| S3-010 | Structured First 检索 | ✅ | Issue #73 / PR #76 已完成 STRUCTURED > KEYWORD > VECTOR、Object CURRENT terminal-miss、server-side Object 32+1 cap、vector keyset paging + fingerprint validation + typed scan-limit、Evidence Ranking enrichment、正式两轮审查与 exact-head CI，并合并 `main=e9225739` |
| S3-011 | Memory RAG | ✅ | Issue #77 / PR #80 已完成内部 read-only RAG seam、S3-013 authoritative trust re-resolution、opaque Evidence slots、strict citation parser、provider 后重验全部 prompt slots、uncited-slot PostgreSQL concurrency gate、正式两轮审查与 exact-head CI，并合并 `main=1ad715b1` |
| S3-012 | Evidence Ranking | ✅ | Issue #70 / PR #71 已完成固定 `USER_DIRECT > SENSOR_DIRECT > SYSTEM_DERIVED > AI_INFERENCE`、owner/deleted isolation、deterministic tie-break、no-autoflush read-only seam、正式 review 与 exact-head CI，并合并 `main=f3c84899` |
| S3-013 | “已确认 / 有证据 / AI推测”答案状态 | ✅ | Issue #74 / PR #75 已完成四态 server-owned resolver、latest edit-source fail-closed、独立 persisted-state read Session、两轮正式审查与 final Gate，并合并 `main=a0636479` |
| S3-014 | Reminder 意图提取 | ✅ | Issue #78 / PR #79 已完成 AIGateway-only inference candidate、StrictBool exact provider contract、literal-span gate、server-owned timezone/time grammar、DST/past fail-closed、显式确认与 no-write 回归；正式复审与 current-head exact CI 通过，并合并 `main=a7366e89` |
| S3-015 | Daily Summary | ✅ | Issue #82 / PR #84 已完成完整日 authoritative snapshot、all-raw-Memory authority revalidation、provider-I/O race gates、两轮正式审查与 exact-head Backend CI，并 squash 合并 `main=9728d46b` |
| S3-016 | 月度回忆 | ✅ | Issue #86 / PR #90 已完成 server-owned local month、bounded complete Memory/Visit inventory、all-raw-Memory S3-013 authority、opaque M-slots、strict provider contract 与 provider-I/O race gates；正式审查、latest-main replay / exact-head CI 后合并 `main=f6aa0fb3` |
| S3-017 | 年度回忆 | ✅ | Issue #91 / PR #93 已完成 server-owned local year、Memory 512+1 / Visit 256+1 complete inventory、all-raw-Memory S3-013 authority、192-slot / 64k complete-or-fail provider context、strict opaque Y-slots、provider 前后完整重验与 PostgreSQL Annual Gate；exact-head Backend #562（445 passed）后合并 `main=dd558913` |
| S3-018 | 记忆纠错 / 用户确认反馈 | ✅ | Issue #83 / PR #85 已完成显式 CONFIRM/CORRECT/DELETE、revision-bound audit、PostgreSQL advisory single-flight、既有 Edit/Delete 复用、Data/Account Delete 生命周期、两轮正式审查与 latest-main exact-head CI，并 squash 合并 `main=964723d4` |
| S3-019 | False Memory Rate 指标 | ✅ | Issue #87 / PR #89 已完成 persisted S3-018 revision-bound feedback 的 canonical revision aggregation；`CORRECT > CONFIRM > DELETE-only`、result_revision 不自动判定、owner/persisted-state isolation、Data/Account Delete 生命周期与 PostgreSQL Gate 均通过；两轮正式审查后合并 `main=512e45db` |

---

# 5. Stage 4：连接家庭

> **Stage 4 已完成。** S4-001～S4-015 均已完成正式审查并合并 `main`；下一阶段为 V2 Personal Memory Graph，本收口不启动 V2 实现。

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S4-001 | 家庭邀请 | ✅ | Issue #95 / PR #96；Family Invite foundation 已合并，merge `c933f2a6` |
| S4-002 | 家庭成员绑定 | ✅ | Issue #95 / PR #96；Family Membership foundation 已合并，merge `c933f2a6` |
| S4-003 | 家庭权限矩阵 | ✅ | Issue #95 / PR #96；default-deny exact-grant permission matrix 已合并，merge `c933f2a6` |
| S4-004 | 查看当前位置授权 | ✅ | Issue #97 / PR #99；exact `VIEW_CURRENT_LOCATION` sensitive read 已合并，merge `f1860ba4` |
| S4-005 | 查看足迹授权 | ✅ | Issue #97 / PR #99；exact `VIEW_FOOTPRINT` Today Footprint read 已合并，merge `f1860ba4` |
| S4-006 | 查看个人记忆授权 | ✅ | Issue #107 / PR #109；exact `VIEW_MEMORY` Family Memory Read V1 已合并，merge `99d5e8ed` |
| S4-007 | 查看照片授权 | ✅ | Issue #108 / PR #110；exact `VIEW_PHOTOS` Family Photos Read V1 已合并，merge `4936e396` |
| S4-008 | 紧急位置共享 | ✅ | Issue #113 / PR #114；time-bounded Emergency Location Sharing V1 已合并，merge `0ec77a68` |
| S4-009 | 到家提醒 | ✅ | Issue #115 / PR #116；one-shot Arrival-Home Reminder V1 已合并，merge `296bbc03` |
| S4-010 | 微信小程序家庭端 | ✅ | Issue #100 / PR #102；Mini Program Family V1 已合并，merge `9867c7f0` |
| S4-011 | 长辈模式 | ✅ | Issue #118 / PR #119；self-controlled Elder Mode Foundation V1 已合并，merge `049eab74` |
| S4-012 | 长辈模式“帮我记一下” | ✅ | Issue #120 / PR #121；explicit voice-first Elder Remember V1 已合并，merge `82a155b0` |
| S4-013 | 长辈模式“我想找东西” | ✅ | Issue #122 / PR #123；trusted no-guess Elder Find Things V1 已合并，merge `b8550a20` |
| S4-014 | 长辈模式“今天去了哪里” | ✅ | Issue #124 / PR #125；trusted self Today Footprint Elder view 已合并，merge `9576c7ad` |
| S4-015 | 家庭隐私审计 | ✅ | Issue #111 / PR #112；Family Privacy Audit V1 已合并，merge `c0e6c4bd` |

---

# 6. V2：个人记忆图谱

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| V2-001 | Person 人物模型 | ✅ | Issue #128 / PR #129：owner-scoped explicit people model 已正式审查并合并；merge `5f9f87dfa868eb85255f9e0aa56a22a5a9afe3cf` |
| V2-002 | 人物相关记忆 | ✅ | Issue #130 / PR #131：explicit evidence-bound Person↔Memory Links V1 已正式审查并合并；merge `6b061b9cee51c00df88bbdb3832c4d35e133c5e5` |
| V2-003 | 人物关系图谱 | ✅ | Issue #132 / PR #133：explicit owner-maintained Person↔Person direct edges 已正式审查并合并；merge `c7b2fb6e5899c54e2f3e538786ed0185295754d5` |
| V2-004 | Place / Person / Object / Event 统一图谱 | ✅ | Issue #134 / PR #135：trusted read-only Unified Memory Graph V1 已正式审查并合并；merge `ef98cabae96537958a1306f52e7ea3caad0d4c3a` |
| Mini V2-A | 小程序 People Center V1 | ✅ | Issue #138 / PR #139：explicit Person CRUD + aliases 已正式审查并合并；merge `a18799d7bf023503323387b70897cdf304857754` |
| Mini V2-B | 小程序 Person Memory Timeline V1 | ✅ | Issue #140 / PR #141：explicit RELATED/MET links、关联已有记忆与 backend-authoritative 最近互动已正式审查并合并；merge `284b0ae98e09499d4131dd3e386ef2307f903eb6` |
| Mini V2-C | 小程序 Person Relationships V1 | ✅ | Issue #142 / PR #143：explicit direct Person↔Person relationship CRUD、OTHER/custom_label contract、field-aware conflict rebase 已正式审查并合并；merge `feb766d7ac78eb87436857d3b69138789ba1bd63` |
| Mini V2-D | 小程序 Unified Graph Neighborhood V1 | ✅ | Issue #144 / PR #145：trusted read-only one-hop PERSON/PLACE/OBJECT/EVENT projection 已正式审查并合并；merge `ae7145c2e850ccf6df885ebac4b3e12fd5f499df` |
| V2-005 | Life Event Foundation V1 | ✅ | Issue #146 / PR #147：独立 LifeEvent authority、显式 CRUD、owner-safe Place、confirmed-Memory evidence、export/delete lifecycle 与 PostgreSQL race/migration gates 已正式审查并合并；merge `6df2514c43d4709e01f0c52049ce12ba23c3e170` |
| V2-006 | Life Stage Foundation V1 | ✅ | Issue #148 / PR #149：explicit overlapping/open-ended LifeStage authority、explicit LifeEvent evidence、export/delete lifecycle 与 PostgreSQL race/migration gates 已正式审查并合并；merge `86127a101028ef9dadf397ef454edc8126082a91` |
| V2-007 | Evidence-backed Long-term Reasoning Foundation V1 | ✅ | Issue #150 / PR #151：Stage-scoped explicit Stage/Event/AnswerTrust-qualified Memory inventory、opaque citations、strict provider contract 与 post-provider full-inventory revalidation 已正式审查并合并；merge `1c1f74535eb1e4bae3e98eefe24c730d42efd401` |
| V2-008 | Person Known Duration V1 — “我认识某人多久了” | ✅ | Issue #152 / PR #153：最早 trusted explicit MET + S3-013 + Memory.occurred_at deterministic no-guess duration 已正式审查并合并；merge `7bf91baef1638f71438f0cd1d5aa71faa80c1db3` |
| V2-009 | Cross-year Evidence Timeline V1 — “过去几年发生了什么” | ✅ | Issue #154 / PR #155：显式 LifeEvent / LifeStage START/END boundary、user-local year bounds、server-owned as_of、opaque keyset cursor 与 bounded three-source merge 已正式审查并合并；merge `e7c7f4740c358c9d7d057da883b503b681c9c72c` |
| V2-010 | Annual Electronic Memoir V1 — 年度电子回忆录 | ✅ | Issue #156 / PR #157：复用 S3-017 Annual Summary + V2-009 timeline + verified PHOTO media gallery 已正式审查并合并；merge `0495112b17d91fb4540048eaa7288047db40fe85` |
| V2-011 | Life Memoir Foundation V1 — 人生回忆录 | ✅ | Issue #158 / PR #159：explicit LifeStage chapter index + on-demand cited stage memoir via canonical V2-007 已正式审查并合并；merge `6df3a6654f14e715db8e3887582b1f83de78cd7c` |
| V2-CLOSE | V2 Final Closeout / Productization Review | ✅ | Issue #160 / PR #164 已正式合并；merge `8e463566068e8fc328b86b816576ec907f8d3911`；V2 Personal Memory Graph V1 formally closed |
| V2-P0-OBS | Production Observability Foundation V1 | ✅ | Issue #161 / PR #170 已正式审查并合并；merge `91e2c8b044912bb61ecada7d679c9054db64df7c`；request correlation、structured JSON telemetry、AI/storage/delete operational events、bounded DB readiness 与 production healthcheck 已收口 |
| V2-P1-MINI | Mini Program advanced V2 surfaces | ✅ | Issue #162 / PR #175 已完成三轮正式极窄复审并合并；merge `7c4ba02b64de67f3627980c3978d1ad2d68fedef`；LifeEvent/LifeStage、Known Duration、Long-term Reasoning、Cross-year History、Annual/Life Memoir 与 strict parser/stale-race 边界已收口 |
| V2-P1-FLUTTER | Flutter Personal Memory Graph parity | ✅ | Issue #163 / PR #176 已完成两轮正式极窄复审并合并；merge `ce0f1578ad3217cb08d5ae7ae7a81d94f33d2d57`；11 条 V2 flow、strict parser、SEC-013、stale authority、single-flight、opaque cursor、signed media、offline boundary 与 Flutter visual gates 已收口 |
| UIUX-P0-001 | JiYi Product Experience V2 | ✅ | Issue #177 / PR #178 已完成最终 extremely narrow review 并合并；merge `84e68c44c08ecea209d34b53b35569cce781ffdb`；Flutter + Mini 五域 IA、Design System V2、用户文案、small-screen/large-font/Elder/accessibility、Golden/visual regression 与 production-language regression 已收口。**此项完成不等于 2026-09-29 用户确认的 8 张高保真参考图已完成视觉还原；该视觉 fidelity 缺口由 UIUX-P0-002 单独收口。** |

---


## 6.1 Operations / Production Deployment

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| ADMIN-001 | JiYi Production Admin Console V1 | ✅ | Issue #180 / PR #181 已完成正式产品/安全审查并合并；merge `97d6a3559a9ab5726acf3e8e8cc27c4c96095869`。独立 Admin 身份/RBAC、Dashboard、用户/家庭/会员与额度、删除/注销、安全中心、AI/ASR/检索/存储/系统健康、审计、受控设置、Admin visual regression 已收口。 |
| OPS-002 | Durable Job & Maintenance Worker Foundation V1 | ⬜ | **P0 public-launch blocker**。首版优先 PostgreSQL-backed durable jobs + claim/lease worker，不强制 Redis；先接管 Data Delete progression、Account Delete 在 `local_cleanup_ready=true` 后的服务端 progression、stale PENDING media cleanup、Security Alert retry、analytics/location retention 等不能依赖客户端/人工触发的任务；第二阶段再迁移 Annual/Life Memoir、Monthly/Annual Summary、Embedding refresh 等长耗时 AI。Redis 仅作为后续 wake-up/scale 层，PostgreSQL 始终是 Job authority。 |
| OPS-001 | Production Deployment V1 | 🟠 | Issue #136 / PR #137：Docker/Compose/Caddy、production env fail-closed、migration、immutable image、backup/restore/rollback 与 CI 已合并；真实 public-server acceptance 继续作为**最终上线 Gate**，顺延到 Production Launch Hardening + OPS-005 capacity acceptance 全部完成后，以最终生产拓扑验收 DNS/TLS/private storage/client domains/backup/restore/rollback/容量。 |
### OPS-002 架构决策（2026-09-30，production-launch audit 修订）

当前 production Compose 仍为：

```text
postgres
migrate
api
reverse-proxy / Caddy
```

生产审查确认：Data Delete / Account Delete 的服务端 durable 状态机、Security Alert retry、analytics/location retention 等已有可靠业务逻辑或 CLI，但没有 scheduler/worker 自动推进；同时 OCR/Vision/ASR/Embedding/Summary/Memoir 中仍存在请求内 Provider I/O。

首版 OPS-002 不直接强制 Redis。对首台 2C2G 环境，优先：

```text
PostgreSQL = durable job authority / lease / retry truth
Worker     = executor + scheduler
Redis      = optional future wake-up / scale layer
```

第一阶段 worker 负责：

```text
Data Delete progression
Account Delete progression（仅在客户端已完成本机 owner purge，并持久化 local_cleanup_ready=true 后）
stale PENDING media cleanup
Security Alert retry
Analytics retention
Location retention
其他明确的 bounded maintenance
```

Account Delete 必须保留现有：

```text
PREPARE
→ client local owner purge
→ local_cleanup_ready=true
→ server durable progression
```

Worker 不得绕过本机清理确认边界。

第二阶段再将天然异步的长任务迁移到 worker：

```text
Annual / Life Memoir
Monthly / Annual Summary
Embedding refresh
随后 Vision / OCR / ASR / Daily Summary / Long-term Reasoning
```

普通交互式 Memory Query 保持同步，除非真实负载数据证明需要改变。

所有 worker job 必须在 claim、外部 I/O 前、外部 I/O 后、commit 前重新验证必要的 owner/resource revision/deletion/privacy authority。Data Delete / Account Delete 后，旧 queued/running job 不得重新生成或重新发布已删除用户数据。

OPS-002 不以“5000/10000 DAU”作为单一启动条件；正式规模化判断看 provider peak concurrency、P95/P99 latency、timeout、429/5xx、retry volume 与 API long-request concurrency。

---

## 6.2 Production Launch Hardening（2026-09-30 production audit）

> 目标：服务器可以继续作为 staging / production-acceptance 环境部署，但在以下 P0 完成前不开放无约束公网注册/正式放量。P1 原则上在 #136 最终验收前收口；P2 不阻断第一版公网，但进入后续性能清单。

| ID | 优先级 | 功能 / 风险 | 状态 | 冻结结论 |
| --- | --- | --- | --- | --- |
| AUTH-001 | P0 | Public Auth & Persistent Session Hardening | ✅ | Issue #182 / PR #183 已完成正式安全审查并合并；merge `d20617973499c2a04cede58016999f31d331bdfc`。durable server session、15 分钟短 JWT、opaque refresh rotation/replay revoke、logout/logout-all/revoke、邮箱验证/密码恢复、Keychain/Keystore secure persistence、cold-start server-authoritative restore、并发 refresh exactly-one-success 与 stale-refresh/logout/account-switch 竞态均已收口。 |
| AUTH-002 | P0* | WeChat Mini Program Identity | ⬜ | 若微信小程序作为正式主入口，则在公开发布前加入 `WECHAT_MINIPROGRAM` AuthIdentity：`wx.login → code2session → stable provider subject → User`；微信 secret 仅服务端。若小程序不是首发主入口，可降为 P1。 |
| AUTH-003 | P0* | Phone Number + SMS OTP Login | ⬜ | 当前只有邮箱+密码认证；`users.phone` 仅是资料字段，尚未接入手机号 AuthIdentity、短信验证码发送/校验、过期/重放/频率限制、阿里云 SMS 服务端凭证和 Flutter/小程序登录入口。若手机号是正式主登录方式，公开发布前必须完成；短信密钥只能放服务端。 |
| AUTH-004 | P0* | Native WeChat Login for Flutter Android/iOS | ⏸ | 后期配置，当前不阻塞主线开发。届时需完成 Android/iOS SDK 注册、`wxlogin` 回调、服务端 `code → openid/unionid → AuthIdentity → session`，并配置 Android 包签名、iOS Universal Link、微信 AppID；微信 secret 仅服务端。 |
| BIZ-011 | P0 | Production Registration Entitlement Default | ✅ | **Issue #197 / PR #199 已正式审查并合并 `main=f805848ba16af786b3d15a6ae26d5dc3d399aa95`**。正式 `register_email_password()` 使用 canonical `FREE` initial entitlement；User + AuthIdentity + Entitlement 保持同事务原子提交。`LEGACY_FULL` 仅历史兼容/migration/dev-only 明确路径可用，现有历史用户不做批量降级或登录时重写。 |
| OPS-002 | P0 | Durable Job & Maintenance Worker Foundation V1 | ⬜ | PostgreSQL-backed durable job/lease 优先；服务端自动推进 deletion/maintenance，并逐步异步化长耗时 AI。客户端只能发起/查询状态，不再承担服务端任务推进责任。 |
| SEC-016 | P0 | Authenticated API Abuse & Provider Concurrency Guard | ✅ | **Issue #202 / PR #203 已正式审查并合并 `7b61e0a93e1f8f4a6be1e65cc30904cb841ef33b`**。authenticated per-user/per-IP/route-class 限流、AI/ASR/Embedding 跨 Uvicorn worker durable permit/lease、全局 Argon2 concurrency、429+Retry-After 及 PostgreSQL 真实竞态 Gate 已收口；最终审查 P0/P1/P2=0/0/0。 |
| OPS-003 | P0 | Off-host Backup & Scheduled Operations | ⬜ | 当前 pg_dump 默认写本机目录。增加私有异地 COS/OSS backup bucket、保留策略、校验、自动上传与定期 restore drill；本机短期备份仅作为一层缓存，不能是唯一灾备。 |
| MEDIA-001 | P1 | AI Media Input & Stale Upload Hardening | ⬜ | 原始图片存储上限与 AI 分析输入上限分离；增加 `AI_IMAGE_MAX_BYTES`/analysis derivative（缩放压缩，原图保留），避免 20MB→base64 大请求与 30s provider timeout/3M 出口冲突；stale PENDING upload 按 presign expiry + quiet settle + object absence 安全回收并释放 quota reservation。 |
| API-001 | P1 | Export & Legacy Pagination Hardening | ⬜ | 当前 Data Export 虽有 section 5000 行硬上限，但仍同步将多 section 装入内存并返回 JSON；改为 async ExportJob→private object storage→短时签名下载，或至少真正 streaming。统一审计旧 API，无界列表（已确认 `GET /objects`）补 `limit + opaque cursor + stable order`。 |
| SEC-017 | P1 | Human Security Alert Delivery | ⬜ | 当前 durable Security Alert 的 delivery adapter 实际为结构化日志 stream；ADMIN-001 Security Center 可承接查看，但 HIGH/CRITICAL 至少接一个真实人类通知渠道（飞书/企业微信/邮件等），并保留 durable retry/backoff。 |
| REM-001 | P1/P0* | Reminder Delivery / Product Promise Gate | ⬜ | 当前 Reminder 有 PENDING/DONE/CANCELLED/remind_at，但未形成到点扫描→Push/微信订阅/APNs/FCM 的正式 delivery。若正式 UI 承诺“到点提醒”，则升级为 P0 并在上线前实现；否则首发必须明确降级/隐藏通知承诺。 |
| OPS-004 | P1 | Production Runtime Guardrails | ⬜ | Compose 增加日志 rotation；SQLAlchemy 显式 `DB_POOL_SIZE/DB_MAX_OVERFLOW/POOL_TIMEOUT/RECYCLE`；Caddy 增 HSTS、X-Content-Type-Options、Referrer-Policy 与合理 API body ceiling。Provider process-lifetime HTTP client pooling 记为 P2 性能优化，可后续完成。 |
| OPS-005 | P0 Gate | Production Capacity Acceptance | ⬜ | #136 前在真实目标规格（当前计划 2C2G3M）执行可重复的容量测试；至少 50/100/200 concurrent mixed workload，记录 CPU/RAM/Swap/Postgres connections/DB latency/API P50/P95/P99/5xx/429/provider latency/OOM/network，得到实测安全容量，不用 DAU 估算替代。 |
| CORE-001 | P0 | Passive Memory Reliability V1 | ✅ | **Issue #184 / PR #185 已完成并合并**。已实现单一 shared/passive delivery authority、SQLite durable delivery lease/attempt diagnostics、Native Queue V2/backpressure、Android WorkManager watchdog + boot/package-replace/process-death recovery、iOS relaunch/privacy quarantine recovery、stable UUID replay、cross-engine secure-session owner binding，以及 foreground/background 统一 AUTH/Privacy/upload authority；正式审查 P0/P1/P2 = 0/0/0，exact-head CI 全绿。 |
| CORE-002 | P0 | Historical Day Footprint & Natural-language Date Query V1 | ✅ | **Issue #186 / PR #187 已完成并合并**。已落地 canonical `DayFootprintService(user_id, day)`、typed historical endpoint、deterministic date parser、`DATE_FOOTPRINT_QUERY`、evidence-first broad-day query，以及 Flutter/Mini 同 authority 消费；纯“我25号去哪了？”由 Visit+Place 直接回答且 LLM calls = 0，多日期/无证据/未来日期 fail closed。正式审查 P0/P1/P2 = 0/0/0，exact-head Backend/Mini/Mobile/Visual gates 全绿，latest-main replay behind=0。 |
| CORE-003 | P0 | Automatic Recording Health & Coverage V1 | ✅ | **Issue #188 / PR #189 已完成并合并**。统一复用 CORE-001 producer/runtime、permission/location services、Privacy、native/SQLite queue、delivery/backpressure/recovery authority，建立 owner-scoped `RecordingHealthSnapshot`；确定性输出 HEALTHY/DEGRADED/PAUSED/BLOCKED/RECOVERING/UNKNOWN，UNKNOWN 不得伪装 healthy；增加 evidence-derived Today Coverage、gap reason、Healthy Days、Location Gap Hours 与 Flutter 记录状态 UI，Mini 只展示 server-observed authority。正式审查 P0/P1/P2 = 0/0/0。 |
| CORE-004 | P0 Gate | Passive Recording Real-device Certification V1 | ⏸ | **Issue #190 保留为未来 P0 Gate；PR #191 已关闭且未合并。** 当前不启动正式 24h/72h/12h 长时认证，先完成真机暴露问题、Provider/服务端配置和其他短周期上线收口；待 Android+iOS 基础闭环与测试环境稳定后，从当时最新 `main` 新建干净 certification PR/构建，并重新执行完整物理设备矩阵。模拟器、mock、CI 仍不得替代真机认证证据。 |
| UIUX-P0-002 | P0 Product Gate | JiYi Consumer Visual Fidelity V1 | 🔵 | **当前主线 / Issue #204**。8 张用户确认高保真参考图为 Consumer Visual Design Authority；Flutter 优先恢复山水/晨曦品牌氛围、photo-first、真实足迹地图、层叠卡片和消费者产品质感。新增硬验收：Today/Place/Memory/Query/Summary/Memoir 在有真实坐标 authority 时使用真实高德地图；照片展示走 owner-scoped 本机持久缓存，cache miss 才签名下载，禁止业务 UI 反复直连 COS signed URL。Golden 将以新视觉为基准重置。 |
| PROD-001 | P1 | Core Product Positioning & Promise Refresh | ✅ | **Issue #198 / PR #200 已正式审查并合并 `main=76a525d600ffa94cad1bc35e638c49657341a005`**。公开定位已统一为“自动记录生活、需要时帮助找回过去”的个人/家庭长期记忆产品；结构化事实/Evidence 为事实来源，AI 仅辅助搜索、整理、总结和表达；绝对自动记录承诺被明确禁止，CORE-004 长期真机认证状态保持真实。 |
| ADMIN-002 | P0/P1 Ops | Provider Configuration V1 | ✅ | **Issue #196 / PR #201 已正式审查并合并 `e1ec4f392fad180cfd92c0653d9f0d38972ba736`**。AI/ASR/Embedding/RAG 已具备 SUPER_ADMIN-only 在线配置、write-only 加密凭证、revision/CAS、多 worker bounded cache convergence、exact-fingerprint runtime evidence 与 bounded/idempotent Embedding backfill；最终审查 P0/P1/P2=0/0/0。 |

### Public launch 顺序

```text
ADMIN-001
→ AUTH-001 persistent session
→ CORE-001 Passive Memory Reliability
→ CORE-002 Historical Day Footprint / Date Query
→ CORE-003 Recording Health
→ CORE-004 real-device certification
→ UIUX-P0-002 Consumer Visual Fidelity V1
→ AUTH-002（若 Mini 为首发主入口）
→ AUTH-003（若手机号为正式主登录入口）
→ AUTH-004（后期配置，正式启用 Flutter 微信登录时再纳入）
→ BIZ-011
→ OPS-002
→ SEC-016
→ OPS-003
→ MEDIA-001 / API-001 / SEC-017 / REM-001 decision / OPS-004 / PROD-001
→ OPS-005 Production Capacity Acceptance
→ #136 OPS-001 real-environment Production Acceptance
→ public/commercial rollout
→ V3
```

### UIUX-P0-002 Consumer Visual Authority

本任务的视觉基准不是当前简化版 Flutter Golden，而是 **2026-09-29 用户确认的 8 张高保真消费者 APP 参考图**：

```text
Today / 今天
Timeline / 时间线
Memory Detail / 记忆详情
Family / 家庭
Memory Query / 问记忆
Unified Capture / 帮我记一下
Summary / 回忆总结
Profile / 我的
```

冻结原则：

```text
业务 authority / AUTH / Privacy / Family grant 不改
UIUX-P0-001 五域 IA 不推翻
没有真实数据 authority 的字段可以删/降级
但整体视觉构图、品牌氛围、photo-first 叙事、足迹地图主视觉与卡片层次必须忠实恢复

Visual CI PASS
!=
符合 Design Authority

新的 Golden / visual artifact 必须以 UIUX-P0-002 完成后的视觉为基准
```
### 非阻断 P2

```text
Provider HTTP client process-lifetime pooling / keep-alive / connection limits
更细的 Worker 拆分与 Redis wake-up layer
iOS CLVisit / startMonitoringVisits() 低功耗信号可行性研究（仅作 Visit 候选辅助，server Visit 聚类继续是统一 authority）
更高阶 autoscaling / multi-node / Kubernetes 等
```

## 6.3 Core Product Closure（2026-09-30 core-product audit）

产品总原则冻结为：

> **自动记录用户真实生活，在用户需要的时候帮他找回来。**

工程判断优先级：

```text
自动记得住
> 数据不丢
> 停留识别准确
> 耗电可接受
> 需要时找得到
> 答案可信
> 更多 AI 花样
```

现有地基继续保留，不做推倒重构：

```text
LocationPoint / Visit / Place
Timeline / Today Footprint
Privacy Pause
Raw Location Retention
Adaptive Sampling
Native Location Bridge
Offline Queue / stable client_uuid
Structured Retrieval / Evidence Ranking / Answer Trust
NO EVIDENCE → NO MEMORY
Family Permission
Data Delete / Account Delete
```

### CORE-001 关键安全边界

后台恢复/上传不得为了“自动化”绕过隐私：

```text
secure session restore
→ exact owner restore
→ native permission/runtime check
→ fresh server Privacy authority
→ PASS 才允许 producer/upload
```

失败、token refresh 失败、owner mismatch、Privacy Pause、permission revoke 均 fail closed。原生队列不得因为达到容量静默形成不可见记忆缺口；必须有 backpressure/drop diagnostics 与 Recording Health 告警。

Android recovery 必须符合当前平台后台启动限制，不能简单用 BootReceiver 无条件拉起 location FGS。iOS location relaunch 继续保持“先 quarantine，后 server privacy revalidation，再恢复”的既有安全思路。

### CORE-002 结构化查询原则

```text
“我25号去哪了？”
Question
→ deterministic date parse
→ server timezone day bounds
→ DayFootprint
→ Visit + Place
→ structured answer
→ LLM calls = 0
```

```text
“25号发生了什么？”
DayFootprint
+ Memory
+ Photo metadata
+ Voice
→ bounded Evidence Set
→ optional AI summary
```

AI 永远不是生活事实来源。

### Product metrics

传统 DAU/打开时长继续保留运营参考，但核心新增：

```text
Memory Coverage Rate
Location Coverage
Visit Coverage
Automatic Recording Healthy Days
Location Gap Hours
Query Success Rate
Evidence-backed Answer Rate
False Memory Rate
User Correction Rate
```

对迹忆而言，“几天不打开 App，之后 10 秒找回真实一天”可以是成功体验，不以高打开时长作为唯一目标。


## 6.4 Passive Context & Activity Memory（自动生活上下文）

> **产品目标扩展：不仅记住“去了哪里”，还要在用户明确授权、证据足够时帮助记住“那段时间大概在做什么”。** 任何活动/行为推断都必须区分“系统直接活动信号”“结构化推断”“用户确认事实”，禁止把传感器猜测直接写成确认的人生事实。

| ID | 优先级 | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| PLACE-INTEL-001 | P1 | Frequent Places & Place Insights V1 | ⬜ | 基于已有 Place/Visit，不重做定位。增加最近 7/30/90 天 visit_count、total_duration、首次/最近到访、常见到达/离开时段、工作日/周末到访、frequent_score 与“我的地点/常去地点”排序。HOME/WORK 只生成候选，必须用户确认后才能成为事实；支持“最近常去、第一次去、很久没去、本月最常去”等回忆产品能力。 |
| AUTO-CONTEXT-001 | P1 | Native Activity Recognition V1 | ⬜ | 当前 MotionState 主要由 GPS speed/accuracy 推断。升级为系统原生活动信号：iOS 接入 Core Motion CMMotionActivityManager（stationary/walking/running/cycling/automotive/unknown）；Android 优先 Activity Recognition Transition API（STILL/WALKING/RUNNING/ON_BICYCLE/IN_VEHICLE）。活动信号作为 Evidence/Context，不直接升级为 Memory 事实；保留现有 speed-based fallback，国内无 Google Play Services 设备必须有 vendor-neutral fallback。 |
| AUTO-CONTEXT-002 | P1 | Activity Segment Derivation V1 | ⬜ | 将低功耗 activity transition + Location/Visit 聚合成 ActivitySegment 候选，例如“步行 08:10–08:28”“乘车 08:30–09:05”“跑步 19:12–19:48”。要求 confidence/source/start/end，可被用户纠正。活动段与 Visit/Place/Timeline 对齐，回答“我那天怎么去的/运动了多久”等问题；低置信度只展示“可能”。 |
| AUTO-CONTEXT-003 | P1/P2 Opt-in | Steps & Exercise Context V1 | ⬜ | 用户单独授权后读取 iOS HealthKit / Android Health Connect 的步数、运动/Workout/Exercise Session、距离等高层数据，用于“今天走了多少、跑步/骑行多久、这次运动在哪里”等生活上下文。健康权限按类型渐进请求，不与位置授权捆绑；未授权不影响迹忆核心功能。首版只读必要的活动数据，不采集临床/诊断信息。 |
| AUTO-CONTEXT-004 | P2 Opt-in | Sleep / Day-boundary Context V1 | ⬜ | 仅用户主动开启后读取 HealthKit/Health Connect 的睡眠 session 作为“睡觉/起床”时间边界和日记上下文，可生成“昨晚睡眠时间段”候选。睡眠属于敏感健康数据，默认关闭、单独解释用途、最小化存储；不得据此进行医疗诊断或健康结论。 |
| AUTO-CONTEXT-005 | P1 | Passive Photo Context V1 | ⬜ | 与 GROW-001 联动。经明确照片权限后，优先本机增量读取新照片的拍摄时间、EXIF 地点、媒体类型等 metadata，形成“这段时间拍了几张照片/可能发生了一次旅行或聚会”的候选上下文；默认不把整个相册原图自动上传。Vision 仅在用户授权且需要时分析选择的媒体，推断不得无 Evidence 写事实。 |
| AUTO-CONTEXT-006 | P1/P2 Opt-in | Calendar Context V1 | ⬜ | 用户单独授权后读取日历事件的时间、标题和地点，用于辅助解释某个 Visit/ActivitySegment，例如“14:00–15:00 日历有牙医预约”。Calendar 只作为来源明确的 Context/Evidence，不自动把计划当成“实际发生”；需要位置/活动证据或用户确认才能形成已发生事实。 |
| AUTO-CONTEXT-007 | P1 | Environmental Context Enrichment V1 | ⬜ | 使用已有时间+地点在服务端补充天气、城市/区域、节假日等公共环境信息，让回忆从“去过哪里”变成“那天下雨、去了哪里、拍了哪些照片”。此类数据不要求额外传感器权限，但必须绑定具体时间/地点来源并可重算；天气等第三方数据不得成为用户行为事实。 |
| AUTO-CONTEXT-008 | P1 | Daily Life Reconstruction V1 | ⬜ | 将 DayFootprint + ActivitySegment + Photo Context + Calendar Context + 用户主动 Memory 组成 evidence-first 的 DailyLifeSnapshot。结构化层先生成“去了哪里 / 如何移动 / 有哪些活动 / 拍了什么 / 有什么日程”，AI 只负责可选总结。典型目标：回答“我25号去了哪里、怎么去的、做了些什么？”并逐条展示来源和可信度。 |
| AUTO-CONTEXT-009 | Research / P2 | iOS CLVisit Signal | ⬜ | 评估并接入 startMonitoringVisits() 作为 iOS 低功耗 Visit candidate，辅助现有 Significant Location Change + Standard Location。CLVisit 只提供候选信号，服务端 Visit 聚类仍是跨 iOS/Android 的统一 authority。 |
| AUTO-CONTEXT-010 | 🚫 V1 | Continuous Audio / Camera Body-posture Tracking | 🚫 | V1 不做 24 小时麦克风监听、后台摄像头体态识别或隐蔽环境录音。手机单独放置位置无法可靠代表人体坐/站/躺，不能把手机倾斜等信号冒充“人体姿态事实”。未来若有可穿戴设备，可在用户明确授权下研究更可靠姿态/活动输入。 |

### 自动行为识别可信度分层

```text
Level A — 系统/传感器直接信号
位置点、Visit、Core Motion / Activity Recognition、步数、Workout、照片拍摄时间

Level B — 确定性结构化派生
连续步行段、乘车段、到访次数、停留时长、常去地点、路线切换

Level C — 上下文推断候选
“可能在通勤”
“可能在跑步”
“可能在餐厅吃饭”
“可能参加了日历里的会议”

Level D — 用户确认事实
“这是公司”
“那天在和老张吃饭”
“这段是晨跑”
```

规则：

- A/B 可以自动形成结构化 Context，但必须保留 source/confidence。
- C 只能作为候选或问用户确认，不能直接写为 confirmed Memory。
- D 才能成为最高权重用户事实。
- “地点类型 = 餐厅”不等于“用户一定在吃饭”；“学校停留”不等于“用户在上课”；“静止”不等于“坐着”。
- 不为了“记录更多”而无限申请权限。每一种新数据源都必须能解释“为什么迹忆需要它”，且用户可单独关闭。


---

# 7. V3：AI 人生助手与硬件扩展

| ID | 功能 | 状态 | 说明 |
| --- | --- | --- | --- |
| V3-001 | AI 人生助手 | ⬜ | 跨多年记忆查询与整理 |
| V3-002 | “过去十年”总结 | ⬜ | 长期时间范围分析 |
| V3-003 | 家庭数字档案 | ⬜ | 需要更严格的权限与继承设计 |
| V3-004 | 记忆按钮 / 迹忆记忆夹 | ⏸ | APP 验证需求后进入 7.1 Hardware Roadmap；优先低成本身体佩戴传感器，不直接做智能手表 |
| V3-005 | 可穿戴快捷语音记录 | ⏸ | 仅用户主动按键触发的短语音/记忆标记；不做 24 小时录音，详见 HW-003 |
| V3-006 | 实体回忆录打印 | ⏸ | 商业化扩展 |

## 7.1 Hardware Roadmap（软硬件结合）

> **硬件原则：硬件必须补足手机 App 做不好的事情，而不是重复造一台手机或手表。** 迹忆硬件的第一目标是让“自动记住去了哪里、怎么移动、关键时刻做了什么”更可靠、摩擦更低；第二目标才是硬件销售收入。商业上优先形成“硬件一次性毛利 + PERSONAL/FAMILY 持续订阅”的双层收入。

### 分阶段路线

| ID | 阶段 | 功能 / 产品 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| HW-001 | Phase H0 | Existing Wearable Integration V1 | ⬜ | **先不造硬件。** Apple Watch 通过 watchOS + HealthKit/Workout/用户授权活动数据；Wear OS 通过 Health Services/Health Connect；华为用户评估 Health Kit。迹忆统一映射到 ActivitySegment / Steps / Workout / Sleep Context。Watch 端重点做“一键记一下、快捷语音、今日足迹、找回、到家/到达确认”等轻交互，不把手表做成完整 App 副本。该阶段先验证“穿戴数据是否显著提高记忆覆盖和留存”。 |
| HW-002 | Phase H1 POC | JiYi Memory Button Prototype | ⬜ | 做 20～50 台工程样机验证，不直接量产。核心器件只需要 BLE、实体按键、低功耗 MCU、IMU、RTC/时钟、震动/LED、少量本地存储和电池。单击创建可靠 MemoryMarker（时间戳 + 设备身份），双击/长按可定义为用户主动记忆动作。手机后续将 Marker 与 Location/Activity/Photo/Calendar 对齐；即使手机当时不在线，设备也要能缓存后补。 |
| HW-003 | Phase H2 | JiYi Memory Clip V1 | ⬜ | 若 HW-002 验证成立，再做第一款可销售硬件“迹忆记忆夹/记忆扣”。身体佩戴比手机更适合采集 IMU，因此用于提升步行/跑步/骑行/乘车/静止等 ActivitySegment 可信度。V1 不内置 GPS/蜂窝，复用手机位置与网络以控制成本、体积和续航；可评估加入麦克风，但**只允许实体按键主动触发短语音**，必须有明显 LED/震动反馈与本地停止机制，绝不后台常开录音；不加摄像头。 |
| HW-004 | Phase H2 | Hardware Secure Pairing / Sync / OTA | ⬜ | 建立 Device authority：per-device key、owner binding、BLE secure pairing、anti-replay、event sequence、离线队列、signed firmware/OTA、失窃解绑/撤销、恢复出厂、battery/firmware health。硬件事件只作为 Evidence/Context，不能绕过 Privacy Pause、Family Permission 或用户身份。 |
| HW-005 | Phase H2 Commercial | Hardware + Membership Bundle V1 | ⬜ | 后端将 `HardwareProduct`、实物订单、设备 ownership 与 PERSONAL/FAMILY Entitlement 分开建模，即使前台作为套装销售也不得把“买了某设备”硬编码成永久会员。建议首款 Memory Clip 目标零售价区间 ¥399～499；首发可测试“设备 + 1年 PERSONAL”约 ¥499 左右，家庭双设备 + FAMILY 年费可测试 ¥799～899。**这些只是商业测算基线，不在拿到 ODM/BOM/渠道报价前冻结。** |
| HW-006 | Phase H3 | Family / Elder Wearable | ⏸ | 用户规模和硬件售后体系成熟后，再评估长辈/家庭版本：更大的按键、语音记忆、到家/离家、家庭提醒等。独立 LTE/eSIM、GNSS、SOS、跌倒检测属于更高责任与认证等级，不能作为第一代硬件；如未来进入，应另立安全/误报/续航/通信资费/认证 Gate，避免把“记忆产品”贸然变成生命安全设备。 |
| HW-007 | Phase H3 | Standalone Smartwatch / Always-on AI Pendant | 🚫 Early | **前期不做自研智能手表，也不做全天录音 AI 挂件。** 智能手表与手机能力重叠，研发/屏幕/OS/功耗/认证/售后成本高；全天录音带来巨大隐私、审核、存储和社会接受风险。只有当现有 Watch 集成和 Memory Clip 已证明有明确付费需求后才重新评估。 |

### 第一方硬件应该补足的能力

```text
手机 App 擅长：
定位 / 地图 / 网络 / 照片 / 日历 / AI / 展示

手表生态擅长：
心率 / 步数 / Workout / 活动 / 睡眠 / 抬腕交互

迹忆第一方硬件擅长：
身体佩戴 IMU
关键时刻实体按键
低摩擦 MemoryMarker
离线缓存
（可选）主动按键短语音

融合后：
Where + How + What + User Mark
→ DailyLifeSnapshot
```

### Memory Clip V1 建议边界

首代优先包含：

```text
BLE
6-axis IMU
physical button
RTC / timestamp
haptic / LED
local event queue
battery telemetry
signed firmware / OTA
```

首代原则上不包含：

```text
camera
always-on microphone
LTE/eSIM
independent GNSS
large display
open app platform
```

原因是这些器件会显著增加 BOM、功耗、体积、认证和售后，而手机已经能承担定位、联网、地图和 AI。

### 商业模型与毛利目标

目标不是靠硬件一次性收入替代订阅，而是：

```text
FREE App
→ 用户确认长期价值
→ PERSONAL / FAMILY
→ 可选 Memory Clip
→ 更高 Memory Coverage / 留存
→ 下一年继续订阅
```

首款量产商业 Gate 建议：

```text
目标 DTC 硬件毛利率      >= 55%
目标 landed COGS         <= 零售价的 30%～35%
典型使用续航目标          >= 7 天（最终以 EVT/DVT 实测冻结）
30 天硬件活跃率           必须显著高于纯 App 对照
佩戴后 Memory Coverage    必须有可测提升
退货/故障/电池投诉        必须在量产前形成可接受基线
```

若最终 Memory Clip 零售价为 ¥399～499，则设计阶段应倒推 BOM/组装/包装/认证摊销/物流成本，而不是硬件做好以后再决定售价。实际 BOM 与毛利只在 ODM 报价和 EVT/DVT 后冻结。

### 推荐销售结构（待后期商业化验证）

```text
软件：FREE                         ¥0
软件：PERSONAL                     按现有商业定价
软件：FAMILY                       按现有商业定价

Memory Clip                        ¥399～499 target
Memory Clip + PERSONAL 1年          ~¥499 target
2 × Memory Clip + FAMILY 1年        ~¥799～899 target
```

物理硬件订单与数字会员必须保持后台 authority 分离；iOS/Android 店内展示、兑换、跨平台 entitlement 与支付路径在实际销售前按当时商店政策重新审查。

### 硬件量产 Gate

```text
H0 现有 Watch / Health integration
→ 验证穿戴数据能否提高 Memory Coverage

H1 EVT / POC 20～50 台
→ BLE / IMU / Marker / battery / sync 实测

H2 DVT 100～300 台
→ 外壳 / 续航 / 跌落 / 防汗 / OTA / 量产测试

H2.5 小批量 500～1000 台
→ 真实用户 30～90 天留存、故障、退货、佩戴率验证

PASS
→ 才进入正式量产
```

硬件安全/隐私硬约束：

- 不出售、广告化或画像化用户的 HealthKit/Health Connect/运动/睡眠数据。
- 健康数据权限必须逐类、按需申请；拒绝后仍可使用迹忆核心记录功能。
- 硬件采集的数据默认 owner-scoped；Family 共享必须二次授权。
- 所有传感器推断继续遵守 AUTO-CONTEXT 的 A/B/C/D 可信度分层。
- 物理设备丢失后必须可以服务端 revoke；新 owner 绑定不能继承上一用户数据。

---

# 8. 隐私、安全与合规（贯穿所有阶段）

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| SEC-001 | HTTPS / TLS | 🟠 | Caddy/production 部署代码与 provider endpoint HTTPS fail-closed 已实现并有 CI；真实 DNS/证书/public endpoint 尚未验收 |
| SEC-002 | 对象存储私有桶 | 🟠 | 代码已按私有桶 + 服务端 key + fail-closed 设计实现；仍需真实 provider 部署验收 |
| SEC-003 | 临时签名下载 URL | 🟠 | 短时 PUT/GET 已实现；微信 API + signed PUT 合法域名及真实 COS/OSS 真机闭环仍需部署验收 |
| SEC-004 | 敏感数据权限隔离 | 🟠 | owner isolation、Family exact-grant、Privacy Pause 与多类敏感读取边界已实现；尚无覆盖所有未来敏感域的统一策略层 |
| SEC-005 | 服务端访问审计 | 🟠 | Family 敏感读取已有 FamilyAccessAuditEvent / audit API；尚未形成所有敏感读取统一审计与 production observability |
| SEC-006 | 数据导出 | ✅ | PR #12 已合并；当前认证用户可导出版本化 JSON，严格 owner 隔离且不泄露内部 Storage 字段 |
| SEC-007 | 数据彻底删除 | ✅ | PR #28 已实现 durable DB / Storage 全删除、partial-failure retry、MemoryEdit 审计清理并通过 exact-head CI 后合并 |
| SEC-008 | 账户注销 | ✅ | M / S1-022 / Issue #31 / PR #32 已完成两轮正式审查并合并；S1-021 数据清理先行、身份最终同事务删除、恢复 token、竞争删除 fail closed、旧 token 失效及本地 producer/sync/onboarding quiesce + owner purge 均有回归 |
| SEC-009 | 位置权限单独同意 | 🟠 | Flutter 原生定位 progressive permission / privacy lifecycle 已实现并有 Mobile CI；真实生产签名包与平台权限验收仍待 OPS-001 real-env acceptance |
| SEC-010 | 家庭查看逐项授权 | ✅ | Issue #95 / PR #96 已完成 default-deny per-scope foundation、canonical membership locks、committed persisted-state resolver、PostgreSQL Family Gate 与 exact-head #575（454 passed）；已合并 `main=c933f2a6`，真实敏感读取按 S4-004+ 分阶段接入 |
| SEC-011 | 记忆暂停 | ✅ | 暂停/恢复、PrivacyPauseInterval 历史门禁与时区边界均已合并 |
| SEC-012 | AI 不知道就说不知道 | ✅ | RAG、Daily/Monthly/Annual Summary、V2-007/010/011 已形成 evidence-only、bounded inventory、opaque slots、strict citation、post-provider revalidation 与 fail-closed typed status；无证据/证据不完整不生成可信答案 |
| SEC-013 | AI 推断显式标记 | ✅ | Issue #166 / PR #174 已完成两轮正式极窄复审并合并；merge `7ae43003f817932e38c7d9ef07ea9ce2b67eeee5`；deterministic Query 明确不标 AI，四态 contract 用于 Trusted Summary 与后续真实 AI surfaces |
| SEC-014 | 敏感操作二次确认 | ✅ | Issue #167 / PR #179 已完成两轮正式 security review 并合并；merge `2080174f0b0fed4181efe467897f3f64a62450f5`；Account Delete 全事务 session binding、Family/Emergency stale publish suppression、Location fresh privacy/native authority、跨端 second-confirm/single-flight/idempotency 已收口 |
| SEC-015 | 安全事件与异常访问告警 | ✅ | Issue #165 / PR #171 已完成两轮正式极窄复审并合并；merge `75ec2f73084cd4b7d9f4035ae1beeca3f209cae7`；durable anomaly windows、elapsed cooldown、HMAC correlation、Auth/Family/Delete/Storage signals 与 bounded retry 已收口 |

## 8.1 国内用户上线专项

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| CN-001 | APP / 小程序备案与主体资料 | ⬜ | 国内公开分发前核对 APP 备案、网站/接口备案、主体资质、应用商店开发者资料、隐私政策发布地址与客服投诉渠道；具体备案类别由运营主体和服务形态确认。 |
| CN-002 | 中文隐私政策与权限/SDK清单 | ⬜ | 将定位、后台定位、照片、麦克风、语音、设备标识、短信/微信 SDK、对象存储、AI 第三方处理方逐项写明目的、频率、保存期限、共享方、用户撤回/导出/删除/注销路径，并做真机权限审计。 |
| CN-003 | 国内 AI 内容安全与投诉处置 | ⬜ | 对用户输入、语音转写、OCR、AI 总结建立敏感内容识别、人工复核/申诉、违规内容处置、审计留存和 AI 生成标识策略；不能只依赖“无证据不回答”。 |
| CN-004 | 国内推送与系统兼容 | ⬜ | Android 国内设备不能只依赖 FCM；需评估厂商推送（华为/小米/OPPO/vivo 等）或微信订阅消息，并与 REM-001 统一送达、撤回、失败重试和隐私授权。 |
| CN-005 | 国内客服、注销与数据请求闭环 | ⬜ | 在 App/小程序内提供可达客服和隐私投诉入口，定义工单、身份核验、15 个工作日内处理目标、导出/更正/删除/注销结果通知和证据留存。 |
| CN-006 | 国内网络与第三方服务实测 | ⬜ | 真实 HTTPS 域名、备案后 API、COS/OSS 合法域名、短信通道、微信回调、运营商网络、弱网/断网、国产 Android 机型和应用商店包需做生产预发布验收。 |


## 8.2 Apple App Store 上架专项

> **后置统一收口，不在当前 UIUX-P0-002 主线拆散实现。** 启动条件建议为：消费者端视觉/行为稳定、#205 完成并合并、正式 iOS Release 签名与生产后端进入预发布状态。以下项目是 **App Store submission gate**；未全部完成前，不得把“可上传 TestFlight / 可安装 IPA”表述为“已满足 App Store 正式上架条件”。

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| IOS-STORE-001 | App Store Compliance & Submission Readiness V1 | ⏸ | Apple 上架统一收口总任务。后期一次性完成 Privacy Manifest、隐私政策、第三方数据/AI consent、后台定位审核材料、App Privacy、登录政策、账号注销、IAP/StoreKit、审核账号与 Release Archive 验收；当前只登记，不启动实现。 |
| IOS-STORE-002 | Privacy Manifest & Required Reason API Audit | ⬜ | 为 iOS App target 增加并审查 `PrivacyInfo.xcprivacy`；盘点 App 自身及 Flutter/原生/高德/secure-storage 等依赖使用的 Required Reason API 与 privacy manifest。当前原生代码使用 `UserDefaults`，正式 Archive 必须以当期 Apple approved reason API 规则声明；同时导出/检查 Xcode Privacy Report，禁止漏报或使用不匹配 reason。 |
| IOS-STORE-003 | In-app Privacy Policy / User Agreement / SDK Disclosure | ⬜ | App Store Connect metadata 与 App 内均提供长期可访问的 HTTPS 隐私政策；登录/注册与“我的→隐私与权限”可进入。政策需覆盖定位/后台定位、照片、相机、麦克风/语音、对象存储、家庭授权、AI/ASR/OCR/Vision/Embedding 等处理目的、共享方、保存期限、撤回、导出、删除与注销，并列出第三方 SDK/服务清单。与 CN-002 共用 canonical 文档，避免中外两套事实漂移。 |
| IOS-STORE-004 | Third-party AI/Data Processing Explicit Consent & Revocation | ⬜ | 第一次向第三方 AI/ASR/OCR/Vision/Embedding provider 发送用户个人内容前，显示清晰的数据类别、用途、第三方类型/提供方、处理边界，并取得明确同意；服务端持久化 consent revision。拒绝/撤回后基础记录、足迹、非第三方 AI 依赖能力仍可使用；不得用会员购买替代隐私同意。Provider 变更或处理目的实质变化时需重新评估 consent。 |
| IOS-STORE-005 | AMap iOS Privacy & SDK Initialization Compliance | ⬜ | 与 UIUX-P0-002/#205 联动收口：未同意高德相关隐私披露时不得初始化/构建 AMap SDK；同意状态必须在 SDK 初始化/使用前正确应用，撤回后未来地图构建 fail closed；隐私政策列明高德 SDK 数据处理。正式 Release 还需检查 SDK privacy manifest/签名与实际版本。 |
| IOS-STORE-006 | App Store Connect App Privacy / Data Collection Mapping | ⬜ | 基于最终生产数据流逐项填写 App Privacy（Privacy Nutrition Labels）：Contact Info、User Content、Photos/Audio、Precise/Coarse Location、Identifiers、Diagnostics/Usage Data 等只按真实收集/关联/用途申报；核对第三方 SDK/provider 数据流。每次新增 SDK、广告/分析、支付或 provider 后重新审查。 |
| IOS-STORE-007 | Account Deletion Submission Readiness | ⬜ | 现有 App 内注销入口与 S1-022 durable delete 保留；上架前验证用户可在 App 内发起永久账号删除，关联个人数据/媒体按政策删除，失败/等待状态有明确说明且可恢复。优先在 OPS-002 后由服务端 durable worker 自动推进，避免依赖用户反复点击“继续注销”；同时准备审核演示路径。 |
| IOS-STORE-008 | Background Location App Review Package | ⬜ | 后台定位继续只服务于用户主动启用的“自动位置记忆”。正式审核前验证 progressive permission（When In Use → 明确启用后再申请 Always）、拒绝 Always 时 App 核心非自动能力仍可用、Privacy Pause/关闭入口真实生效、Info.plist purpose string 与实际行为一致；准备 Review Notes 解释后台定位用途、开关路径和审核复现步骤。 |
| IOS-STORE-009 | Login Policy / Sign in with Apple Review | ⬜ | 当前仅自有邮箱/密码认证时保持现状即可。若未来在 iOS 主客户端加入微信等第三方/社交登录，必须按提交时最新 App Review Guideline 4.8 重新审查，并提供符合要求的等效登录方案（通常包括 Sign in with Apple 或其他满足当期规则的方案）；不得先接微信登录后遗漏该 Gate。 |
| IOS-STORE-010 | iOS Digital Membership / StoreKit & Purchase Policy | ⬜ | PERSONAL/FAMILY/未来数字 AI 权益进入 iOS 销售前，单独完成 StoreKit/App Store IAP/订阅及服务端 Purchase→Entitlement 校验；不得直接照搬微信/支付宝的 App 内数字解锁路径。最终实现以提交时 Apple storefront、entitlement、external-purchase 等最新规则为准，避免把会变化的商店政策硬编码进 Plan authority。与 BIZ-017 联动。 |
| IOS-STORE-011 | Release Archive / Reviewer Access / Submission Evidence | ⬜ | 使用正式 Bundle ID、Distribution 签名和 production 配置生成最终 Archive；验证无测试密钥/调试入口/私有 API/真实 secret 泄漏，Privacy Report 与权限用途一致。提供稳定审核账号、可用生产/审核后端、Review Notes、后台定位/注销/AI consent 的操作步骤、Support URL/Privacy URL、必要截图和联系信息。 |
| IOS-STORE-012 | Final iOS Real-device & Store-readiness Gate | ⬜ | #205/相关客户端收口后重新执行 iOS 真机稳定性与关键路径验收：登录/refresh、冷启动恢复、照片上传与本地缓存、自动位置记忆、后台唤醒/恢复、高德地图、Privacy Pause、AI consent、账号注销。CORE-004 长时认证仍按其独立 P0 Gate 执行；正式提交不得以模拟器/无签名 IPA 代替最终 Release 包真机证据。 |
| APP-ID-001 | Production Application Identity Migration — `com.jiyidays` | ⏸ | **后期统一迁移，当前不改 #205 / 测试包。** 当前 Android `applicationId` 与 iOS Bundle ID 为 `cn.jiyidashi.jiyidashi`；V1 正式生产目标暂冻结为 `com.jiyidays`，商店展示名仍为“迹忆”。迁移必须一次性核对 Android applicationId/namespace、iOS Bundle ID/App ID/Provisioning/Keychain、CI/Release 配置、高德 Android/iOS SDK Key 绑定、微信/Push/Universal Link/OAuth/IAP 等依赖应用身份的配置。应在正式 App Store/Google Play 生产条目、生产高德 Key、Push/第三方登录/IAP 等外部绑定最终锁定前完成；若届时目标 ID 已被占用或平台记录已锁定，先重新评估再迁移。 |

### App Store 正式提交锁

```text
UIUX-P0-002 / consumer client stable
→ APP-ID-001 production application identity migration PASS
→ IOS-STORE-002 Privacy Manifest / Required Reason API PASS
→ IOS-STORE-003 privacy policy / SDK disclosure PASS
→ IOS-STORE-004 third-party AI consent PASS
→ IOS-STORE-005 AMap privacy PASS
→ IOS-STORE-006 App Privacy mapping PASS
→ IOS-STORE-007 account deletion PASS
→ IOS-STORE-008 background-location review package PASS
→ IOS-STORE-009 login-policy review PASS
→ IOS-STORE-010 IAP policy PASS when digital sales are enabled
→ IOS-STORE-011 final signed Archive + reviewer evidence PASS
→ IOS-STORE-012 final real-device/store-readiness PASS
→ 才允许标记 IOS-STORE-001 ✅
```

> App Store 政策会变化。IOS-STORE-001 启动时必须重新核对**当时生效**的 Apple App Review Guidelines、Required Reason API 列表、Privacy Manifest/SDK 要求、App Privacy 字段和支付/登录政策；本表记录的是当前已识别的工程 Gate，不以 2026-10-04 的政策文本永久冻结实现细节。

---

# 9. 商业化与增长

> **状态边界（2026-10-04）**：正式商业化实现尚未启动。现有 FREE/PERSONAL/FAMILY Plan、Quota、Entitlement、Admin 等仅视为技术基础，不代表定价、试用、Founder、订阅、支付、StoreKit 或消费者会员页面已经实现。除已明确完成的 BIZ-007～011 外，后续商业任务统一按本节重新排期。

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| BIZ-001 | 免费版权益 | ⬜ | **商业实现未开始**。Issue #168 / PR #172 仅提供 FREE plan/capability/quota 技术基础。V1 商业基线：¥0 永久；基础“记录→保存→找到”长期可用，含基础文字/时间线/搜索/足迹/人物地点物品/导出，以及受 quota 控制的基础照片、语音、AI 回忆、OCR/Vision/总结体验；建议首发存储 500MB～1GB，但最终值只由 canonical server config 决定。 |
| BIZ-002 | 个人会员 | ⬜ | **商业实现未开始**；PERSONAL authority 仅为技术基础。直连/Android/微信渠道 V1 价格基线：¥15/月、¥129/年；创始会员首发 ¥99/年。iOS App Store 采用独立 storefront price（见 BIZ-019），权益保持同一 PERSONAL。建议首发存储 20GB；包含更高媒体/AI quota、高级时间线/历史/检索/RAG/总结/导出等。禁止宣传“无限 AI/OCR/Vision”。 |
| BIZ-003 | 家庭会员 | ⬜ | **商业实现未开始**；FAMILY authority 仅为技术基础，Family permission/grant/privacy authority 保持独立。直连/Android/微信渠道 V1 价格基线：¥25/月、¥239/年；首发推广 ¥199/年。iOS App Store 采用独立 storefront price（见 BIZ-019），权益保持同一 FAMILY。建议最多 5 人、共享存储 100GB。会员 capability 永远不能替代家庭成员隐私授权。 |
| BIZ-004 | 高级会员 | ⏸ | PREMIUM capability foundation 可继续保留，但 **V1 消费者页面不展示、不销售**。后续根据真实 AI 成本和高频需求再评估“迹忆 Pro / AI 高级版”，参考区间 ¥199～299/年；V1 不实现该商业 SKU。 |
| BIZ-005 | 年度回忆报告 | ⬜ | V2-010 Annual Electronic Memoir backend + Mini/Flutter 产品能力已完成，但**商业 packaging 尚未开始**；V1 计划作为 PERSONAL/FAMILY 高价值能力的一部分，正式 entitlement packaging、quota、rollout 待商业化工作线统一收口。 |
| BIZ-006 | 实体年度回忆录 | ⏸ | 后续增值服务；V1 不做一次买断/实体商业闭环。 |
| BIZ-007 | 北极星指标：成功找回记忆数 | ✅ | Issue #169 / PR #173 已完成两轮正式极窄复审并合并；server-owned successful-memory-retrieval 口径、durable dedupe 与 aggregate report 已收口 |
| BIZ-008 | D1 / D7 / D30 留存 | ✅ | Issue #169 / PR #173 已合并；UTC signup cohort、active-day authority、D1/D7/D30 eligible/retained/null-zero 口径已收口 |
| BIZ-009 | Memory Retrieval Success | ✅ | Issue #169 / PR #173 已合并；accepted-attempt denominator、SUCCESS numerator 与 privacy-safe success-rate aggregation 已收口 |
| BIZ-010 | False Memory Rate | ✅ | S3-019 / Issue #87 / PR #89 已完成首版显式用户反馈驱动的 revision 指标基础：counts + denominator + rate；DELETE-only 不误算 false，不做 AI 质量打分/看板；已正式审查并合并 main |
| BIZ-011 | Production Registration Entitlement Default | ✅ | **Issue #197 / PR #199 已合并 `main=f805848ba16af786b3d15a6ae26d5dc3d399aa95`**：正常生产注册默认 `FREE`，public registration 不再调用 `create_legacy_full_entitlement()`；`LEGACY_FULL` 仅历史兼容/migration-only（以及明确 dev-only）使用，不出现在消费者购买/营销/升级入口；历史 entitlement 原样保留，不做批量迁移。 |
| BIZ-012 | Pricing Catalog & Commercial Policy V1 | ⬜ | 建立独立 Product/Price Catalog 与 Commercial Policy。首发逻辑产品：PERSONAL_MONTHLY/ANNUAL、FAMILY_MONTHLY/ANNUAL，以及 Founder/Launch price entry；Price 必须支持 `sales_channel/storefront` 维度，同一 Plan 可在不同销售渠道使用不同价格；金额使用 integer minor unit，Plan 与 Price 解耦，客户端不得硬编码价格。 |
| BIZ-013 | Value-triggered Trial & Founder Cohort | ⬜ | 新用户不注册即试用。满足价值条件（基线：记录≥10 / 连续使用≥3天 / 有效照片≥5）后可触发 14 天 PERSONAL 体验；服务端记录开始/结束，防卸载重领。Founder 使用 `pricing_cohort`/eligibility，不新增 PlanCode；基线前 5000 名个人付费会员 ¥99/年，续费锁价策略必须可运营修改。 |
| BIZ-014 | Membership Expiration & Safe Downgrade | ⬜ | PERSONAL/FAMILY 到期降为 FREE，但不得删除/锁定已有记忆、照片、语音或已有 AI 结果；超 FREE 存储时已有媒体继续可读/可删，只禁止新增超额媒体；新的高成本 AI/付费 capability 按 FREE authority/quota 判定；续费后恢复写入。 |
| BIZ-015 | Commercial Admin Simulation & Metrics | ⬜ | **商业模拟/运营指标尚未开始**；ADMIN-001 仅已包含 Entitlement & Quota 管理基础。商业化阶段需能由 SUPER_ADMIN 正确模拟 FREE→PERSONAL→FAMILY→expiry→downgrade，并记录 revision/audit。后台预留 FREE/PERSONAL/FAMILY/Trial 数量、转化、续费、平均存储/AI、AI/storage cost per paid user、ARPU 等指标；这些是运营指标，不是业务 hard rule。 |
| BIZ-016 | Consumer Membership Surfaces V1 | ⬜ | Flutter/Mini 消费者页面只展示 FREE / PERSONAL / FAMILY 三档；不展示 PREMIUM、LEGACY_FULL、内部 quota/provider token。展示当前权益、使用量、价格 Catalog、Trial/Founder eligibility、到期/降级说明；不得将价格和 quota 写死在客户端。 |
| BIZ-017 | Payment & Subscription Integration | ⬜ | 支付供应商单独任务。架构保持 Product → Price → Purchase/Subscription → Entitlement/Grant；Plan 不等于微信订单或 Apple SKU。未来接微信支付/App Store IAP 等；本任务完成前可由 Admin 模拟 entitlement 生命周期验证。 |
| BIZ-018 | Invite Reward V1 | ⏸ | V1 可先保留数据模型/规则，不必首发开放。基线：邀请新用户并达到真实激活条件（如连续使用 7 天）后双方 +7 天 PERSONAL；需要账号唯一约束、设备/IP 风控、年度奖励上限、禁止自邀请与循环刷。 |
| BIZ-019 | Cross-Store Pricing & Entitlement Parity V1 | ⬜ | **后期与 BIZ-012/BIZ-017/IOS-STORE-010 一起实现。** 同一 PERSONAL/FAMILY entitlement 在 Android/微信/官网/iOS 登录后保持一致，不建立 IOS_PERSONAL/ANDROID_PERSONAL 等分裂 Plan；仅 Price 按 `sales_channel/storefront` 区分。V1 基线：Android/微信 PERSONAL ¥15/月、¥129/年、Founder ¥99/年；iOS ¥18/月、¥148/年、Founder ¥118/年。Android/微信 FAMILY ¥25/月、¥239/年、Launch ¥199/年；iOS ¥30/月、¥268/年、Launch ¥228/年。iOS 用户在其他渠道已合法获得的 entitlement 登录后继续生效；App Store 购买仍由 StoreKit/IAP 校验。价格均为可运营调整基线，不硬编码 Apple 佣金或永久 storefront 政策。 |


## 9.1 V1 首发会员与定价设计基线（2026-09-30）

> 本节是**首发产品/商业设计基线**，用于开发和验收，不是不可修改的永久价格表。价格、存储、AI quota、家庭人数、试用触发阈值、Founder eligibility 都必须通过 canonical server authority / Admin policy 可调整，严禁散落硬编码在 Flutter、Mini、Admin frontend 或业务 endpoint。

### 首发消费者套餐

> 以下 Android/微信价格是直连销售渠道基线；iOS App Store 使用独立 storefront price。**渠道价格可以不同，但 Plan / Capability / Quota / Entitlement 语义必须相同。**

```text
FREE
¥0 / 永久

PERSONAL — Android / 微信
¥15 / 月
¥129 / 年
Founder baseline: ¥99 / 年

PERSONAL — iOS App Store
¥18 / 月
¥148 / 年
Founder baseline: ¥118 / 年

FAMILY — Android / 微信
¥25 / 月
¥239 / 年
Launch baseline: ¥199 / 年

FAMILY — iOS App Store
¥30 / 月
¥268 / 年
Launch baseline: ¥228 / 年

FAMILY
最多 5 人（基线）
共享存储 100GB（基线）

PREMIUM
V1 不展示、不销售

LEGACY_FULL
migration-only / compatibility-only
```

### FREE 产品原则

FREE 不是 Demo，也不是 7/30 天后锁死的试用版。用户必须能长期完成：

```text
记录
保存
找到
查看已有数据
基础搜索
数据导出
```

基础照片/语音/AI/OCR/Vision/Summary 可以提供体验额度，但不得无限。建议首发存储 500MB～1GB；AI/OCR/Vision/语音/总结初始额度由运营后台/服务端配置确定。

禁止：

```text
免费期结束后禁止查看已有记忆
付费后才能导出自己的数据
广告补贴换取私人 Memory/Photo/Location/Family 画像
```

### PERSONAL 产品原则

主推年费，年费显著优于月付：

```text
¥15 × 12 = ¥180
标准年费 = ¥129
Founder baseline = ¥99
```

基线能力：
- FREE 全部能力；
- 建议 20GB 存储；
- 更高 Photo/Voice/OCR/Vision/ASR quota；
- AI 回忆 / 找记忆 / 日月年总结；
- 高级时间线 / 完整历史 / RAG / 高级整理；
- 高级导出/备份能力；
- 所有高成本能力仍受 server quota 控制。

产品文案不得承诺“无限 AI / 无限 OCR / 无限 Vision”。

### FAMILY 产品原则

基线：

```text
¥25 / 月
¥239 / 年
首发推广 ¥199 / 年
最多 5 人
共享存储 100GB
```

包含 PERSONAL 主要能力 + 家庭成员/记忆/时间线/照片/权限/老人模式/帮我记一下/家庭回忆/家庭月报年报/关怀能力，以及更高共享 quota。

**商业 entitlement 永远不能越过 Family Membership / Permission / Grant / Privacy Pause authority。**

### PREMIUM 与 LEGACY_FULL

- PREMIUM：代码可保留，V1 不营销、不售卖；后续根据 AI 成本和用户行为决定是否演化为 Pro/AI 高级版。
- LEGACY_FULL：只用于历史兼容和 migration，不允许正常注册创建、不允许客户端购买/升级、不出现在消费者页面。

### Value-triggered Trial

不做“注册即开始 7/30 天会员”。

触发基线：

```text
累计记录 >= 10
OR 连续使用 >= 3 天
OR 有效照片 >= 5
→ 14 天 PERSONAL 体验
```

必须服务端持久化 eligibility / start / expires，不依赖客户端时间，卸载/重装不能重复领取。

新手任务奖励可以后续配置：

```text
第一条记忆      +1 天
第一次照片      +1 天
第一次语音      +2 天
连续记录 3 天   +3 天
第一次 AI 回忆  +2 天
创建家庭        +2 天
邀请家庭成员    +3 天
累计最多 14 天
```

奖励数值是运营策略，不是 hard rule。

### Founder Cohort

Founder 与 Plan 分离：

```text
plan_code = PERSONAL
pricing_cohort = FOUNDER_2026
```

基线为前 5000 名个人付费会员 ¥99/年。是否“连续订阅永久保持 ¥99”必须由后续运营策略确认并可修改，禁止用 User.created_at 或 PlanCode 写死。

### 到期 / 降级

```text
PERSONAL / FAMILY expires
→ FREE
```

到期后：

```text
已有记忆      可读
已有照片      可读
已有语音      可读
已有 AI 结果  可读
基础搜索      可用
数据导出      可用
```

若已有存储 > FREE quota：

```text
不删除
不锁读取
允许删除
禁止新增超额媒体
续费后恢复写入
```

新 AI/高成本操作按 FREE capability + quota 判定。

### Quota authority

现有维度继续作为 V1 canonical resource quota：

```text
STORAGE_BYTES
AI_PROVIDER_REQUESTS
AI_INPUT_TOKENS
AI_OUTPUT_TOKENS
```

原则：

```text
Plan  → Capability
Quota → high-cost resource amount

client != quota authority
```

Provider 调用前必须：

```text
entitlement check
→ quota reservation
→ durable commit
→ provider request
```

Provider 已开始后，即使 timeout/provider failure，可按既定政策计入 request quota，避免重试形成无界外部成本。

### Pricing Catalog

价格不得与 PlanCode 绑死；同一逻辑产品必须允许多个 `sales_channel/storefront` price entry。

首发逻辑产品/渠道价格基线：

```text
# Android / 微信 / direct baseline
JIYI_PERSONAL_MONTHLY          1500 fen
JIYI_PERSONAL_YEARLY          12900 fen
JIYI_PERSONAL_FOUNDER_YEARLY   9900 fen
JIYI_FAMILY_MONTHLY            2500 fen
JIYI_FAMILY_YEARLY            23900 fen
JIYI_FAMILY_LAUNCH_YEARLY     19900 fen

# iOS App Store baseline
JIYI_PERSONAL_MONTHLY_IOS          1800 fen
JIYI_PERSONAL_YEARLY_IOS          14800 fen
JIYI_PERSONAL_FOUNDER_YEARLY_IOS  11800 fen
JIYI_FAMILY_MONTHLY_IOS            3000 fen
JIYI_FAMILY_YEARLY_IOS            26800 fen
JIYI_FAMILY_LAUNCH_YEARLY_IOS     22800 fen
```

上述 `_IOS` 仅表达 Catalog 价格项示意，不代表新增 PlanCode。正式模型优先使用 `product + sales_channel/storefront + price` 关系，而不是复制 PERSONAL/FAMILY 会员类型。金额必须使用 integer minor unit，禁止 float。

商业层概念分离：

```text
Plan
Price
Trial
Promotion
Pricing Cohort
Subscription
Entitlement / Grant
Quota
```

长期架构：

```text
Product
→ Price
→ Purchase / Subscription
→ Entitlement / Grant
→ UserEntitlement runtime authority
```

支付供应商订单/SKU 不得直接成为 Plan authority。

### 邀请奖励

推荐基线：

```text
老用户邀请新用户
→ 新用户达到真实激活条件（例如连续使用 7 天）
→ 双方 +7 天 PERSONAL
```

禁止“仅注册立即奖励”。需要账号级唯一约束、设备/IP 风控、最大年度奖励、禁止自邀请、禁止循环邀请刷奖励。V1 可以先设计模型和规则，不必首发开放。

### 广告策略

V1 不加入广告。长期也禁止使用以下私人内容做广告画像/定向：

```text
Memory
照片内容
位置足迹
家庭关系
```

商业模式优先：

```text
个人会员
家庭会员
未来高级 AI
```

### 消费者页面

V1 只展示：

```text
免费版      ¥0 / 永久

个人会员    ¥129 / 年
            Founder baseline ¥99 / 年

家庭会员    ¥239 / 年
            Launch baseline ¥199 / 年
```

不显示 PREMIUM、LEGACY_FULL、内部 quota 名称、provider/token 成本。

### 运营指标（参考，不是服务端 hard rule）

后台预留：

```text
FREE / PERSONAL / FAMILY / Trial 用户数
Trial → Paid
FREE → PERSONAL
PERSONAL → FAMILY
会员到期数
续费率
平均存储使用
平均 AI 使用
AI cost / paid user
Storage cost / paid user
ARPU
```

当前经营目标仅作为运营参考：

```text
FREE → PAID        5%～10%+
CAC                尽量 < ¥30
第一阶段续费率      >= 50%
成熟续费率目标      65%～70%
```

这些目标不得进入业务逻辑或 entitlement hard rule。

### V1 明确不做

```text
无限 AI
终身会员
一次买断
广告
PREMIUM 商业销售
复杂优惠券体系
积分商城
企业多人套餐
家庭人数动态计费
按 token 向普通用户收费
付费后才能导出自己的数据
会员到期删除/锁定已有数据
```

### 商业化实施顺序

> 当前不启动；待现阶段产品/生产稳定工作完成后统一进入商业化工作线。

```text
1. BIZ-011 注册默认 LEGACY_FULL → FREE              ✅ 已完成
2. BIZ-012 Pricing Catalog + channel/storefront price
3. Entitlement / Quota canonical runtime authority
4. BIZ-013 Founder cohort + Value-triggered Trial
5. BIZ-014 Expiration / safe downgrade
6. BIZ-015 Admin simulation + commercial metrics
7. BIZ-016 Flutter/Mini membership surfaces
8. BIZ-019 Cross-store pricing / entitlement parity
9. BIZ-017 Payment & Subscription Integration
   ├─ WeChat/direct payment
   └─ App Store StoreKit / IAP（IOS-STORE-010）
10. Commercial Launch
```

在支付系统接入前，Admin 必须能够安全模拟并验证：

```text
FREE
→ PERSONAL
→ FAMILY
→ expiry
→ downgrade
```

所有 Capability / Quota 行为必须以服务端 canonical authority 为准。


## 9.2 上线增长与留存优化（2026-10-04）

> **单独作为消费者增长工作线推进，不等同于继续堆功能。** 目标是把“下载安装 → 第一次感受到价值 → 长期自动记录 → 成功找回 → 主动回忆 → 分享/邀请 → 口碑传播”做成完整增长飞轮。AI 仍只做搜索、理解、总结和表达辅助，不把“AI聊天”作为增长主卖点。

### 增长飞轮

```text
下载安装
→ 完成必要授权
→ 首日就看到迹忆已经形成内容
→ 第一次成功找回过去
→ 后续持续自动形成可回忆生活
→ 那年今日 / 周月回忆主动把过去送回来
→ 生成值得保存与分享的回忆成果
→ 朋友圈 / 微信好友 / 家庭邀请
→ 新用户安装
→ 家庭与个人记忆资产继续积累
→ 留存、续费与口碑增强
```

| ID | 优先级 | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- | --- |
| GROW-001 | P0.5 | First-day Aha / Recent Memory Bootstrap V1 | ⬜ | 解决“新用户第一天没有历史数据”的冷启动问题。用户明确授权照片访问后，优先在本机读取最近 30～90 天照片的拍摄时间、EXIF 地点等必要 metadata，生成“最近记忆”候选与日期/地点聚合，让用户安装当天就能看到“迹忆已经帮我找回一些过去”。不得在未授权时扫描；不得为做冷启动而默认上传全部原图；候选事实必须标明来源并允许跳过/纠正。后续可扩展日历/旧日记导入，但首版不做大而全导入。 |
| GROW-002 | P0.5 | Today Active Recording Experience V1 | ⬜ | 基于已完成的 CORE-003 Recording Health，优化消费者“今天”首页，让用户明确看到“迹忆正在工作”：今日地点数、有效足迹/覆盖、最近记录时间、照片关联、记录健康状态与缺口。避免只展示技术状态；核心体验是“即使我没操作，今天也在自动形成记忆”。 |
| GROW-003 | P1 | On This Day / Memory Resurfacing V1 | ⬜ | 增加“那年今日 / 去年今天 / 一个月前今天 / 值得回看的这一天”等低打扰主动回忆。候选必须来自真实 Memory/Visit/Photo Evidence，优先用户可感知价值，不做无证据 AI 编故事。需要 notification/reminder 时与 REM-001 共用正式 delivery authority，控制频率，避免骚扰。 |
| GROW-004 | P1 Growth | Memory Story Cards & WeChat Moments Share V1 | ⬜ | **重点口碑传播能力。** 将月度回忆、旅行、家庭日、年度回忆等整理成高质量“回忆故事卡/我的九月/这次旅行/我们的家庭2026”等可保存成果；支持生成分享图片，并面向微信好友/朋友圈分享。分享前必须提供明确预览与隐私脱敏：默认不暴露精确地址、经纬度、家庭成员真实姓名、私密照片/语音文字；地点默认降为城市/用户确认名称，敏感字段必须由用户主动选择才可进入分享结果。分享卡可带低干扰“迹忆”品牌标识/来源，但不能覆盖主体内容。首版优先静态长图/多卡，不先做复杂视频生成。 |
| GROW-005 | P1 Growth | Content-driven Family Invite V1 | ⬜ | Family Invite 不只放在设置页。把邀请放到真实内容场景：一次家庭旅行、一顿饭、孩子生日、长辈故事等，允许用户“邀请家人一起补充/保存这段回忆”。邀请落地页首先解释“这里有属于你的家庭记忆”，而不是先卖会员。继续严格受 Family Membership / Permission / Grant / Privacy authority 约束。与 BIZ-018 推荐奖励分离：内容邀请是产品增长，奖励邀请是后续商业增长。 |
| GROW-006 | P0.5 | “找回”明星入口与 Query UX V1 | ⬜ | 基于已完成 CORE-002，把“我25号去哪了？”这类找回体验升级成消费者明星功能。入口文案优先“想找什么？ / 找回”，而不是“AI聊天”。结果先展示结构化事实、时间、地点、停留和 Evidence，再提供“帮我总结这一天”等 AI 二级动作。典型场景：某天去哪了、上次去某地、什么时候见过某人、某次照片在哪里。 |
| GROW-007 | P0.5 Trust | My Data / Privacy Trust Center V1 | ⬜ | 把隐私从合规文档变成产品能力。集中展示“今天采集了什么、长期保留了什么、AI 本月处理次数、家庭当前共享范围、自动记录状态”，并提供暂停、关闭自动足迹、导出、删除、注销等真实操作。清晰承诺不使用私人 Memory/Photo/Location/Family 做广告画像。所有统计必须来自真实 authority，不得伪造“安全评分”。 |
| GROW-008 | P1 Launch | Launch Messaging & Scenario Creative V1 | ⬜ | 首发营销不讲“多模态 AI 第二大脑”，只打 3 个一秒可懂场景：①“忘了25号去哪了？问迹忆。” ②“妈妈生日那天，我们去了哪家饭店？” ③“那些你没写日记的日子，也不该消失。” 官网/App Store/短视频素材展示真实产品路径与真实数据样例，AI 只作为辅助说明。建立 15～30 秒短视频、商店截图、官网首屏统一 narrative。 |
| GROW-009 | P1 Analytics | Growth Funnel & Word-of-mouth Metrics V1 | ⬜ | 在现有 BIZ-007～010 指标基础上新增消费者增长漏斗：授权完成率、Time-to-First-Aha、7日有效记录覆盖率、30日 Memory Coverage、First Retrieval Success、分享卡生成率/实际分享率、Family 内容邀请率/接受率、D7/D30、Trial→Paid、续费。指标用于判断产品价值与口碑，不进入 entitlement hard rule。 |
| GROW-010 | P1 Retention | Weekly / Monthly Memory Productization V1 | ⬜ | 将现有 Summary/Annual Memoir 能力产品化为“这一周 / 我的九月 / 我的2026”等可读、可保存、可分享成果。默认强调地点、照片、真实事件与用户确认内容，AI只负责组织语言。优先做少而精的高价值模板，不做大量花哨模板市场。 |
| GROW-011 | P1 Growth | Value-triggered Share / Invite Timing V1 | ⬜ | 分享/邀请触发必须发生在真实价值事件之后，例如成功找回一天、生成月度回忆、完成旅行回忆或家庭内容整理；禁止注册即弹“分享给朋友”、首次打开即索要评价/邀请。需要建立频控、dismiss cooldown 与实验开关，避免破坏信任。 |

### 朋友圈 / 微信分享产品原则

```text
私密原始记忆
→ 用户主动选择生成回忆成果
→ server/client 生成 share-safe projection
→ 隐私脱敏
→ 用户预览
→ 用户主动确认
→ 保存图片 / 微信好友 / 朋友圈
```

默认 share-safe projection：

```text
允许：
日期/月份
城市级地点
用户明确确认的地点名称
统计数字
用户主动选择的照片
用户主动选择的文字
低干扰“迹忆”品牌来源

默认禁止：
精确经纬度
家庭住址
未确认的精确地点
家庭成员真实姓名
未选择的照片
语音原文
私密 Memory 原文
后台定位原始点
Evidence 内部 ID / provider 信息
```

朋友圈传播的目标不是做广告海报，而是让用户愿意分享一个真正属于自己的结果：

```text
我的九月
这次旅行
一年前的今天
这一年和妈妈
孩子这一年的成长
我们的家庭2026
```

### 上线前 / 上线后优先级

```text
上线前消费者闭环优先：
GROW-001 First-day Aha
GROW-002 Today / Recording Health 产品化
GROW-006 “找回”明星入口
GROW-007 My Data / Privacy Trust Center

上线首批增长能力：
GROW-003 On This Day
GROW-004 Memory Story Cards + 朋友圈/微信分享
GROW-005 Content-driven Family Invite
GROW-008 Launch Messaging
GROW-009 Growth Funnel Metrics
GROW-010 Weekly/Monthly Memory Productization
GROW-011 Value-triggered Share / Invite Timing
```

### 产品约束

- 不以“每天打开次数”和“使用时长”作为唯一成功指标；用户数天不打开、需要时 10 秒找回真实生活仍是成功体验。
- 不为了提高分享率泄露精确足迹、家庭成员或私人记忆。
- 不为了增长强制通讯录上传、默认公开、默认家庭共享或强制邀请。
- 不把 AI 生成内容伪装成用户真实经历。
- 不在首日用高频推送、评价弹窗、会员墙破坏自动记录和隐私信任。
- 所有增长实验必须可关闭、可审计，并服从 Privacy / Family / Entitlement / Evidence authority。


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
6. 每次新增或修改人工维护的源代码，都必须遵守 `docs/CODE_ANNOTATION_RULES.md`：对关键/非显而易见逻辑写正常开发注释，说明用途、原因和边界；不要求固定标签。
7. 自动生成文件、lockfile、二进制资源不得为了加注释而破坏格式；通过提交记录和本表追踪。
8. Stage 2 及以后功能不得提前侵入当前 Stage 1 PR，除非先更新本表并明确变更范围。
9. 并行开发必须保持独立分支/独立 PR；共享协议由单一 PR 定义，其他工作线只消费。
10. 每条工作线在最终合并前都必须重新确认最新 `main`、clean replay、精确 HEAD CI 和最终净 diff。
