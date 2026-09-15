# 迹忆（jiyidashi）

> 你负责生活，我帮你记住。

迹忆是一款面向 Android、iOS 与微信小程序的“个人 AI 第二记忆”产品。V1.0 先验证一个核心闭环：

**记录 → 保存 → 找到 → 相信**

当前分支是 V1 基础工程，重点不是堆功能，而是先把可信记忆模型、对象位置查询、隐私暂停与三端工程骨架建立起来。

## 仓库结构

```text
backend/        FastAPI 后端与核心 Memory API
mobile/         Flutter Android/iOS 主客户端
miniprogram/    微信小程序（Taro）基础工程
docs/           PRD、架构与接口说明
```

## V1 第一阶段已覆盖

- 开发环境 JWT 登录
- 文字/语音/照片等 Memory 数据模型
- Memory Evidence / 可信度字段
- “东西放哪里”对象与位置历史
- `NO EVIDENCE -> NO MEMORY` 查询原则
- 基础记忆搜索
- 自动记录隐私暂停/恢复
- 批量位置点上传入口
- Flutter 5 个一级导航骨架
- 微信小程序基础页面骨架
- PostgreSQL + Redis 本地开发环境
- 后端单元测试与 CI

> 当前不会把 AI 猜测当成用户事实。没有证据时，查询接口必须明确返回 `NO_EVIDENCE`。

## 本地启动后端

需要 Python 3.12+。

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

访问：

- API: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

开发环境可以先获取一个测试 Token：

```http
POST /v1/auth/dev-token
Content-Type: application/json

{
  "nickname": "测试用户"
}
```

生产环境必须禁用此接口并接入正式登录方案。

## Docker 开发依赖

```bash
docker compose up -d postgres redis
```

然后将 `backend/.env` 中的数据库切换为：

```text
DATABASE_URL=postgresql+psycopg://jiyi:jiyi@127.0.0.1:5432/jiyi
```

## 测试

```bash
cd backend
pytest
ruff check .
```

## 当前开发原则

1. **结构化检索优先于 LLM。**
2. **无证据不生成个人事实。**
3. **用户主动记录优先级最高。**
4. **物品位置保留历史，不覆盖旧记录。**
5. **暂停记录后自动定位不得继续入库。**
6. **APP 是自动记录主端，小程序不是长期后台定位主端。**
7. **V1 暂不做医疗诊断、人脸识别、24 小时录音。**

更多信息见 `docs/`。
