import {
  fixtureAccountTasks,
  fixtureAdmins,
  fixtureAlerts,
  fixtureAudit,
  fixtureDashboard,
  fixtureDeletionTasks,
  fixtureFamilies,
  fixtureFamilyDetail,
  fixtureHealth,
  fixtureQuota,
  fixtureSession,
  fixtureSettings,
  fixtureUserDetail,
  fixtureUsers,
} from './fixtures'

export const fixtureMode = import.meta.env.VITE_ADMIN_VISUAL_FIXTURES === '1'

const safeErrors: Record<string, string> = {
  ADMIN_AUTH_REQUIRED: '登录状态已失效，请重新登录',
  ADMIN_SESSION_STALE: '登录状态刚刚发生变化，请重新登录',
  ADMIN_INVALID_CREDENTIALS: '账号或密码不正确',
  AUTH_RATE_LIMITED: '登录尝试过于频繁，请稍后再试',
  ADMIN_PERMISSION_DENIED: '你现在没有权限执行这个操作',
  ADMIN_CSRF_REQUIRED: '操作验证信息缺失，请刷新页面后重试',
  ADMIN_CSRF_INVALID: '操作验证已失效，请刷新页面后重试',
  ADMIN_STATE_STALE: '状态刚刚发生变化，请重新打开后再试',
  ADMIN_LAST_SUPER_ADMIN_REQUIRED: '至少需要保留一名可用的超级管理员',
  ADMIN_SELF_ROLE_CHANGE_DENIED: '不能修改自己的关键权限状态',
  ADMIN_QUOTA_POLICY_NOT_INITIALIZED: '请先完成会员额度配置',
  ADMIN_QUOTA_POLICY_UNAVAILABLE: '会员额度配置暂时不可用，请检查后再试',
  ADMIN_USER_NOT_FOUND: '没有找到这个用户',
  ADMIN_FAMILY_NOT_FOUND: '没有找到这个家庭',
  ADMIN_SECURITY_ALERT_NOT_FOUND: '没有找到这条安全事件',
  ADMIN_SECURITY_ALERT_NOT_RETRYABLE: '当前状态不需要再次发送',
  ADMIN_ACCOUNT_EXISTS: '这个管理员账号已经存在',
  ADMIN_ACCOUNT_NOT_FOUND: '没有找到这个管理员账号',
}

export class AdminApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message)
  }
}

function csrfToken() {
  const pair = document.cookie
    .split(';')
    .map((item) => item.trim())
    .find((item) => item.startsWith('jiyi_admin_csrf='))
  return pair ? decodeURIComponent(pair.slice('jiyi_admin_csrf='.length)) : null
}

function fixtureResponse<T>(path: string, method: string): T | undefined {
  if (!fixtureMode) return undefined
  if (path === '/auth/session') return fixtureSession as T
  if (path === '/auth/login') return fixtureSession as T
  if (path === '/auth/logout') return { message: '已安全退出' } as T
  if (path === '/dashboard') return fixtureDashboard as T
  if (path === '/users') return fixtureUsers as T
  if (/^\/users\/[^/]+$/.test(path)) return fixtureUserDetail as T
  if (path === '/families') return fixtureFamilies as T
  if (/^\/families\/[^/]+$/.test(path)) return fixtureFamilyDetail as T
  if (path === '/data-tasks/deletions') return fixtureDeletionTasks as T
  if (path === '/data-tasks/account-deletions') return fixtureAccountTasks as T
  if (path === '/security/alerts') return fixtureAlerts as T
  if (path === '/audit') return fixtureAudit as T
  if (path === '/system/settings') return fixtureSettings as T
  if (path === '/system/health') return fixtureHealth as T
  if (path === '/settings/quota-catalog') return fixtureQuota as T
  if (path === '/admins') return fixtureAdmins as T
  if (method !== 'GET') return { message: '操作已完成' } as T
  return undefined
}

export async function adminRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const fixture = fixtureResponse<T>(path, method)
  if (fixture !== undefined) {
    await Promise.resolve()
    return fixture
  }

  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = csrfToken()
    if (csrf) headers.set('X-CSRF-Token', csrf)
  }

  let response: Response
  try {
    response = await fetch(`/admin/api/v1${path}`, {
      ...init,
      method,
      headers,
      credentials: 'include',
      cache: 'no-store',
    })
  } catch {
    throw new AdminApiError('服务暂时不可用，请稍后重试', 0)
  }

  if (response.ok) {
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  let code: string | undefined
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') code = body.detail
  } catch {
    // Deliberately ignore arbitrary backend response bodies.
  }

  const fallback =
    response.status === 401
      ? '登录状态已失效，请重新登录'
      : response.status === 403
        ? '你现在没有权限执行这个操作'
        : response.status === 409
          ? '状态刚刚发生变化，请重新打开后再试'
          : response.status >= 500
            ? '服务暂时不可用，请稍后重试'
            : '操作没有完成，请检查后重试'
  throw new AdminApiError((code && safeErrors[code]) || fallback, response.status, code)
}

export function postJson<T>(path: string, payload?: unknown) {
  return adminRequest<T>(path, {
    method: 'POST',
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
}

export function putJson<T>(path: string, payload: unknown) {
  return adminRequest<T>(path, { method: 'PUT', body: JSON.stringify(payload) })
}

export function patchJson<T>(path: string, payload: unknown) {
  return adminRequest<T>(path, { method: 'PATCH', body: JSON.stringify(payload) })
}
