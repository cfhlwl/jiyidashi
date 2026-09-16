<!-- [人工注释][FND-025] 本文档必须与当前公开 schema 同步；客户端只能声明 capture_source，可信等级由服务端所有。 -->
<!-- [人工注释][S1-001] Stage 1 正式认证接口已加入公开 API；dev-token 仍只用于显式开启的开发/测试环境。 -->
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

`timezone` 必须是可解析的 IANA 时区名称。`user_id` 由服务端生成，客户端不能指定。

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

账号不存在与密码错误统一返回 `401 INVALID_CREDENTIALS`，不通过错误信息泄露账号存在性。

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

`PATCH /v1/user` 只允许修改公开资料字段；登录邮箱/身份归属不能通过 profile API 修改。

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
DELETE /v1/memories/{id}
GET    /v1/timeline
POST   /v1/memory/query
GET    /v1/memory/summarize/day
```

### 新建 Memory

公开客户端只能提交用户实际使用的采集通道：

- `USER_TEXT`
- `USER_VOICE`
- `USER_PHOTO`

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

随后记录位置：

```json
POST /v1/objects/{id}/locations
{
  "location_text": "书房左侧柜子第二层",
  "capture_source": "USER_VOICE",
  "recorded_at": "2026-09-15T20:36:00+08:00"
}
```

`recorded_at` 可省略；如果客户端显式提交，必须携带时区偏移。

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
      "occurred_at": "2026-09-15T12:36:00Z",
      "excerpt": "护照：书房左侧柜子第二层",
      "confidence": 1.0
    }
  ],
  "memory_ids": [
    "22222222-2222-2222-2222-222222222222"
  ]
}
```

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

## 隐私

```http
GET  /v1/privacy/status
POST /v1/privacy/pause
POST /v1/privacy/resume
```

暂停 30 分钟：

```json
{
  "duration_minutes": 30
}
```
