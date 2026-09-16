<!-- [人工注释][DOC-PROGRESS-001] 本文件是迹忆项目长期维护的唯一开发进度总表；每次功能开发、修复、审查或合并后都必须同步更新状态。 -->
<!-- [人工注释][DOC-PROGRESS-009] PR #2 已通过第二轮复审并合并 main；Stage 1 第一批真实用户闭环正式完成，下一批仍继续 Stage 1，不启动 Stage 2。 -->
<!-- [人工注释][DOC-PROGRESS-010] Stage 1 第二批启动：物品位置失效、单条 Memory 删除、暂停记忆与手动恢复；Stage 2 继续保持未开始。 -->
<!-- [人工注释][DOC-PROGRESS-011] Stage 1 第二批首版代码与三端自动验收完成后进入 PR #3 第一轮正式审查。 -->
<!-- [人工注释][DOC-PROGRESS-012] PR #3 第一轮正式审查结论 HOLD：2 个 P1 + 2 个 P2 进入窄范围修复；本批状态回退 🔵，Stage 2 继续未开始。 -->
<!-- [人工注释][DOC-PROGRESS-013] PR #3 第一轮 2 P1 + 2 P2 已完成窄修并在同一生产代码 HEAD cfa2cd84 上通过 Backend / Mobile / Mini Program 全量门禁，进入第二轮正式审查。 -->
<!-- [人工注释][DOC-PROGRESS-014] PR #3 第二轮原 2 P1 + 2 P2 全部关闭，新发现 P1 S1-PR3-FIX-005 已完成唯一 Object 解析窄修；生产代码 HEAD 1b0bf994 通过 Backend 41/41、Mobile、Mini Program 全量门禁，进入第三轮窄范围最终复审。 -->
<!-- [人工注释][DOC-PROGRESS-015] PR #3 第三轮最终复审 PASS，并已合并 main=52ef68f4；Stage 1 第二批正式完成，Stage 2 继续未开始。 -->
<!-- [人工注释][DOC-PROGRESS-016] Stage 1 第三批采用四工作线并行开发；统一基于 main=e98c99de 排期，当前仅完成任务拆分与依赖记录，尚未启动功能开发，Stage 2 继续未开始。 -->
<!-- [人工注释][DOC-PROGRESS-017] A：Backend Media 已在 PR #7 完成 S1-006 + S1-005 后端媒体/Evidence 第一阶段实现并通过 Backend 全量门禁，状态进入待正式审查；OCR/Vision/ASR/Stage 2 均未启动。 -->
<!-- [人工注释][DOC-PROGRESS-018] PR #7 第一轮预审 HOLD 的 3 个 P1 + 2 个 P2 已完成窄修；生产代码 HEAD 13cd13f3 通过 Backend 全量门禁与 pytest 53/53，A 线恢复 🟠 待第二轮审查；OCR/Vision/ASR/Stage 2 继续未启动。 -->
<!-- [人工注释][DOC-PROGRESS-020] B：Flutter Offline 首版完成后，PR #6 第一轮正式审查 HOLD，进入 S1-PR6-FIX-001 transport 异常分类 P1 窄修；S1-017 仍未开始。 -->
<!-- [人工注释][DOC-PROGRESS-021] PR #6 第一轮正式审查：0 P0 / 1 P1 / 0 阻塞 P2；仅 TransportException 可触发 SQLite offline fallback，协议/解析/客户端异常必须 fail closed。 -->
<!-- [人工注释][DOC-PROGRESS-022] PR #6 第二轮窄范围复审 PASS：S1-PR6-FIX-001 正式关闭，生产 HEAD d1351f61 的 transport/protocol 分类与 SQLite fallback 边界通过审查；S1-015/S1-016 进入 🟠 待合并，S1-017 继续未开始。 -->
<!-- [人工注释][DOC-PROGRESS-019] PR #7 第二轮窄范围复审 PASS，第一轮 3P1+2P2 全部关闭；PR 已从 Draft 转 Ready 并合并 main=9504fa8d。S1-006 完成，S1-005 继续由客户端主动拍照/选图工作线推进；Stage 2 继续未开始。 -->
# 迹忆开发进度总表

> 最后更新：2026-09-17  
> 当前阶段：Stage 1「记得住」第三批并行开发进行中；PR #6 第二轮窄范围复审 PASS，工作线 B 正式审查通过、待合并；Stage 2 未开始
> 当前开发基线：`main=daf84199a10ad1669fbe241d8e6b150d8f4434bb`  
> 当前 PR：#6 `feat/stage1-mobile-offline`（第二轮 PASS；S1-015/S1-016 🟠 待合并；S1-017 不在本 PR）

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
| S1-M2 | Stage 1 第二批“纠错 → 删除 → 暂停/恢复” | ✅ | PR #3 已通过三轮正式审查并合并 `main=52ef68f4`；最终 HEAD 三端 CI 全部 SUCCESS |
| S1-M3 | Stage 1 第三批“多媒体记录 + 离线 + 数据控制” | 🔵 | 并行工作线已启动；B 线 SQLite/离线队列正式审查通过、待合并，其余任务继续按独立工作线推进 |
| CI-001 | Backend CI | ✅ | PR #7 生产 HEAD `13cd13f3`：Ruff、SQLite/PostgreSQL migration、`alembic check`、ObjectLocation invariants、pytest 53/53 PASS |
| CI-002 | Flutter Android CI | ✅ | 最终 PR HEAD `7319d493`：analyze + tests + production-config debug APK build PASS |
| CI-003 | Flutter iOS CI | ✅ | 最终 PR HEAD `7319d493`：production-config `flutter build ios --debug --no-codesign` PASS |
| CI-004 | 微信小程序 CI | ✅ | 最终 PR HEAD `7319d493`：`npm ci` + TypeScript + production Taro WeChat build PASS |
| CI-005 | UI Visual Preview / Golden Screenshot | ⬜ | 第三批工程质量任务；先覆盖 Flutter Golden，再扩展 Android Emulator / 小程序 Preview |

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
| FND-012 | 离线旧位置晚到防回滚 | ✅ | 根据 `recorded_at` 决定 CURRENT / STALE；PR #3 已补“用户失效水位”边界并通过回归 |
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

目标：完成“记录 → 保存 → 找到 → 相信 → 纠错/删除/暂停”的 V1 主闭环。

| ID | 功能 / 需求 | 状态 | 说明 |
| --- | --- | --- | --- |
| S1-001 | 正式用户注册 / 登录 | ✅ | Argon2、限速/退避、dummy verify、migration drift gate 已通过复审 |
| S1-002 | 用户资料与时区设置 | ✅ | trim-before-validation、IANA timezone |
| S1-003 | 文字记忆录入 | ✅ | Flutter / 小程序接真实 Memory API，仅声明 `USER_TEXT` |
| S1-004 | 语音记忆录入 | ⬜ | 录音、上传、ASR、Evidence |
| S1-005 | 图片记忆录入 | 🔵 | 后端媒体/Evidence 基础已随 PR #7 合并；主动拍照/选图客户端仍由 C 线实现，因此整体继续进行中 |
| S1-006 | COS / OSS 对象存储直传 | ✅ | PR #7 第二轮复审 PASS 并合并 `main=9504fa8d`；私有 staging→final、短时签名、owner gate、真实图片签名与 commit-safe staging 清理已落地 |
| S1-007 | ASR 语音转写 | ⬜ | 原始音频保留为证据；本 PR 未启动 |
| S1-008 | “帮我记住”统一入口 | ⬜ | 文字 / 语音 / 拍照统一进入 Memory Pipeline |
| S1-009 | “东西在哪”物品录入 | ✅ | Object create 并发竞争已幂等兜底 |
| S1-010 | “东西在哪”查询 | ✅ | 返回真实 Evidence `source_type` / `memory_source_id` |
| S1-011 | 物品位置失效 / “已经不在那里” | ✅ | 唯一最具体 Object 解析、普通搜索排除位置 backing Memory、UNKNOWN 失效水位、stale/add 共锁及重叠名称回归均通过三轮审查并已合并 |
| S1-012 | 基础记忆搜索 | ✅ | 普通 Memory Evidence 返回真实来源且不降低 gate |
| S1-013 | “问记忆”客户端页面接真实 API | ✅ | Flutter / 小程序已接真实 API |
| S1-014 | 答案展示 Evidence / 来源 / 时间 | ✅ | 客户端展示来源、证据类型、时间、可信度 |
| S1-015 | 客户端本地 SQLite | 🟠 | PR #6 第二轮窄范围复审 PASS；SQLite schema/状态机本轮未修改，正式审查通过、待合并 |
| S1-016 | 离线记忆队列 | 🟠 | PR #6 第二轮窄范围复审 PASS；仅 TransportException 可触发 SQLite fallback，Protocol/Api/未知异常 fail closed，待合并 |
| S1-017 | 离线同步与幂等 | ⬜ | 真实同步/自动 flush 尚未进入；未来自动重发前必须用 `client_uuid + 服务端幂等` 处理“请求已发送但响应丢失”的不确定性 |
| S1-018 | 单条 Memory 编辑 | ⬜ | 编辑后 Evidence 与审计语义需明确 |
| S1-019 | 单条 Memory 删除 | ✅ | 真实服务端 DELETE 链、删除后查询失效及 ObjectLocation 联动均通过审查并已合并 |
| S1-020 | 数据导出 | ⬜ | 用户可导出自己的全部记忆 |
| S1-021 | 全部数据删除 | ⬜ | DB / Cache / Storage 一致删除 |
| S1-022 | 注销账号 | ⬜ | 与全部数据删除联动 |
| S1-023 | 暂停记忆 30 分钟 / 1 小时 / 3 小时 / 今天 | ✅ | 单一 reference timestamp + `America/New_York` DST 时区回归通过正式审查并已合并 |
| S1-024 | 手动恢复记录 | ✅ | resume 保留 PrivacyPauseInterval 历史，延迟上传门禁回归通过并已合并 |
| S1-025 | 基础提醒模型 | ⬜ | 仅从记忆产生提醒，不做完整 Todo |
| S1-026 | 首次使用引导 | ⬜ | 3 分钟内完成“记住 → 找回”Aha Moment |

## 2.1 PR #2 第一轮审查修复项

| ID | 优先级 | 问题 | 状态 | 最终结果 |
| --- | --- | --- | --- | --- |
| S1-FIX-001 | P1 | `AuthIdentity` metadata / schema drift gate | ✅ | PostgreSQL `alembic check` PASS，已合并 |
| S1-FIX-002 | P1 | Evidence 未返回真实 `source_type` | ✅ | API + Flutter + 小程序已合并 |
| S1-FIX-003 | P1 | 注册/登录缺少抗爆破与 Argon2 DoS 门禁 | ✅ | IP/账号窗口、429、Retry-After、指数退避已合并 |
| S1-FIX-004 | P2 | 不存在账号未执行 dummy Argon2 verify | ✅ | missing/wrong-password 成本路径一致 |
| S1-FIX-005 | P2 | nickname / locale 空白绕过 | ✅ | strip-before-validation，whitespace-only 422 |
| S1-FIX-006 | P2 | 同名 Object 并发创建唯一约束 500 | ✅ | rollback + reselect 幂等返回 |
| S1-FIX-007 | P2 | 客户端生产 API endpoint 仍是开发态 | ✅ | build-time endpoint + production CI 真构建 |

## 2.2 PR #3 正式审查修复项

| ID | 优先级 | 问题 | 状态 | 当前结果 |
| --- | --- | --- | --- | --- |
| S1-PR3-FIX-001 | P1 | Object 查询路由既漏拦历史位置又误伤普通“哪里”查询 | ✅ | 第二轮确认 PASS；PR #3 已合并 main |
| S1-PR3-FIX-002 | P1 | 用户 STALE 后晚到旧位置可在 CURRENT 为空时复活 | ✅ | `UNKNOWN` invalidation watermark + add/stale 共 Object `FOR UPDATE` 通过回归与 PostgreSQL 门禁；已合并 |
| S1-PR3-FIX-003 | P2 | `pause/today` 两次读取当前时间存在午夜跨日竞态 | ✅ | 单一 `now` 派生 local day + `America/New_York` 回归 PASS；已合并 |
| S1-PR3-FIX-004 | P2 | 本轮传输层语义修改缺少人工注释 | ✅ | Flutter / 小程序人工注释补齐并通过 CI；已合并 |
| S1-PR3-FIX-005 | P1 | 重叠 Object 名称可能跨对象按最新位置回答，甚至绕过更具体 Object 的 STALE | ✅ | 唯一最长/最具体 Object 解析、同等最佳 fail closed、更具体 STALE 不回退短名均通过第三轮最终复审；已合并 |

## 2.3 Stage 1 第三批并行开发安排

<!-- [人工注释][S1-PLAN-001] 第三批采用“公共协议先冻结、四工作线独立分支、独立 PR、逐条审查”的方式推进；排期不等于开工，未创建开发分支前任务仍保持 ⬜。 -->

### 2.3.1 统一基线与硬规则

- 所有第三批开发分支统一从对应任务启动时确认的最新 `main` 创建；A 线实际基线为 `main=b09a3981e12904fe488a623b1a5e1ee1314af6a8`。
- 一个任务组一个独立分支、一个独立 PR；禁止建立一个包含全部第三批功能的“大 Stage 1 分支”。
- 手工新增或修改的语义代码块继续使用 `[人工注释][TASK-ID]`；自动生成文件、lockfile、严格 JSON 等按既有豁免规则处理。
- 公共 API / schema / Evidence 协议先冻结再让多端并行；任何工作线需要修改共享协议时，必须先记录并通知其他工作线，禁止各端自行发明字段。
- 每个 PR 单独通过本端自动测试；涉及公共协议时必须补 Backend + 受影响客户端回归。
- Stage 2 后台定位、CoreLocation、Location Bridge、Visit clustering 等全部保持 ⬜，第三批不得提前侵入。

### 2.3.2 四条并行工作线

| 工作线 | 第一阶段任务 | 计划分支 / PR | 允许范围 | 关键依赖 | 当前状态 |
| --- | --- | --- | --- | --- | --- |
| A：Backend Media | `S1-006` + `S1-005` 后端媒体/Evidence 基础 | `feat/stage1-media-pipeline` / PR #7 | 私有对象存储、临时签名上传/下载、媒体元数据、图片 Evidence、Backend tests、API 文档 | 媒体协议已冻结为 staging→final；第二轮复审 PASS；未引入 OCR/Vision/ASR/Stage 2 | ✅ 已合并 |
| B：Flutter Offline | `S1-015` + `S1-016` | `feat/stage1-mobile-offline` / PR #6 | Android/iOS 本地 SQLite、离线队列、状态机、重启恢复、Flutter tests | 第二轮窄范围复审 PASS；S1-PR6-FIX-001 已关闭；`S1-017` 后置 | 🟠 正式审查通过，待合并 |
| C：Mini Capture | `S1-005` 小程序主动拍照/选图 + `S1-004` 录音 UI/权限壳 | `feat/stage1-miniprogram-capture` | 小程序页面、权限、文件选择/录音适配、上传客户端；禁止假 API/假成功 | 媒体提交字段必须使用 A 已合并协议；真实语音提交等待 `S1-007` | ⬜ 待启动 |
| D：Data & Quality | `S1-020` 数据导出；`CI-005` UI Visual Preview | `feat/stage1-data-export`；`ci/ui-visual-preview` | 用户数据导出、授权边界、导出测试；Flutter Golden/视觉产物 CI | 与 A/B/C 冲突较少，两个任务仍各自独立 PR | ⬜ 待启动 |

A 线最终验收：生产代码 HEAD `13cd13f3`；Ruff PASS；SQLite migration PASS；PostgreSQL migration PASS；`alembic check` PASS；PostgreSQL ObjectLocation invariants PASS；pytest **53/53 PASS**。第二轮窄范围复审 PASS，PR #7 已合并 `main=9504fa8d`。

B 线正式审查：生产 HEAD `d1351f61`；第二轮窄范围复审确认 0 P0 / 0 P1 / 0 阻塞 P2，S1-PR6-FIX-001 已关闭。TransportException 才允许 SQLite fallback；ProtocolException、ApiException 与未知客户端异常均 fail closed。Android analyze/tests/APK 与 iOS no-codesign build 已绑定最终生产 SHA 验收通过。真实自动同步与服务端幂等仍留到 `S1-017`。

### 2.3.3 第二阶段接续任务

| 顺序 | 任务 | 前置条件 | 计划工作线 | 当前状态 |
| --- | --- | --- | --- | --- |
| 1 | `S1-007` ASR 语音转写 | A 的对象存储/Evidence 基础合并 | A | ⬜ |
| 2 | `S1-008` “帮我记住”统一入口 | `S1-005` + `S1-007` 协议稳定 | A + B/C 客户端接入 | ⬜ |
| 3 | `S1-017` 离线同步与幂等 | B 的 SQLite/队列完成；服务端提交幂等协议冻结；自动重发前必须覆盖 response-loss/unknown-commit 场景 | B + Backend 窄配合 | ⬜ |
| 4 | `S1-018` 单条 Memory 编辑 | 第三批公共协议稳定 | 独立 Backend/客户端 PR | ⬜ |
| 5 | `S1-021` 全部数据删除 | `S1-006` Storage 删除语义稳定 | D / Backend | ⬜ |
| 6 | `S1-022` 注销账号 | `S1-021` 全量删除闭环完成 | D / Backend | ⬜ |
| 7 | `S1-025` 基础提醒模型 | 核心记录/离线链稳定 | 后续独立 PR | ⬜ |
| 8 | `S1-026` 首次使用引导 | 文字/图片/语音统一入口稳定 | Flutter + 小程序 | ⬜ |

### 2.3.4 推荐启动与合并顺序

1. **先启动 A 与 B**：A 先锁定媒体上传公共协议，B 完全独立实现本地 SQLite + 离线队列。
2. **随后启动 D**：数据导出和 UI Preview 各自独立 PR，不等待媒体功能。
3. **C 在 A 的公共协议冻结后启动真实接入**：可先做 UI/权限，但不允许提交假数据兜底。
4. A 第一阶段合并后进入 `S1-007`；B 第一阶段合并后等待服务端幂等契约再进入 `S1-017`。
5. `S1-021/022` 必须等对象存储删除语义确定后再做，避免 DB 删除完成而 Storage 残留。
6. 每个工作线合并前都必须基于最新 `main` 做最终 replay / CI；不得因为“另一条线已 PASS”而跳过自己的验收。

### 2.3.5 共享文件冲突规则

以下位置视为第三批共享热点，修改前必须先确认是否已有其他工作线占用：

- `backend/app/schemas.py` 及公共 API payload 定义；
- `docs/API.md`；
- Flutter / Mini Program 公共 API client 的字段协议；
- `docs/DEVELOPMENT_PROGRESS.md`；
- CI workflow 文件。

原则：**共享协议只允许一个 PR 定义，其他 PR 只消费；如确需修改，先 rebase 最新 `main` 并重新做跨端契约审查。**

### 2.3.6 PR #7 第一轮预审修复项

| ID | 优先级 | 问题 | 状态 | 当前结果 |
| --- | --- | --- | --- | --- |
| S1-PR7-FIX-001 | P1 | READY commit 前删除 staging，commit 失败后无法恢复 | ✅ | 第二轮确认 PASS；READY commit 成功后才 best-effort 清 staging，commit-failure 回归确认可恢复；已随 PR #7 合并 |
| S1-PR7-FIX-002 | P1 | production 自定义对象存储 endpoint 可使用 HTTP | ✅ | 第二轮确认 PASS；production/prod + S3 + custom endpoint 强制 HTTPS；已随 PR #7 合并 |
| S1-PR7-FIX-003 | P1 | READY 只验证 size/MIME，不能证明真实图片 | ✅ | 第二轮确认 PASS；staging/final 双文件头校验，非法对象保持 PENDING；已随 PR #7 合并 |
| S1-PR7-FIX-004 | P2 | `create_schema()` 依赖偶然 import 顺序加载媒体模型 | ✅ | 第二轮确认 PASS；显式 import `media_models`；已随 PR #7 合并 |
| S1-PR7-FIX-005 | P2 | 公共 `MediaRead` 暴露内部 `storage_etag` | ✅ | 第二轮确认 PASS；DB 内部 ETag 保留、公开 API 移除；已随 PR #7 合并 |

> 第二轮窄范围复审结论 PASS；生产代码范围 `c553b121..13cd13f3` 无新 P0/P1/阻塞 P2。PR #7 已合并 `main=9504fa8d`，上述 5 项正式关闭。

### 2.3.7 PR #6 正式审查修复项

| ID | 优先级 | 问题 | 状态 | 当前结果 |
| --- | --- | --- | --- | --- |
| S1-PR6-FIX-001 | P1 | catch-all 客户端异常被误判为离线并写入 SQLite | ✅ | 第二轮窄范围复审 PASS；底层仅 `http.ClientException` / `TimeoutException` 映射为 `TransportException`，2xx malformed/结构错误为 `ProtocolException`，非 2xx malformed 仍为 `ApiException`；UI 仅 TransportException 可入队 |

> 第二轮窄范围复审结论：**PASS / READY FOR FINAL MERGE PROCESS**。`S1-015` / `S1-016` 当前 🟠 待合并；`S1-017` 保持 ⬜。已知 response-loss/unknown-commit 边界留到 S1-017 使用 `client_uuid + 服务端幂等` 处理，不构成 PR #6 阻塞项。

---

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
| SEC-001 | HTTPS / TLS | ⬜ | 上线前强制；PR #7 已额外强制 production 自定义对象存储 endpoint 使用 HTTPS |
| SEC-002 | 对象存储私有桶 | 🟠 | PR #7 已按私有桶 + 服务端 key + fail-closed 设计实现，且 READY 前验证真实图片文件头；待部署验收 |
| SEC-003 | 临时签名下载 URL | 🟠 | PR #7 已实现短时 PUT/GET，GET 仅对 owner 的 READY final 对象签发；staging 仅在 READY commit 成功后清理，待部署验收 |
| SEC-004 | 敏感数据权限隔离 | ⬜ | 位置 / 健康 / 家庭 / 生物识别分级 |
| SEC-005 | 服务端访问审计 | ⬜ | 敏感数据查询留痕 |
| SEC-006 | 数据导出 | ⬜ | 用户数据可迁移 |
| SEC-007 | 数据彻底删除 | ⬜ | DB / Cache / Storage 一致删除 |
| SEC-008 | 账户注销 | ⬜ | 与删除策略联动 |
| SEC-009 | 位置权限单独同意 | ⬜ | 按平台规则实施 |
| SEC-010 | 家庭查看逐项授权 | ⬜ | 默认关闭 |
| SEC-011 | 记忆暂停 | ✅ | 暂停/恢复、PrivacyPauseInterval 历史门禁、`pause/today` 单时钟边界均通过审查并随 PR #3 合并 |
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
9. 第三批并行开发必须遵守 2.3 的工作线边界；共享协议由单一 PR 定义，其他工作线只消费，禁止多分支同时独立修改同一契约。