# 系统架构

## 总体结构

```text
Flutter Android/iOS ─┐
                     ├── API Gateway / FastAPI
微信小程序 ──────────┘          │
                               ├── PostgreSQL
                               ├── Redis
                               ├── Object Storage（后续）
                               └── AI Memory Gateway（后续）
```

V1 采用模块化单体，不提前拆微服务。

## 核心领域

- `users`
- `devices`
- `memories`
- `memory_sources`
- `objects`
- `object_locations`
- `places`
- `location_points`
- `visits`
- `reminders`
- `privacy_states`
- `family_members`
- `family_permissions`

## Memory 与 Evidence

`Memory` 是整理后的个人记忆。

`MemorySource` 是证据。

两者不能混为一谈。

示例：

```text
Memory
  “护照放在书房左侧柜子第二层”
       │
       └── MemorySource
              source=USER_VOICE
              raw_text=原始语音转写
              confidence=1.0
```

后续上传原始音频时，`source_id` 指向 `media_assets`。

## 查询策略

```text
Question
  ↓
Intent Router
  ↓
Structured Search
  ↓
Keyword Search
  ↓
Vector Search（后续）
  ↓
Evidence Ranking
  ↓
LLM Answer（后续）
```

原则是 **Structured First, LLM Last**。

“护照在哪里”不需要先问大模型，先查 `objects/object_locations`。

## 向量检索

第一轮基础工程暂未强行写死 embedding 维度和供应商。

原因：

1. 物品/时间/地点等核心查询首先应由结构化数据库完成。
2. embedding 模型在模型选型完成前不应该污染 schema。
3. 第二阶段可以增加 `memory_embeddings`，使用 PostgreSQL + pgvector。

推荐设计：

```text
memory_embeddings
- memory_id
- provider
- model
- dimension
- embedding vector(...)
- created_at
```

这样以后换 embedding 模型不需要改 `memories` 主表语义。

## 自动足迹

第一轮只建立 `location_points` 接口和隐私门禁。

第二阶段实现：

```text
UNKNOWN
→ STATIONARY
→ MOVING
→ POSSIBLE_VISIT
→ VISITING
→ LEAVING
```

最终长期价值来自 `Visit`，不是无限保存 GPS 原始点。

## 原生定位

Flutter 负责 UI 和业务。

Android 与 iOS 后台定位单独实现原生模块，避免核心能力完全绑定第三方 Flutter 插件。

## 安全基线

- 生产禁用 `/v1/auth/dev-token`
- 所有个人数据接口必须鉴权
- 用户 ID 永远从 Token 获取，不信任客户端 body 中的 user_id
- 对象位置查询限制在当前用户
- 删除 Memory 为软删除，查询必须过滤
- 隐私暂停是服务端最后一道门禁，不只依赖客户端
- 未来媒体对象存储必须私有桶 + 临时签名 URL
