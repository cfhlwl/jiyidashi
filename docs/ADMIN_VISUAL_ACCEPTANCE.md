# Admin Visual Acceptance

ADMIN-001 使用 deterministic Playwright 做正式视觉验收。

## Fixture Boundary

只有 VITE_ADMIN_VISUAL_FIXTURES=1 时才启用 review fixture。fixture 只能经统一 Admin API boundary 消费，不是 production 默认数据。视觉测试阻止访问本地 review server 之外的网络。

## Flagship Screens

1440 reference project 覆盖 Admin Login、Dashboard、Users、User Detail、Families、Family Detail、Entitlement & Quota、Data Tasks、Account Deletion、Security Center、AI Services、Storage、System Health、Audit Log、System Settings、Admin Accounts，以及 Empty、Loading、Error、Permission Denied、Danger Confirm。

## Responsive Matrix

Dashboard 额外覆盖 1024x800、1280x900、1920x1080；检查 document-level horizontal overflow。表格内部受控横向滚动允许。

## Determinism

CI 使用 exact-head checkout、lockfile Node dependencies、固定 Playwright/Chromium、zh-CN locale、Asia/Shanghai timezone、light color scheme、deterministic fixture timestamps/data、无外部网络依赖。

visual-artifacts/manifest.json 记录每张截图的 SHA-256 和 bytes。

## Mismatch Proof

独立 proof 会故意将 Dashboard 横向偏移 3px 后与 committed Golden 比较。只有 Playwright 返回 non-zero 时 proof gate 才 PASS，证明视觉差异真的能被检测。

## Accessibility

Playwright 检查主要 control 有 accessible name、危险 dialog focus trap、125% zoom 时主要管理员操作仍可发现；CSS 提供 focus-visible 和 reduced-motion 支持。