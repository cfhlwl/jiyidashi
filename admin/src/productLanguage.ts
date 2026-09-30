import type { AdminRole } from './types'

export const roleLabel: Record<AdminRole, string> = {
  SUPER_ADMIN: '超级管理员',
  OPERATOR: '运营管理员',
  SUPPORT_READONLY: '支持人员（只读）',
}

export const planLabel: Record<string, string> = {
  FREE: '免费版',
  PERSONAL: '个人版',
  FAMILY: '家庭版',
  PREMIUM: '高级版',
  LEGACY_FULL: '历史兼容方案',
}

export const familyRoleLabel: Record<string, string> = {
  OWNER: '家庭创建者',
  MEMBER: '家庭成员',
}

export const permissionLabel: Record<string, string> = {
  VIEW_CURRENT_LOCATION: '当前位置',
  VIEW_FOOTPRINT: '今日足迹',
  VIEW_MEMORY: '记忆',
  VIEW_PHOTOS: '照片',
}

export const dataDeletionStatusLabel: Record<string, string> = {
  STORAGE_PENDING: '正在清理文件数据',
  WAITING_STORAGE_EXPIRY: '等待旧文件访问能力失效',
  WAITING_STORAGE_QUIET: '确认文件清理完成',
  STORAGE_FAILED: '文件清理未完成',
  DB_PENDING: '正在清理账号内数据',
  DB_FAILED: '数据清理未完成',
  COMPLETED: '已完成',
}

export const securitySeverityLabel: Record<string, string> = {
  INFO: '提示',
  LOW: '低',
  MEDIUM: '中',
  HIGH: '高',
  CRITICAL: '严重',
}

export const securityCategoryLabel: Record<string, string> = {
  LOGIN_PROTECTION: '登录保护',
  FAMILY_ACCESS: '家庭敏感访问',
  DATA_SECURITY: '数据安全',
  STORAGE: '文件存储',
  SYSTEM_SECURITY: '系统安全',
}

export const deliveryStatusLabel: Record<string, string> = {
  PENDING: '等待发送',
  DELIVERED: '已送达',
  RETRYABLE_FAILURE: '等待重试',
  TERMINAL_FAILURE: '发送未完成',
}

export const serviceStatusLabel: Record<string, string> = {
  NORMAL: '正常',
  DISABLED: '未启用',
  WARNING: '需要关注',
  ERROR: '异常',
}

export const auditActionLabel: Record<string, string> = {
  ADMIN_LOGIN: '管理员登录',
  ADMIN_LOGOUT: '管理员退出',
  ADMIN_SESSION_ROTATE: '登录会话更新',
  ADMIN_ACCOUNT_CREATE: '创建管理员',
  ADMIN_ACCOUNT_UPDATE: '修改管理员',
  ADMIN_PASSWORD_RESET: '重置管理员密码',
  ADMIN_SESSIONS_REVOKE: '撤销管理员会话',
  ENTITLEMENT_QUOTA_CATALOG_UPDATE: '修改使用额度',
  USER_ENTITLEMENT_ADJUST: '调整会员方案',
  SECURITY_ALERT_RETRY: '重试安全通知',
  ADMIN_BOOTSTRAP: '初始化超级管理员',
}

export const auditTargetLabel: Record<string, string> = {
  ADMIN_SESSION: '管理员会话',
  ADMIN_ACCOUNT: '管理员账号',
  RUNTIME_POLICY: '运行策略',
  USER: '用户',
  SECURITY_ALERT: '安全事件',
}

export function safeLabel(map: Record<string, string>, value: string | null | undefined, fallback = '未知状态') {
  if (!value) return fallback
  return map[value] ?? fallback
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function formatBytes(value: number | null | undefined) {
  if (value == null) return '不限'
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`
  return `${(value / 1024 ** 3).toFixed(2)} GB`
}

export function formatNumber(value: number | null | undefined) {
  if (value == null) return '不限'
  return new Intl.NumberFormat('zh-CN').format(value)
}
