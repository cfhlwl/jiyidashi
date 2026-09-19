# Account Delete V1（S1-022）

## 1. 范围

Account Delete 是“注销账号”，与 S1-021 的“删除用户数据但保留账号”不同。

本阶段目标：

1. 账号注销必须先完整复用 S1-021 的对象存储 + DB 删除状态机；
2. S1-021 未安全完成前，绝不删除 `User` / `AuthIdentity`；
3. 注销进行中禁止普通数据 API 再写入新数据；
4. 最终事务原子删除登录身份、删除 receipt、注销 gate 和 User；
5. response-loss / 客户端重启后可以安全继续；
6. 完成后不保存永久账号墓碑。

本阶段不引入 Stage 2 能力，也不改变普通 logout。

## 2. API

`POST /v1/account/delete`

请求：

```json
{
  "request_id": "UUID",
  "confirmation": "DELETE_MY_ACCOUNT",
  "local_cleanup_ready": false
}
```

`confirmation` 必须精确为 `DELETE_MY_ACCOUNT`，不能使用 `DELETE_MY_DATA`。`local_cleanup_ready` 是两阶段提交位：`false` 只建立 durable Account gate；官方客户端完成本机 owner 数据清理后，才以 `true` 推进 S1-021 与最终身份删除。

未完成时返回 HTTP 202，例如：

```json
{
  "request_id": "canonical UUID",
  "data_deletion_status": "WAITING_STORAGE_QUIET",
  "completed": false,
  "retry_after_seconds": 30,
  "deleted_counts": {}
}
```

最终完成返回 HTTP 200，`completed=true`。

## 3. Durable gate

首次注销时创建 transient `AccountDeletionOperation`。

它只保存：

- `user_id`
- 首次 canonical `request_id`
- 实际复用的 S1-021 `data_deletion_request_id`

如果用户在注销前已经有一个未完成的 Data Delete，Account Delete 会加入并继续那个 S1-021 operation；否则由服务端生成**全新的内部 UUID** 新建 S1-021。内部 UUID 绝不复用客户端 Account Delete request_id，避免命中过去同 ID 的 COMPLETED Data Delete receipt 而跳过注销后的新数据/对象存储清理。

同一账号后续即使客户端丢失首次 request_id、换了新的 request_id，也会 join 已存在的 Account Delete gate，不会因为 409 永久无法恢复。

两个注销请求真实并发时也允许使用不同 request_id：先建立 gate 的 request_id 成为 canonical intent；另一个请求 join。若其中一个请求先完成最终 User 删除，另一个请求在后续 S1-021 阶段看到 `USER_NOT_FOUND` 时按既定“User absence = completed”语义收敛为成功，而不是暴露瞬时 404。

## 4. 写入封锁

只要 `AccountDeletionOperation` 存在：

- 普通用户数据 API：`423 ACCOUNT_DELETION_IN_PROGRESS`
- 正式密码 login：允许重新认证并签发**恢复 token**，响应 `account_deletion_in_progress=true`；普通数据 API 仍返回 `423 ACCOUNT_DELETION_IN_PROGRESS`
- token 真正签发前会再次对 User 拿 `KEY SHARE` 并检查 account gate；该锁保持到请求结束，Account Delete 不能在“最后状态检查”和 TokenResponse 之间插队删除 User
- login 与注销首次建 gate 在 PostgreSQL 上仍锁同一个 User row：login 持 KEY SHARE，Account Delete 持 FOR UPDATE；删除中的重新登录只用于恢复注销，不解除普通数据 gate
- 已准入但跨 rollback/commit 边界继续执行的旧请求：由 `GuardedSession` fail closed

Account Delete 恢复端点继续使用 JWT subject 认证并由 orchestrator 内部推进既定 S1-021 operation。Account Delete gate 建立后，外部 `POST /v1/data/delete` 返回 `423 ACCOUNT_DELETION_IN_PROGRESS`，不能另起或改换 Data Delete request。

外部 Data Delete 入口与 Account Delete 首次建 gate 还必须在数据库层锁同一 User row：
- Data Delete 先拿 `FOR UPDATE`：Account Delete 等它建立/加载 S1-021 operation，随后 join 该 operation；
- Account Delete gate 先成立：Data Delete 拿锁后看到 gate，返回 423。

因此不存在“Data Delete 先查到无 gate，但 Account Delete 在它真正建 operation 前插队”的 TOCTOU 窗口。

## 5. 最终删除事务

只有目标 S1-021 operation 已经 `COMPLETED`，才允许进入最终事务。

同一个事务显式删除：

1. `AuthIdentity`
2. 当前用户全部 `DataDeletionOperation` receipt
3. `AccountDeletionOperation`
4. `User`

任何异常整体 rollback。

因此不会出现：

- User 已删除但 AuthIdentity 还能登录；
- AuthIdentity 已删但 User 仍处于半注销；
- storage 删除失败却提前删账号。

## 6. Token 与重新注册语义

Access token 是无状态 JWT。

完成注销后，普通 API 仍会查权威 `User`；旧 token 的 subject 已无对应 User，因此不能继续访问原账号数据。

Account Delete 自身把“合法 token 指向的 User 已不存在”视为幂等完成。这样最终 200 响应丢失后，旧 token 重放不会把成功误报成失败。

完成后不保存永久 identity tombstone。相同邮箱未来可以明确重新注册，但会得到**新的 user_id、全新的空账号**，不会恢复旧数据。

## 7. 本地数据与两阶段提交

官方 Flutter 使用 **PREPARE → LOCAL PURGE → COMMIT** 顺序：

1. 用户输入“注销账号”完成不可逆确认；
2. 先调用 `POST /v1/account/delete`，`local_cleanup_ready=false`；
3. 服务端只建立/复用 durable `AccountDeletionOperation` gate，普通 API 立即变成 423，但**不推进 S1-021，也不删除身份**；
4. 客户端收到 PREPARE 后，隐藏普通导航、停止新的自动 outbox flush，等待当前 owner 的 single-flight flush 收尾；
5. 先 quiesce Onboarding controller，等待已在飞的账号作用域状态写入结束；再删除 OfflineQueueStore 中该 owner 的全部 payload（包括 completed/cancelled）与该 owner 的 Onboarding 本地状态；
6. 本机清理成功后，再以 `local_cleanup_ready=true` COMMIT，服务端才允许推进 S1-021 和最终身份事务。

这个顺序同时封闭两类崩溃窗口：

- PREPARE 后、本机 purge 前崩溃：服务端 gate 已持久化；重新密码登录会返回
  `account_deletion_in_progress=true` 的恢复 token，普通数据 API 仍 423，客户端可再次 purge 后继续 COMMIT。
- 本机 purge 后、最终服务端删除前崩溃：本机敏感 payload 已经清空；重新登录恢复后继续 COMMIT 即可。
- 服务端最终删除完成后崩溃：本机 payload 早已在 COMMIT 之前清掉，不存在“账号已无身份但设备残留无法收尾”的窗口。

PREPARE 响应丢失时，客户端保持同一 request_id 重试 PREPARE；服务端只会 join 同一 account gate。
COMMIT 返回 202/网络错误时，本机 purge 不回滚，用户只能继续注销或退出，稍后重新登录恢复。

普通 logout 仍保留原有“按 user_id 隔离但不清本地数据”的行为。

## 8. AuthRateLimitBucket

AuthRateLimitBucket 只保存由服务端密钥生成的 HMAC bucket key，不保存原始邮箱/IP，也没有 user_id 外键；历史 account+IP bucket 无法从表本身反查到账号，因此不作为账号身份表删除。

## 9. 必须回归

- exact confirmation
- storage failure 时 User/AuthIdentity 保留
- 注销进行中普通 API 被锁；正确密码 login 只能签发带 `account_deletion_in_progress=true` 的恢复 token
- 不同 request_id 加入同一注销
- 已存在 S1-021 operation 可被 Account Delete 继续
- Account Delete gate 建立后外部 Data Delete 返回 423，不能生成竞争 S1-021 operation
- 最终 User/AuthIdentity/receipts/gate 同时消失
- 旧 token 普通 API 失效
- 同邮箱重新注册得到新 user_id
- PostgreSQL 旧请求 stale commit 被 Account Delete gate 阻止
- 多用户 owner isolation
- 本地 outbox / onboarding 只清当前 owner
