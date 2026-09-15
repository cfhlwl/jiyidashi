# V1 API 基线

Base path:

```text
/v1
```

## 开发登录

```http
POST /v1/auth/dev-token
```

仅 development 使用。

## Memory

```http
POST   /v1/memories
GET    /v1/memories/{id}
DELETE /v1/memories/{id}
GET    /v1/timeline
POST   /v1/memory/query
GET    /v1/memory/summarize/day
```

示例：

```json
POST /v1/memories
{
  "memory_type": "NOTE",
  "content": "医生让我下个月18号复查",
  "source_type": "USER_TEXT",
  "confidence": 1.0,
  "is_confirmed": true
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

示例：

```json
POST /v1/objects
{
  "name": "护照"
}
```

随后：

```json
POST /v1/objects/{id}/locations
{
  "location_text": "书房左侧柜子第二层",
  "source_type": "USER_VOICE",
  "confidence": 1.0
}
```

查询：

```json
POST /v1/memory/query
{
  "question": "我的护照在哪里？"
}
```

命中：

```json
{
  "answer": "你最后一次记录“护照”的位置是：书房左侧柜子第二层。",
  "can_answer": true,
  "certainty": "confirmed",
  "reason": null,
  "intent": "FIND_OBJECT",
  "evidence": [],
  "memory_ids": []
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

## 自动位置

```http
POST /v1/location/batch
```

暂停记录时服务端返回：

```http
409 RECORDING_PAUSED
```

因此即使客户端后台任务没有及时停掉，也不能继续写入自动轨迹。

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
