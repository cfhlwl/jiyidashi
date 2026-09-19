<!-- [人工注释][FND-025] 本文档必须与当前公开 schema 同步；客户端只能声明 capture_source，可信等级由服务端所有。 -->
<!-- [人工注释][S1-001] Stage 1 正式认证接口已加入公开 API；dev-token 仍只用于显式开启的开发/测试环境。 -->
<!-- [人工注释][S1-FIX-002][S1-FIX-003] 第二轮修复补充真实 Evidence 来源契约与正式认证滥用保护。 -->
<!-- [人工注释][S1-011][S1-019][S1-023][S1-024] Stage 1 第二批补齐位置失效、单条删除、暂停今天与手动恢复控制语义。 -->
<!-- [人工注释][S1-PR3-FIX-001][S1-PR3-FIX-002][S1-PR3-FIX-003] PR #3 第一轮 HOLD 后补充 Object 匹配路由、失效时间水位与 pause/today 单时钟语义。 -->
<!-- [人工注释][S1-005][S1-006] Stage 1 第三批 A 线冻结私有 staging->final 媒体协议、真实图片签名校验、commit-safe READY 与 Evidence 关联协议。 -->
# V1 API 基线

Base path:

```text
/v1
```

## 正式认证

### 注册

```http
POST /v1/auth/register
```

```json
{
  "email": "user@example.com",
  "password": "correct-horse-battery-staple",
  "nickname": "小忆",
  "timezone": "Asia/Shanghai",
  "locale": "zh-CN"
}
```

`timezone` 必须是可解析的 IANA 时区名称。`nickname` / `locale` 会先去除首尾空白再校验，纯空白返回 422。`user_id` 由服务端生成，客户端不能指定。

成功返回：

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user_id": "11111111-1111-1111-1111-111111111111"
}
```

### 登录

```http
POST /v1/auth/login
```

```json
{
  "email": "user@example.com",
  "password": "correct-horse-battery-staple"
}
```

账号不存在与密码错误统一返回 `401 INVALID_CREDENTIALS`。不存在账号仍执行固定 dummy Argon2 verify，避免出现明显的快速失败路径。

正式认证同时启用服务端滥用保护：

- 注册：IP 窗口限速，且门禁发生在 Argon2 hash 之前。
- 登录：IP 总窗口 + 已存在账号/IP 窗口。
- 连续失败：短期指数退避。
- 超限统一返回 `429 AUTH_RATE_LIMITED`，并附 `Retry-After` 响应头。
- 限流 bucket 只保存服务端 HMAC key，不保存原始 IP 或邮箱。
- `APP_ENV=production/prod` 时禁止关闭 `AUTH_RATE_LIMIT_ENABLED`。

### 本人资料

```http
GET   /v1/user
PATCH /v1/user
```

更新示例：

```json
PATCH /v1/user
{
  "nickname": "新的昵称",
  "timezone": "Asia/Singapore",
  "locale": "zh-CN"
}
```

`PATCH /v1/user` 只允许修改公开资料字段；登录邮箱/身份归属不能通过 profile API 修改。nickname / locale 采用 strip-before-validation，纯空白输入返回 422。

## 开发登录

```http
POST /v1/auth/dev-token
```

仅本地 development/test 使用，并且必须显式 `ENABLE_DEV_AUTH=true`。

`APP_ENV=production` 或 `APP_ENV=prod` 时该能力不可开启；生产必须使用正式认证方案。

## Memory

```http
POST   /v1/memories
GET    /v1/memories/{id}
PATCH  /v1/memories/{id}
DELETE /v1/memories/{id}
GET    /v1/timeline
POST   /v1/memory/query
GET    /v1/memory/summarize/day
```

### 新建 Memory

通用 Memory API 当前只允许直接提交 `USER_TEXT` / `USER_VOICE`。图片必须先完成下文的私有媒体上传与 `READY` 校验，再调用 `/v1/media/{media_id}/memory`；裸 `USER_PHOTO` 会返回 422。

客户端**不得提交** `confidence`、`is_confirmed`、`AI_INFERENCE` 等服务端可信字段；额外字段会被 schema 拒绝。

```json
POST /v1/memories
{
  "memory_type": "NOTE",
  "content": "医生让我下个月18号复查",
  "capture_source": "USER_TEXT"
}
```

语音主动记录示例：

```json
POST /v1/memories
{
  "memory_type": "VOICE",
  "content": "护照放在书房左侧柜子第二层",
  "capture_source": "USER_VOICE"
}
```

### 编辑单条 Memory

```http
PATCH /v1/memories/{id}
```

Stage 1 只允许修改 `title` / `content`。请求还必须携带最近一次 GET 返回的
`expected_revision` 作为并发前置条件；它不是可编辑业务字段。客户端不能提交
`occurred_at`、`memory_type`、`source_type`、`confidence`、`is_confirmed`
或位置/metadata 等可信字段；额外字段返回 422。

编辑不会重写原始 Evidence：

- 原有 `MemorySource` / `MediaEvidenceLink` 永久保留；
- 每次实际修改写入 append-only `MemoryEdit` revision；
- 正文变化时服务端追加一个新的 `USER_TEXT` edit-source，并由“用户明确改写正文”这一服务端事实派生当前 Memory 为 `USER_TEXT / confirmed / confidence=1.0`；
- 查询当前修正文案时 Evidence 必须指向该 edit-source，`provenance=USER_EDIT`，不能继续复用旧图片/语音媒体作为新文字的证明；
- 标题-only 修改不制造新的正文 Evidence，也不改变当前正文来源；
- 相同值重试是 no-op，不重复制造 revision，即使原 `expected_revision` 已落后也可安全返回当前结果；
- 不同内容的过期编辑若 `expected_revision` 与当前 revision 不同，返回 409 `MEMORY_EDIT_REVISION_CONFLICT`，防止多设备静默覆盖；
- `OBJECT_LOCATION` backing Memory 在 Stage 1 拒绝通用编辑，避免与结构化当前位置状态分叉；
- 跨用户或已删除 Memory 统一返回 404。

```json
PATCH /v1/memories/11111111-1111-1111-1111-111111111111
{
  "expected_revision": 3,
  "title": "新的标题",
  "content": "用户修正后的正文"
}
```

### 删除单条 Memory

```http
DELETE /v1/memories/{id}
```

删除成功返回 `204`。

- 删除后的 Memory 不能再进入普通记忆搜索或 Evidence 回答。
- 如果该 Memory 支撑一个 CURRENT ObjectLocation，删除会让该当前位置同步失效。
- Flutter / 微信小程序只有在服务端 DELETE 成功后才清空当前答案，不能只做本地隐藏。

## 私有媒体 / 图片 Evidence

```http
POST /v1/media/uploads
POST /v1/media/{media_id}/complete
POST /v1/media/{media_id}/download
POST /v1/media/{media_id}/memory
```

媒体桶必须保持**私有**。服务端数据库保存私有 staging / final object key，公开 API 永远不返回这些 key、内部 `storage_etag` 或永久公开 URL，也不允许客户端提交 bucket / endpoint / object key。COS / OSS 通过服务端 `STORAGE_BACKEND=s3` 的 SigV4 兼容配置接入；Mini / Flutter 只消费本节统一协议。

生产环境使用自定义 `STORAGE_ENDPOINT_URL` 时必须是 `https://`；development / test 可为本地 MinIO 等显式使用 HTTP。没有自定义 endpoint 时由 SDK 按 provider / region 生成标准 endpoint。

### 1. 创建临时上传

```json
POST /v1/media/uploads
{
  "client_upload_id": "22222222-2222-2222-2222-222222222222",
  "kind": "IMAGE",
  "content_type": "image/jpeg",
  "size_bytes": 284921,
  "original_filename": "IMG_1001.jpg"
}
```

Stage 1 当前只接受 `IMAGE`，支持 `image/jpeg`、`image/png`、`image/webp`、`image/heic`、`image/heif`。`client_upload_id` 是**当前用户域内**的幂等键：

- 同一用户 + 同一 `client_upload_id` + 相同元数据：复用同一个 `media_id` / staging 对象身份，并可重新签发短时 PUT。
- 同一用户 + 同一 `client_upload_id` 但尺寸/类型/文件名变化：`409 MEDIA_UPLOAD_ID_CONFLICT`。
- 不同用户可以使用相同 `client_upload_id`，不会共享媒体身份。

成功示例：

```json
{
  "id": "33333333-3333-3333-3333-333333333333",
  "kind": "IMAGE",
  "status": "PENDING",
  "content_type": "image/jpeg",
  "size_bytes": 284921,
  "original_filename": "IMG_1001.jpg",
  "created_at": "2026-09-16T10:00:00Z",
  "completed_at": null,
  "upload": {
    "method": "PUT",
    "url": "https://<private-object-storage>/<temporary-signature>",
    "headers": {
      "Content-Type": "image/jpeg"
    },
    "expires_at": "2026-09-16T10:10:00Z"
  }
}
```

客户端必须使用响应里的 `method` / `headers` 上传；`upload.url` 到期后由对象存储拒绝。服务端默认签名 TTL 为 600 秒，配置范围 60–3600 秒。PUT 只允许写服务端生成的私有 staging key，客户端从未获得 final Evidence key 的写能力。

### 2. 服务端确认对象

对象直传成功后调用：

```http
POST /v1/media/33333333-3333-3333-3333-333333333333/complete
```

此请求**不接受** object key / size / content type 等客户端补充字段。服务端流程固定为：

1. 用当前用户归属找到服务端持久化的 staging key。
2. HEAD staging，校验实际尺寸与 Content-Type。
3. Range 读取 staging 的极小文件头，验证真实图片签名；JPEG / PNG / WebP 按 magic bytes，HEIC / HEIF 按 ISO-BMFF `ftyp` brand 校验。本步骤只判断文件容器/类型，**不做 OCR、Vision 或任何图片语义分析**。
4. 使用服务端对象存储凭证把 staging COPY / promote 到独立 final key。
5. HEAD final 再次校验尺寸与 Content-Type，并再次 Range 读取 final 文件头验证图片签名，封住“staging 校验后、COPY 前旧 PUT 改写”的竞态。
6. final 全部校验成功后，数据库事务写 `READY` 与内部 final ETag，并执行 `commit`。
7. **只有数据库 commit 成功后**才 best-effort 删除 staging。若 commit 失败，数据库保持 `PENDING`、staging 保留，final 可以已存在；再次调用 `complete` 可重新校验/晋升并恢复成功。

这样即使旧 PUT 签名在 `READY` 后尚未到期，它也只能改写 staging，不能覆盖已经作为 Evidence 的 final 对象。下载与 Evidence 永远只引用 final key。

错误语义：

- staging 对象不存在：`409 MEDIA_OBJECT_NOT_FOUND`
- 实际尺寸不符：`409 MEDIA_OBJECT_SIZE_MISMATCH`
- 实际 Content-Type 不符：`409 MEDIA_OBJECT_TYPE_MISMATCH`
- 声明图片类型但实际文件头不匹配：`409 MEDIA_IMAGE_INVALID`
- staging -> final 晋升后 final 不可读取：`503 MEDIA_PROMOTION_FAILED`
- 对象存储不可用：`503 MEDIA_STORAGE_UNAVAILABLE`
- 媒体不属于当前用户：统一 `404 MEDIA_NOT_FOUND`

客户端“上传成功”的声明和客户端提供的 MIME 元数据本身都不能升级可信等级；只有服务端完成尺寸、类型、真实文件签名、staging → final 与数据库 commit 后状态才会成为 `READY`。

### 3. 创建图片 Memory / Evidence

```json
POST /v1/media/33333333-3333-3333-3333-333333333333/memory
{
  "content": "红色文件夹里有旅行票据",
  "title": "旅行票据",
  "occurred_at": "2026-09-16T18:05:00+08:00"
}
```

规则：

- `media_id` 必须属于当前用户且状态为 `READY`。
- `content` 是用户主动输入的文字；本阶段**不做 OCR、Vision、AI 图片理解**。
- 服务端创建 `PHOTO` Memory + `USER_PHOTO` MemorySource，并写入一对一 MediaEvidenceLink。
- 同一 `media_id` 重复调用只返回既有 Memory，不重复制造 confirmed fact。
- 原始图片是 Evidence；它不代表任何 AI 推断已经成为 confirmed fact。

`POST /v1/memory/query` 的 Evidence 在图片证据命中时增加：

```json
{
  "kind": "MEMORY",
  "source_type": "USER_PHOTO",
  "memory_source_id": "44444444-4444-4444-4444-444444444444",
  "media_id": "33333333-3333-3333-3333-333333333333"
}
```

非图片 Evidence 的 `media_id` 为 `null`。客户端不得自行根据 `source_type` 合成媒体 ID。

### 4. 临时下载

```http
POST /v1/media/{media_id}/download
```

仅当前用户的 `READY` 媒体可签发短时 GET。每次读取都重新执行用户归属检查；跨用户访问统一 404。GET 只签 final object，响应中的 `download.url` 不是永久地址，不应持久化。

## Objects

```http
POST /v1/objects
GET  /v1/objects
POST /v1/objects/{id}/locations
GET  /v1/objects/{id}/location
POST /v1/objects/{id}/location/stale
```

创建物品：

```json
POST /v1/objects
{
  "name": "护照"
}
```

同一用户重复创建相同规范化名称会返回既有 Object；并发首次创建发生唯一约束竞争时也会 rollback 后重新读取既有 Object，不把该竞争暴露成 500。

随后记录位置：

```json
POST /v1/objects/{id}/locations
{
  "location_text": "书房左侧柜子第二层",
  "capture_source": "USER_VOICE",
  "recorded_at": "2026-09-15T20:36:00+08:00"
}
```

`recorded_at` 可省略；如果客户端显式提交，必须携带时区偏移。当前对象位置 API 也拒绝裸 `USER_PHOTO`，未来如果支持“图片证明物品位置”，必须复用已验证 media 链路而不是仅声明来源字符串。

### 明确标记“已经不在那里”

```http
POST /v1/objects/{id}/location/stale
```

该接口用于用户主动纠正当前位置：

- 当前 `CURRENT` 位置变为 `STALE`，历史记录保留。
- 服务端同时写入一个内部 `UNKNOWN` ObjectLocation 作为**失效时间水位**；它不是新的用户位置，也不会作为 CURRENT 返回。
- 失效时间水位取用户执行该操作时的服务器时间 `T`。之后迟到的 `recorded_at <= T` 位置只能成为 `STALE`，即使当时已经没有 CURRENT，也不能“复活”为当前位置。
- 新位置写入与 stale 操作都锁同一个 Object 行 `FOR UPDATE`，保证两者在 PostgreSQL 上串行化。
- 此后再问“护照在哪里？”或“护照在什么地方？”时，只有**位置意图 + 实际命中用户已有 Object**才由结构化 ObjectLocation 状态接管；如果该 Object 没有新的 CURRENT，必须返回 `NO_EVIDENCE`。
- 如果问题虽然包含“哪里”等位置词，但根本没有匹配到已有 Object，则允许继续普通 Memory 搜索，例如“老张在哪里工作？”。
- 普通 Memory 搜索明确排除 `MemoryType.OBJECT_LOCATION` backing Memory，历史位置不能绕过结构化 CURRENT / STALE / UNKNOWN 状态重新承担当前位置事实源。

## 查询记忆

```json
POST /v1/memory/query
{
  "question": "我的护照在哪里？"
}
```

命中示例：

```json
{
  "answer": "你最后一次记录“护照”的位置是：书房左侧柜子第二层。",
  "can_answer": true,
  "certainty": "confirmed",
  "reason": null,
  "intent": "FIND_OBJECT",
  "evidence": [
    {
      "kind": "OBJECT_LOCATION",
      "id": "11111111-1111-1111-1111-111111111111",
      "source_type": "USER_TEXT",
      "memory_source_id": "33333333-3333-3333-3333-333333333333",
      "occurred_at": "2026-09-15T12:36:00Z",
      "excerpt": "护照：书房左侧柜子第二层",
      "confidence": 1.0,
      "media_id": null
    }
  ],
  "memory_ids": [
    "22222222-2222-2222-2222-222222222222"
  ]
}
```

Evidence 字段语义：

- `kind`：证据承载对象类型，例如 `MEMORY` / `OBJECT_LOCATION`；**不是来源**。
- `id`：对应承载对象 ID（Memory 或 ObjectLocation）。
- `source_type`：真正的采集来源，例如 `USER_TEXT` / `USER_VOICE` / `USER_PHOTO` / `GPS`。
- `memory_source_id`：实际参与 Evidence gate 的 `MemorySource.id`，用于追溯证据记录。
- `confidence`：该 `MemorySource` 的可信度。
- `media_id`：只有服务端存在 MediaEvidenceLink 时才返回对应媒体 ID；否则为 `null`。
- `provenance`：`ORIGINAL_SOURCE` 表示原始采集来源；`USER_EDIT` 表示当前正文由后续用户编辑产生的 USER_TEXT source 支撑。编辑后的文字不会继续复用旧图片/语音媒体作为证明。

没有证据：

```json
{
  "answer": null,
  "can_answer": false,
  "certainty": "unknown",
  "reason": "NO_EVIDENCE",
  "intent": "FIND_OBJECT",
  "evidence": [],
  "memory_ids": []
}
```

> **可信规则：** 可回答的个人事实必须经过服务端 Evidence gate。客户端提交的字段不能把 AI 推断升级为 confirmed fact。

## 客户端生产 API 配置

Flutter 生产构建必须显式提供：

```text
--dart-define=APP_ENV=production
--dart-define=API_BASE_URL=https://<production-api>/v1
```

生产 Flutter 不再回退 localhost，也不显示开发 API 地址。

微信小程序 production build 必须设置：

```text
JIYI_API_BASE_URL=https://<production-api>/v1
```

生产配置拒绝 localhost / `127.0.0.1` / 非 HTTPS endpoint，并通过 build-time 常量移除普通页面中的 API 编辑入口。

## 自动位置

```http
POST /v1/location/batch
```

示例：

```json
{
  "points": [
    {
      "client_uuid": "device-a-20260915-0001",
      "latitude": 39.9042,
      "longitude": 116.4074,
      "accuracy": 20,
      "recorded_at": "2026-09-15T10:30:00+08:00"
    }
  ]
}
```

`recorded_at` **必须 timezone-aware**。例如 `Z`、`+08:00` 均可；`2026-09-15T10:30:00` 这种无时区时间会返回 422。

暂停记录时，如果当前仍处于暂停状态，服务端返回：

```http
409 RECORDING_PAUSED
```

恢复后补传历史点时，服务端仍会根据每个点自身 `recorded_at` 与持久化暂停区间比对；暂停期间产生的自动位置不会因为延迟上传而入库。

## 隐私 / 记忆暂停

```http
GET  /v1/privacy/status
POST /v1/privacy/pause
POST /v1/privacy/pause/today
POST /v1/privacy/resume
```

暂停 30 分钟：

```json
POST /v1/privacy/pause
{
  "duration_minutes": 30
}
```

客户端可用固定时长：30 分钟、60 分钟、180 分钟。

### 暂停今天

```http
POST /v1/privacy/pause/today
```

“今天”由服务端读取用户资料中的 IANA timezone，计算该用户**下一次本地午夜**，客户端不得按设备时区自行猜结束时间。服务端只捕获一次 UTC `now`，`paused_since` 与用户本地日期均从同一个 reference timestamp 派生，避免请求恰好跨本地午夜时产生额外一天的暂停。

### 手动恢复

```http
POST /v1/privacy/resume
```

恢复只结束当前 pause interval：

- 历史暂停区间不会删除。
- 暂停期间产生的自动位置点即使恢复后才上传，仍会被服务端识别并拒绝入库。
- 暂停只影响自动采集；用户主动执行“记一下”、文字记忆、物品位置记录仍允许。

## Reminder（S1-025）

Stage 1 Reminder 是绑定既有 Memory 的最小提醒能力，不是 Todo/日历系统。

- `POST /v1/reminders`
  - Header 必填：`Idempotency-Key: <UUID>`；同 key + 同 payload 返回原 Reminder，同 key + 不同 payload 返回 `409 IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST`
  - 必填：`memory_id`、`title`、带时区 offset/Z 且严格晚于服务端当前 UTC 的 `remind_at`
  - 可选：`content`
  - 过去/当前时刻返回 `422 REMINDER_TIME_MUST_BE_FUTURE`
  - 只能绑定当前用户未删除的 Memory；不存在、跨用户或已删除统一返回 `404 REMINDER_MEMORY_NOT_FOUND`
- `GET /v1/reminders?status=PENDING|DONE|CANCELLED&limit=100`
  - 只返回当前用户的提醒；`status` 可省略以读取最近历史
- `POST /v1/reminders/{id}/done`
- `POST /v1/reminders/{id}/cancel`
  - 只允许从 `PENDING` 进入终态
  - response-loss 后重复相同终态动作是幂等 no-op
  - `DONE <-> CANCELLED` 互相改写返回 `409 REMINDER_STATUS_CONFLICT`

Memory 软删除会把仍为 `PENDING` 的关联 Reminder 自动改为 `CANCELLED`；已完成/已取消历史保留。
本阶段不包含重复规则、优先级、项目/子任务、协作、日历同步、AI 自动创建或推送平台扩展。


## Account Delete（S1-022）

`POST /v1/account/delete`

请求必须包含：

```json
{
  "request_id": "UUID",
  "confirmation": "DELETE_MY_ACCOUNT"
}
```

账号注销会先完整复用 S1-021 Data Delete。只要数据清理尚未安全完成，`User` 与 `AuthIdentity` 都继续保留，但普通数据 API 会返回 `423 ACCOUNT_DELETION_IN_PROGRESS`，避免清理过程中又写入新数据。 Account Delete durable gate 建立后，外部 `POST /v1/data/delete` 也返回 423；只有 Account Delete orchestrator 内部可以推进它已绑定的 S1-021 operation，避免竞争删除 request。

未完成阶段返回 HTTP 202，并携带 `data_deletion_status` / `retry_after_seconds`；调用方使用同一 request_id 重试。客户端若重启而丢失首次 request_id，新的账号注销请求也会 join 已存在的 durable gate，并返回 canonical request_id。

最终完成后，身份、Data Delete receipt、Account Delete gate 与 User 在同一事务删除。旧 JWT 不能再通过普通 API 的 User 权威检查。相同邮箱以后可以重新注册，但会生成新的 user_id 和全新空账号。

详见 `docs/ACCOUNT_DELETE_V1.md`。


### Account Delete 两阶段提交（S1-022-FIX-002）

`POST /v1/account/delete` 额外要求布尔字段 `local_cleanup_ready`：

- `false`：PREPARE。只建立/复用 durable `AccountDeletionOperation` gate；返回 `202`，`data_deletion_status=null`。这一阶段不会推进 S1-021，也不会删除 User/AuthIdentity。
- `true`：COMMIT。表示官方客户端已完成当前 owner 的本机 OfflineQueue/Onboarding purge，服务端才允许继续 S1-021 与最终账号身份事务。

该顺序用于封闭两个崩溃窗口：App 重启时可通过恢复登录继续 PREPARE gate；服务端最终删号前，本机敏感 payload 已被清除。
