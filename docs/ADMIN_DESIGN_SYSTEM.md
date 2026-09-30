# Admin Design System

迹忆 Admin 使用独立的企业级设计语言：专业、稳重、克制、高信息密度但不拥挤。保留迹忆品牌识别，不复制消费端故事化布局。

## 视觉方向

深色稳定侧栏、冷中性浅背景、白色运营 surface、轻边框和低 elevation；主操作使用迹忆蓝；success/warning/error/info 都同时提供文字，不仅依赖颜色。

常规 control 高度 36px，认证大型 control 40px；radius 8-10px；表格保持可读密度。

## 共享组件

AdminUi.tsx 统一提供 AdminShell、SideNavigation、TopBar、PageHeader、MetricCard、StatusCard、DataTable、FilterBar、SearchField、DetailSection、DescriptionList、StatusBadge、EmptyState、Loading/Skeleton、ErrorState、PermissionDenied、ConfirmDialog、DangerConfirmDialog、Drawer/Modal、Pagination、AuditTimeline、TechnicalDetails、SettingRow、SettingSection、SecretConfiguredState。

页面必须组合这些组件，避免一页一套 lookalike。

## Responsive

正式验收宽度：1024、1280、1440、1920。表格可以内部横向滚动，但 document 本身在 1024 不允许横向溢出，关键状态和主要操作必须可发现。

## Accessibility

要求键盘可达、可见 focus ring、语义 label、dialog focus trap、table header、非纯颜色状态、125% browser zoom 可用、reduced-motion 支持，危险操作文案不得裁切。