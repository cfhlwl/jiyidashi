# Admin Security Model

ADMIN-001 建立与普通迹忆用户完全独立的 Admin 身份和会话边界。

## Role Matrix

SUPER_ADMIN：管理员账号/职责、runtime quota、用户会员方案、危险运营动作、全部审核过的只读投影。

OPERATOR：用户/家庭/任务/安全/健康只读和有限运营动作；不能管理管理员、runtime quota 或核心安全/部署设置。

SUPPORT_READONLY：仅审核过的支持诊断只读投影；无 mutation。

前端隐藏只是 UX，服务端授权始终 canonical。

## Browser Session

Admin login 创建随机 opaque session token 和独立 CSRF token。PostgreSQL 只保存 digest，不保存 raw token。session cookie 为 HttpOnly；SameSite Strict；production 为 Secure；浏览器不得用 localStorage/sessionStorage 保存 privileged credential。

mutation 需要 CSRF cookie/header 与服务端摘要一致。reauthentication 会 rotate 已呈现旧 session。logout/revoke 立即失效。Admin role/disabled/revision 改变后旧 session fail closed。普通用户 bearer token 不参与 Admin auth。

## Fresh Mutation Authority

每次 mutation 都重新锁定 AdminSession 和 AdminAccount，复核 disabled/revoked/expiry/account revision/current role/CSRF，随后业务资源再执行自己的 expected_revision。

## 管理员保护

正常 API 不允许修改自己的关键 role/disabled；禁止删除或停用最后一个 active SUPER_ADMIN；SUPER_ADMIN elevation 使用更强 typed confirmation；password reset 会 revoke 目标有效 session。

## Audit

每个受审核 mutation append AdminAuditEvent：actor、role snapshot、bounded action/target/result、request reference、bounded safe metadata、timestamp。PostgreSQL trigger 直接拒绝 UPDATE/DELETE audit row。V1 没有审计删除/编辑 API。

审计禁止保存密码、session/CSRF token、provider key、用户私有内容或任意 request body。

## Privacy

V1 不提供 Memory/photo/location/AI/OCR/Vision 私有内容浏览，也没有 break-glass 内容访问。