# 迹忆（jiyidashi）

> 你负责生活，我帮你记住。

迹忆是一款面向 Android、iOS 与微信小程序的“个人 AI 第二记忆”产品。V1.0 先验证一个核心闭环：

**记录 → 保存 → 找到 → 相信**

当前分支是 V1 基础工程，重点不是堆功能，而是先把可信记忆模型、对象位置查询、隐私暂停与三端工程骨架建立起来。

<!-- [人工注释][DOC-PROGRESS-001] 统一项目进度入口，后续开发状态以 DEVELOPMENT_PROGRESS 为准。 -->
## 开发进度与代码审查规则

- **开发进度总表：** `docs/DEVELOPMENT_PROGRESS.md`
- **人工代码注释规范：** `docs/CODE_ANNOTATION_RULES.md`
- **高层开发路线：** `docs/ROADMAP.md`

状态约定：

- 🔵 进行中
- 🟠 已实现、待审查 / 待合并
- ✅ 已合并 `main` 且验收完成
- ⬜ 未开始
- ⏸ 延后
- 🚫 当前版本不做

从 2026-09-15 起，人工新增或修改的源码逻辑必须使用统一的 `[人工注释][任务ID]` 标记；自动生成文件、lockfile、二进制资源和不支持注释的严格 JSON 按规范中的例外规则处理。

## 仓库结构

```text
backend/        FastAPI 后端与核心 Memory API
mobile/         Flutter Android/iOS 主客户端
miniprogram/    微信小程序（Taro）基础工程
docs/           PRD、架构、接口、进度与代码规范
```

## V1 第一阶段已覆盖

- 开发环境 JWT 登录（默认关闭，仅显式开启 `ENABLE_DEV_AUTH` 后可用）
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

<!-- [人工注释][FND-004] 新环境必须先执行 Alembic migration，再启动 API；AUTO_CREATE_SCHEMA 默认关闭。 -->
### SQLite 本地开发

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

访问：

- API: `http://127.0.0.1:8000`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

开发环境如需测试 Token，必须在**本地开发环境**的 `.env` 中显式设置：

```text
APP_ENV=development
ENABLE_DEV_AUTH=true
```

然后才能调用：

```http
POST /v1/auth/dev-token
Content-Type: application/json

{
  "nickname": "测试用户"
}
```

<!-- [人工注释][FND-019] production/prod 模式下 dev auth 被配置校验和 endpoint 双重硬关闭，不能通过 ENABLE_DEV_AUTH=true 重新开启。 -->
生产环境必须使用正式认证方案。`APP_ENV=production` 或 `APP_ENV=prod` 时，`ENABLE_DEV_AUTH=true` 会导致配置校验失败；即使绕过配置校验，`/v1/auth/dev-token` 也会返回 404。

## Docker / PostgreSQL 开发依赖

```bash
docker compose up -d postgres redis
```

然后将 `backend/.env` 中的数据库切换为：

```text
DATABASE_URL=postgresql+psycopg://jiyi:jiyi@127.0.0.1:5432/jiyi
```

首次启动或 schema 版本更新后必须执行：

```bash
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

不要依赖 `AUTO_CREATE_SCHEMA` 代替 migration；该开关默认保持 `false`。

## 测试

```bash
cd backend
pytest
ruff check .
```

正式 `backend-ci` 同时在 SQLite 和 PostgreSQL 上执行 Alembic baseline，并在 PostgreSQL 上验收 ObjectLocation 的单 `CURRENT` 约束和 `FOR UPDATE` 锁语义。

## 当前开发原则

1. **结构化检索优先于 LLM。**
2. **无证据不生成个人事实。**
3. **用户主动记录优先级最高。**
4. **物品位置保留历史，不覆盖旧记录。**
5. **暂停记录后自动定位不得继续入库。**
6. **APP 是自动记录主端，小程序不是长期后台定位主端。**
7. **V1 暂不做医疗诊断、人脸识别、24 小时录音。**
8. **每次开发先更新进度 ID，源码变更同步加 `[人工注释][任务ID]`。**

更多信息见 `docs/`。
