<!-- 本文件是迹忆项目长期维护的唯一开发进度总表；每次功能开发、修复、审查或合并后都必须同步更新状态。 -->
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

> 最后更新：2026-09-26  
> Stage 1「记得住」：✅ complete  
> Stage 2「自动记」：✅ complete  
> Stage 3「懂生活 / AI Memory」：✅ complete  
> Stage 4「连接家庭 / Elder V1」：✅ complete  
> Stage 4 final production baseline：`9576c7ad912823115e83e67608fdab408e484f1f`（PR #125 merge；before docs-only Stage 4 closeout）  
> 当前阶段：**V2 Personal Memory Graph**；V2-001 / Issue #128 Person Foundation V1 已启动，V2-002+ 仍未开始。

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
| V2-001 | Person 人物模型 | 🟠 | Issue #128 / PR #129：owner-scoped explicit people model 已实现；名称、结构化别名、关系标签、私有备注、revision-safe CRUD、Data Export/Delete/Account Delete 与 PostgreSQL concurrency Gate 已通过当前自动测试；待正式审查/合并，不包含 Person↔Memory/图谱边、AI 自动创建或链接 |
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

| ID | 功能 | 状态 | 说明 |
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
| SEC-007 | 数据彻底删除 | ✅ | PR #28 已实现 durable DB / Storage 全删除、partial-failure retry、MemoryEdit 审计清理并通过 exact-head CI 后合并 |
| SEC-008 | 账户注销 | ✅ | M / S1-022 / Issue #31 / PR #32 已完成两轮正式审查并合并；S1-021 数据清理先行、身份最终同事务删除、恢复 token、竞争删除 fail closed、旧 token 失效及本地 producer/sync/onboarding quiesce + owner purge 均有回归 |
| SEC-009 | 位置权限单独同意 | ⬜ | 按平台规则实施 |
| SEC-010 | 家庭查看逐项授权 | ✅ | Issue #95 / PR #96 已完成 default-deny per-scope foundation、canonical membership locks、committed persisted-state resolver、PostgreSQL Family Gate 与 exact-head #575（454 passed）；已合并 `main=c933f2a6`，真实敏感读取按 S4-004+ 分阶段接入 |
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
| BIZ-010 | False Memory Rate | ✅ | S3-019 / Issue #87 / PR #89 已完成首版显式用户反馈驱动的 revision 指标基础：counts + denominator + rate；DELETE-only 不误算 false，不做 AI 质量打分/看板；已正式审查并合并 main |

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