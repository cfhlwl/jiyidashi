# JiYi Production Admin Console V1

ADMIN-001 建立迹忆第一套生产运营管理后台。它是运营产品，不是数据库浏览器，也不是开发调试面板。

## 产品范围

主导航包含：概览、用户、家庭、会员与额度、数据任务、安全中心、AI 服务、文件存储、系统运行、审计日志、系统设置、管理员。

前端位于 admin/，采用 React、TypeScript、Vite、Ant Design 5 和 React Router，并通过迹忆企业级 token layer 统一视觉。

后端只通过 /admin/api/v1/* 暴露审核过的 Admin DTO。普通迹忆用户 bearer token 不是 Admin 凭证。

## 运营投影

V1 支持生产概览、用户运营元数据、家庭成员结构与授权类别汇总、数据删除和当前账号注销状态、安全告警、AI/语音识别/记忆检索/存储安全配置投影、系统运行信息、Admin 审计和管理员账号管理。

所有列表使用有界查询和确定性排序，不直接序列化 ORM，也不提供任意 SQL 或任意过滤语言。

## 隐私边界

V1 不返回或浏览：Memory 正文、照片内容、精确坐标、Family 私有内容、AI 私有回答、OCR/Vision 输出、存储对象 key、签名下载地址、用户认证 token、密码 hash、provider secret。

Admin V1 没有 break-glass 私有内容入口。

## Runtime quota

FREE、PERSONAL、FAMILY、PREMIUM 四个商业方案使用 PostgreSQL 中 revisioned quota catalog 作为运行时权威。首次初始化必须四个方案一次性完整提交。LEGACY_FULL 继续保持代码拥有的迁移兼容 unlimited 语义，不在后台营销或编辑。

## 危险操作

统一顺序：打开操作 → 明确展示影响 → 二次确认 → fresh Admin session/role 锁定 → resource revision 校验 → canonical mutation → audit → stale response suppression。

V1 不新增用户封禁、强删 user row、隐私授权代操作、secret editor、SQL console、支付/订单/退款系统。

## 初始管理员

首个 SUPER_ADMIN 只允许通过部署 CLI python -m app.maintenance.admin_bootstrap 创建。需要 ADMIN_BOOTSTRAP_EMAIL、ADMIN_BOOTSTRAP_PASSWORD，可选 ADMIN_BOOTSTRAP_NAME。存在有效 SUPER_ADMIN 后 bootstrap 自动拒绝重复初始化。

## Frontend dependency gate

Admin CI installs only the committed lockfile and runs two blocking audits:

- `npm audit --omit=dev --audit-level=high` for browser-shipped dependencies;
- `npm audit --audit-level=high` for the complete runtime/dev/test/build graph.

No advisory allowlist is active. Any unallowlisted high/critical result fails ADMIN-001.
The complete `npm audit --json` result is also retained in the Admin artifact for
moderate/low triage.

Dependency-only review hardening upgraded:

- `@playwright/test 1.55.0 -> 1.63.0`;
- `vite 7.1.7 -> 7.3.6`;
- `vitest 3.2.4 -> 3.2.7`;
- the prior runtime fix remains `react-router-dom 6.30.1 -> 6.30.6`.

After these upgrades, both high/critical gates pass. The full audit currently reports
only moderate findings. The remaining React Router findings require a breaking 7.x
migration; the remaining Vitest mocker finding requires a breaking Vitest 5 migration.
ADMIN-001 does not use `npm audit fix --force` or silently cross either major-version
boundary.
