# Admin Settings Policy

后台展示的每项设置必须属于四类之一：可在线修改、需要重新部署、只读、敏感配置。

## 可在线修改

ADMIN-001 唯一 writable whitelist 是商业会员 quota catalog。四方案完整原子更新，要求 SUPER_ADMIN、CSRF、二次确认、fresh role/session authority 和每行 expected_revision。

## 需要重新部署

AI/ASR provider 开关与模型、timeout/bounds、存储 wiring、足迹识别阈值、登录 rate-limit 阈值、analytics retention 等部署拥有配置只做安全展示，不提供保存按钮。

## 只读

应用/build 状态、服务 readiness、代码拥有的 embedding dimension、安全 endpoint host、聚合存储使用等。

## 敏感配置

AI/ASR/embedding key、对象存储 credential、JWT/Admin secret、database credential 等只返回“已配置/未配置”和安全来源文字，永不返回 secret 或可恢复 masked value。

## Quota Authority Precedence

首次 DB catalog 初始化之前，旧的 validated ENTITLEMENT_QUOTA_CATALOG env 仅作为升级迁移桥，避免 ADMIN-001 升级时无声改变已有商业行为。

一旦 DB 中存在任意 quota policy row：PostgreSQL 成为唯一 commercial quota runtime authority；必须四个商业方案完整存在；partial/corrupt state fail closed；env 不再与 DB 并行竞争。

LEGACY_FULL 始终保持代码拥有的 unlimited migration semantics。

## 用户会员调整

只有 DB catalog 已完整初始化后，用户才可以由 SUPER_ADMIN 调整为 FREE/PERSONAL/FAMILY/PREMIUM。mutation 使用 UserEntitlement revision 并审计 before/after 安全元数据。支付、价格、订单、退款、优惠券不属于 ADMIN-001。