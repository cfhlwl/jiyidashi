# Data Delete V1（S1-021）

## 目标与边界

`POST /v1/data/delete` 删除当前认证用户拥有的**应用数据**，并在数据库、对象存储和
当前持久化临时状态之间提供可重试的一致删除语义。

本接口**不是账号注销**：`users` 与 `auth_identities` 在 S1-021 中保留；S1-022 才负责
最终账号身份删除。删除完成后，用户仍可使用原账号登录并重新产生新的数据。

## 请求

```json
{
  "request_id": "4e379bd9-5ae6-4de0-909f-ab2a12fd5987",
  "confirmation": "DELETE_MY_DATA"
}
```

- `request_id`：客户端生成并在同一次删除重试中保持不变。
- `confirmation`：必须精确等于 `DELETE_MY_DATA`；错误值在任何数据变更前返回 `422`。
- 同一个 `request_id` 重试是幂等的；任务已经 `COMPLETED` 后再次重放只读取完成回执，
  不会删除完成后新创建的数据。
- 一个用户同一时间只能有一个未完成删除任务；用另一个 `request_id` 并发发起时返回
  `409 DATA_DELETION_ALREADY_IN_PROGRESS`。

## 返回状态

- `200`：删除已经 `COMPLETED`。
- `202`：任务安全地进入等待状态；客户端必须使用同一个 `request_id` 重试。
- `423 DATA_DELETION_IN_PROGRESS`：删除未完成期间，普通用户数据 API 被封锁。
- `503 DATA_DELETION_STORAGE_UNAVAILABLE`：对象存储删除/枚举未确认，数据库数据不会
  被当作已成功删除。
- `503 DATA_DELETION_STORAGE_NOT_EMPTY`：旧上传能力失效后仍无法把用户对象前缀收敛为空。
- `503 DATA_DELETION_DATABASE_FAILED`：最终数据库事务失败并整体回滚，可用同一请求重试。
- `500 DATA_DELETION_STORAGE_OWNERSHIP_INVALID`：数据库中的媒体 key 越出当前用户前缀；
  服务端 fail closed，不会尝试删除该 key。

## 持久化清单

当前 S1-021 显式覆盖：

- `devices`
- `places`, `visits`
- `memories`, `memory_edits`, `memory_sources`
- `location_points`
- `objects`, `object_locations`
- `reminders`
- `privacy_states`, `privacy_pause_intervals`
- 与当前用户有关的 `family_members`, `family_permissions`
- `media_assets`, `media_asr_claims`, `media_evidence_links`
- `client_mutations`
- 对象存储 final 用户前缀与 staging 用户前缀，包括数据库没有记录的孤儿对象

有意保留：

- `users`
- `auth_identities`
- `auth_rate_limit_buckets`：这里只保存不可逆 HMAC bucket，当前没有 user_id 归属
- `data_deletion_operations`：保留最小完成回执用于幂等；对象 key obligation 完成后会清除

当前后端没有 Redis 或进程内的“用户内容缓存”。媒体 ASR claim、Memory Edit 审计历史
与离线幂等账本都是现有可映射到用户的临时/持久状态，已纳入上面的删除事务。

## 为什么可能先返回 202

媒体上传使用短时预签名 PUT。删除开始前已经签出的 PUT 即使第一次对象清理完成，仍可能
在票据过期前把 staging 对象重新写回。因此，只要删除任务观察到 `MediaAsset`，服务端就：

1. 立即封锁该用户的普通数据 API；
2. 捕获数据库已知 object key，并枚举用户 staging/final 前缀抓取孤儿对象；
3. 删除当前可见对象；
4. 等待现行代码允许的最大旧上传签名寿命（3600 秒）过去；
5. 进入独立 `WAITING_STORAGE_QUIET`，至少持续 `STORAGE_DELETE_SETTLE_SECONDS`；
6. quiet 期间只要再次发现 late object，就 DELETE，并从该发现时刻重新开始 quiet timer；
7. 首次发现 DB 无引用的 staging orphan 时，重新建立“最大旧签名 TTL + settle”上界；
8. quiet window 真正结束后再做最终 LIST；为空才进入 DB cleanup；
9. 最后才在一个数据库事务中删除应用数据并写入 `COMPLETED`。

这意味着 `202 WAITING_STORAGE_EXPIRY` 与 `202 WAITING_STORAGE_QUIET` 都是安全中间态，
不是“已经删除成功”的假成功。这里明确禁止用瞬时连续 LIST 多次替代真实时间上的 settle。

`STORAGE_DELETE_SETTLE_SECONDS` 必须按部署实际配置为：至少覆盖对象存储、CDN/代理或网络层
允许的一次已开始 PUT 的最大 in-flight 生命周期；默认值为 300 秒，仅是默认部署参数，
生产环境应按实际 provider/代理边界校准。

## 失败与重试不变量

- 对象存储删除发生在 DB destructive cleanup 之前；未确认 storage cleanup 时不删除业务 DB。
- 每个已发现 object key 都先写入 durable obligation；远端 DELETE 成功后才记录完成。
- 进程若在远端 DELETE 后、数据库提交前崩溃，重试会再次 DELETE 同一个 key；DELETE 必须
  以“对象已不存在也视为收敛”为幂等语义。
- 最终数据库应用数据删除与 `COMPLETED` 在同一事务提交；异常时整体 rollback。
- 删除期间普通请求通过 User row lock + durable deletion gate 阻止新业务数据从竞态窗口写入。
- 跨用户对象/数据库行永远不通过客户端 owner 参数选择；删除目标只来自 Bearer token。
- DB 记录里的 object key 也必须再次通过当前用户 storage prefix 校验，不能把持久化 key 当作可信 owner 声明。


## 跨 Transaction 旧请求门禁

普通数据请求在准入时记录当前用户的 `data_deletion_operations` generation。每次
`GuardedSession.commit()` 都会重新获取 User KEY SHARE，并重新核对 generation：

- generation 未变化且没有 active deletion：允许提交；
- 删除任务在请求执行期间创建（即使已经 `COMPLETED`）：旧请求 generation 失效，提交返回
  `409 DATA_DELETION_REQUEST_STALE` 并回滚；
- 删除完成后新发起的请求会读取新的 generation，因此可以正常创建新数据。

Location batch 的唯一键竞争另外改为 SAVEPOINT，仅回滚 nested transaction，不再为了重试
主动释放请求入口的外层 User 锁。Session generation guard 继续覆盖 Media/Voice ASR、
Object 并发回退和离线幂等服务中的 commit/rollback 边界。
