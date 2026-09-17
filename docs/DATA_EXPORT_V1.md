# 用户数据导出 JSON v1

<!-- [人工注释][S1-020] 本文冻结 Stage 1D1 的首版个人数据导出边界；删除账号、批量删除、ZIP 媒体附件不属于本协议。 -->

`GET /v1/export/data` 仅接受当前登录用户的 Bearer Token，不接受可改变数据归属的 `user_id` 参数。

响应为可下载 JSON，`format` 固定为 `jiyidashi.user-export.v1`，包含：

- 当前用户 profile / timezone / locale；
- 未删除的 Memory 与对应 MemorySource / Evidence；
- Object 与 ObjectLocation 历史，并保留 `CURRENT / STALE / UNKNOWN` 状态；
- PrivacyState 与 PrivacyPauseInterval；
- 当前用户媒体业务元数据及仍可用的 Evidence 关联。

<!-- [人工注释][S1-020] 删除 Memory 后不得通过 ObjectLocation 历史重新泄露被删除的位置事实；
backing Memory 已删除的位置行保留历史标识，但强制按 STALE 导出并对事实字段做 tombstone/redaction。 -->
当 ObjectLocation 的 backing Memory 已被删除时，V1 保留：`id`、`object_id`、`recorded_at`，并输出 `status="STALE"`、`redacted=true`、`redaction_reason="BACKING_MEMORY_DELETED"`。这类行的 `memory_id`、`location_text`、`place_id`、`confidence` 均为 `null`。未删除 backing Memory 的正常历史位置仍按原字段导出。

<!-- [人工注释][S1-020] 媒体导出只允许业务元数据，不得泄露对象存储实现细节或临时访问能力。 -->
媒体导出明确不包含 `upload_object_key`、`object_key`、`storage_etag`、签名 URL、bucket/endpoint 或凭证。

<!-- [人工注释][S1-020] V1 超限必须整体失败而不是静默截断，确保“导出成功”始终表示该格式覆盖了全部当前可导出记录。 -->
V1 每个集合最多导出 5000 条；任一集合超限返回 HTTP 413。后续如需超大账号导出，应单独设计异步/分片导出协议。

响应带 `Cache-Control: no-store`，避免个人导出内容被中间缓存长期保存。
