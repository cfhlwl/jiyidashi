import assert from 'node:assert/strict'
import test from 'node:test'

type RequestOptions = { url: string; method: string; data?: unknown; header?: Record<string, string> }

const USER_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const SESSION_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

function tokenResponse(overrides: Record<string, unknown> = {}) {
  return {
    access_token: 'access-a',
    refresh_token: 'refresh-a',
    session_id: SESSION_ID,
    token_type: 'bearer',
    user_id: USER_ID,
    access_expires_at: '2099-01-01T00:00:00Z',
    refresh_expires_at: '2099-02-01T00:00:00Z',
    account_deletion_in_progress: false,
    ...overrides,
  }
}

test('AUTH-MINI-01 controlled Taro contract regressions', async () => {
  ;(globalThis as Record<string, unknown>).JIYI_API_BASE_URL = 'https://api.example.test/v1'
  ;(globalThis as Record<string, unknown>).JIYI_ALLOW_API_BASE_EDIT = false
  for (const key of [
    'ENABLE_ADJACENT_HTML',
    'ENABLE_CLONE_NODE',
    'ENABLE_CONTAINS',
    'ENABLE_INNER_HTML',
    'ENABLE_MUTATION_OBSERVER',
    'ENABLE_SIZE_APIS',
    'ENABLE_TEMPLATE_CONTENT',
  ]) (globalThis as Record<string, unknown>)[key] = false
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  const calls: RequestOptions[] = []
  let handler: (options: RequestOptions) => Promise<{ statusCode: number; data: unknown }>
    = async () => ({ statusCode: 500, data: { detail: 'unconfigured test request' } })
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: RequestOptions) => {
    calls.push(options)
    return handler(options)
  }

  const api = await import('../src/services/api')
  await api.logout()
  storage.clear()
  calls.length = 0

  handler = async (options) => {
    assert.equal(options.url, 'https://api.example.test/v1/auth/register')
    return {
      statusCode: 201,
      data: {
        user_id: USER_ID,
        verification_required: true,
        verification_delivery_pending: false,
      },
    }
  }
  const registration = await api.registerAccount({ email: 'new@example.com', password: 'password-1234', nickname: '新用户' })
  assert.equal(registration.user_id, USER_ID)
  assert.equal(api.isAuthenticated(), false)
  assert.equal(api.currentAuthenticatedUserId(), null)
  assert.equal(storage.has('jiyi_auth_session'), false)

  handler = async (options) => {
    assert.equal(options.url, 'https://api.example.test/v1/auth/login')
    assert.equal(options.header?.Authorization, undefined)
    return { statusCode: 200, data: tokenResponse() }
  }
  await api.loginAccount('a@example.com', 'password-1234')
  assert.equal(api.currentAuthenticatedUserId(), USER_ID)
  assert.equal(storage.has('jiyi_access_token'), false)
  assert.match(String(storage.get('jiyi_auth_device_id')), /^[0-9a-f-]{36}$/i)

  let refreshCalls = 0
  let protectedCalls = 0
  handler = async (options) => {
    if (options.url.endsWith('/privacy/status')) {
      protectedCalls += 1
      if (protectedCalls <= 2) return { statusCode: 401, data: { detail: 'AUTH_SESSION_EXPIRED' } }
      return { statusCode: 200, data: { recording_paused: false } }
    }
    if (options.url.endsWith('/auth/refresh')) {
      refreshCalls += 1
      assert.deepEqual(options.data, { refresh_token: 'refresh-a' })
      return { statusCode: 200, data: tokenResponse({ access_token: 'access-b', refresh_token: 'refresh-b', session_id: SESSION_ID }) }
    }
    throw new Error(`unexpected request ${options.url}`)
  }
  const [first, second] = await Promise.all([api.getPrivacyStatus(), api.getPrivacyStatus()])
  assert.equal(first.recording_paused, false)
  assert.equal(second.recording_paused, false)
  assert.equal(refreshCalls, 1)
  assert.equal(storage.has('jiyi_auth_session'), true)
  assert.equal((storage.get('jiyi_auth_session') as any).refresh_token, 'refresh-b')

  handler = async (options) => {
    if (options.url.endsWith('/privacy/status')) return { statusCode: 401, data: { detail: 'AUTH_SESSION_EXPIRED' } }
    if (options.url.endsWith('/auth/refresh')) throw new Error('simulated response loss')
    throw new Error(`unexpected request ${options.url}`)
  }
  await assert.rejects(api.getPrivacyStatus())
  assert.equal(api.isAuthenticated(), false)
  assert.equal(api.currentAuthenticatedUserId(), null)

  handler = async (options) => {
    assert.equal(options.url, 'https://api.example.test/v1/auth/login')
    return { statusCode: 200, data: tokenResponse({ user_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' }) }
  }
  await api.loginAccount('b@example.com', 'password-1234')
  assert.equal(api.currentAuthenticatedUserId(), 'dddddddd-dddd-4ddd-8ddd-dddddddddddd')
  assert.equal((storage.get('jiyi_auth_session') as any).user_id, 'dddddddd-dddd-4ddd-8ddd-dddddddddddd')
  handler = async () => ({ statusCode: 200, data: tokenResponse() })
  await api.loginAccount('a@example.com', 'password-1234')
  const logoutPromise = api.logout()
  assert.equal(api.isAuthenticated(), false)
  assert.equal(api.currentAuthenticatedUserId(), null)
  await logoutPromise
  assert.equal(calls.at(-1)?.url, 'https://api.example.test/v1/auth/logout')
  assert.match(calls.at(-1)?.header?.Authorization || '', /^Bearer access-a$/)
})

test('AUTH-MINI-01 malformed complete session responses fail closed', async () => {
  const api = await import('../src/services/api')
  assert.throws(
    () => api.parseMiniAuthSession({ access_token: 'a', user_id: USER_ID }),
    /认证响应异常/,
  )
  assert.throws(
    () => api.parseMiniAuthSession({
      ...tokenResponse(),
      refresh_token: undefined,
    }),
    /认证响应异常/,
  )
})

test('profile projection uses the validated session owner after legacy owner removal', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  const calls: RequestOptions[] = []
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: RequestOptions) => {
    calls.push(options)
    if (options.url.endsWith('/auth/login')) return { statusCode: 200, data: tokenResponse() }
    if (options.url.endsWith('/user')) {
      return {
        statusCode: 200,
        data: {
          id: USER_ID,
          email: 'a@example.com',
          nickname: 'A',
          timezone: 'Asia/Shanghai',
          locale: 'zh-CN',
          elder_mode_enabled: false,
        },
      }
    }
    throw new Error(`unexpected request ${options.url}`)
  }
  const api = await import('../src/services/api')
  await api.logout()
  await api.loginAccount('a@example.com', 'password-1234')
  assert.equal(storage.has('jiyi_authenticated_user_id'), false)
  const profile = await api.getProfile()
  assert.equal(profile.id, USER_ID)
  assert.equal(calls.at(-1)?.url, 'https://api.example.test/v1/user')
})

test('delayed 401 reuses the rotated access token without replaying the old refresh token', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  let handler: (options: RequestOptions) => Promise<{ statusCode: number; data: unknown }>
    = async () => ({ statusCode: 500, data: { detail: 'unconfigured' } })
  let privacyCalls = 0
  let refreshCalls = 0
  let releaseDelayed401!: (value: { statusCode: number; data: unknown }) => void
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = (options: RequestOptions) => handler(options)
  const api = await import('../src/services/api')
  await api.logout()
  handler = async (options) => {
    if (options.url.endsWith('/auth/login')) return { statusCode: 200, data: tokenResponse() }
    if (options.url.endsWith('/auth/refresh')) {
      refreshCalls += 1
      assert.deepEqual(options.data, { refresh_token: 'refresh-a' })
      return { statusCode: 200, data: tokenResponse({ access_token: 'access-b', refresh_token: 'refresh-b' }) }
    }
    if (options.url.endsWith('/privacy/status')) {
      privacyCalls += 1
      const auth = options.header?.Authorization
      if (privacyCalls === 1) return { statusCode: 401, data: { detail: 'AUTH_SESSION_EXPIRED' } }
      if (privacyCalls === 2) {
        return new Promise((resolve) => { releaseDelayed401 = resolve })
      }
      assert.equal(auth, 'Bearer access-b')
      return { statusCode: 200, data: { recording_paused: false } }
    }
    throw new Error(`unexpected request ${options.url}`)
  }
  await api.loginAccount('a@example.com', 'password-1234')
  const first = api.getPrivacyStatus()
  await Promise.resolve()
  const delayed = api.getPrivacyStatus()
  await first
  releaseDelayed401({ statusCode: 401, data: { detail: 'AUTH_SESSION_EXPIRED' } })
  await delayed
  assert.equal(refreshCalls, 1)
  assert.equal((storage.get('jiyi_auth_session') as any).refresh_token, 'refresh-b')
})

test('late login A cannot install over completed login B', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  let resolveA!: (value: { statusCode: number; data: unknown }) => void
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: RequestOptions) => {
    if (options.data && (options.data as any).email === 'a@example.com') {
      return new Promise((resolve) => { resolveA = resolve })
    }
    return { statusCode: 200, data: tokenResponse({ user_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' }) }
  }
  const api = await import('../src/services/api')
  await api.logout()
  const loginA = api.loginAccount('a@example.com', 'password-1234')
  await api.loginAccount('b@example.com', 'password-1234')
  resolveA({ statusCode: 200, data: tokenResponse() })
  await assert.rejects(loginA, /登录状态已变化/)
  assert.equal(api.currentAuthenticatedUserId(), 'dddddddd-dddd-4ddd-8ddd-dddddddddddd')
})

test('late verify-email A cannot replace login B', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  let resolveVerify!: (value: { statusCode: number; data: unknown }) => void
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: RequestOptions) => {
    if (options.url.endsWith('/auth/verify-email')) {
      return new Promise((resolve) => { resolveVerify = resolve })
    }
    return { statusCode: 200, data: tokenResponse({ user_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' }) }
  }
  const api = await import('../src/services/api')
  await api.logout()
  const verifyA = api.verifyEmail('verify-a')
  await api.loginAccount('b@example.com', 'password-1234')
  resolveVerify({
    statusCode: 200,
    data: { verified: true, already_verified: false, session: tokenResponse() },
  })
  await assert.rejects(verifyA, /登录状态已变化/)
  assert.equal(api.currentAuthenticatedUserId(), 'dddddddd-dddd-4ddd-8ddd-dddddddddddd')
})

test('delayed protected success is rejected after account switch', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  let resolvePrivacy!: (value: { statusCode: number; data: unknown }) => void
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: RequestOptions) => {
    if (options.url.endsWith('/auth/login')) {
      const userId = (options.data as any).email === 'b@example.com'
        ? 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        : USER_ID
      return { statusCode: 200, data: tokenResponse({ user_id: userId }) }
    }
    if (options.url.endsWith('/privacy/status')) return new Promise((resolve) => { resolvePrivacy = resolve })
    throw new Error(`unexpected request ${options.url}`)
  }
  const api = await import('../src/services/api')
  await api.logout()
  await api.loginAccount('a@example.com', 'password-1234')
  const oldRequest = api.getPrivacyStatus()
  await Promise.resolve()
  await api.loginAccount('b@example.com', 'password-1234')
  resolvePrivacy({ statusCode: 200, data: { recording_paused: true } })
  await assert.rejects(oldRequest, /登录状态已变化/)
})

test('delayed protected error is rejected after logout instead of reaching the old page', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  let resolvePrivacy!: (value: { statusCode: number; data: unknown }) => void
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: RequestOptions) => {
    if (options.url.endsWith('/auth/login')) return { statusCode: 200, data: tokenResponse() }
    if (options.url.endsWith('/privacy/status')) return new Promise((resolve) => { resolvePrivacy = resolve })
    if (options.url.endsWith('/auth/logout')) return { statusCode: 204, data: undefined }
    throw new Error(`unexpected request ${options.url}`)
  }
  const api = await import('../src/services/api')
  await api.logout()
  await api.loginAccount('a@example.com', 'password-1234')
  const oldRequest = api.getPrivacyStatus()
  await Promise.resolve()
  await api.logout()
  resolvePrivacy({ statusCode: 500, data: { detail: 'old account error' } })
  await assert.rejects(oldRequest, /登录状态已变化/)
})

test('logout reports remote revoke uncertainty and rejects cross-session refresh responses', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  let mode: 'logout-500' | 'refresh-cross-account' = 'logout-500'
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: RequestOptions) => {
    if (options.url.endsWith('/auth/login')) return { statusCode: 200, data: tokenResponse() }
    if (options.url.endsWith('/auth/logout')) return { statusCode: 500, data: { detail: 'server error' } }
    if (options.url.endsWith('/auth/refresh') && mode === 'refresh-cross-account') {
      return { statusCode: 200, data: tokenResponse({ user_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd', session_id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' }) }
    }
    if (options.url.endsWith('/privacy/status')) return { statusCode: 401, data: { detail: 'expired' } }
    throw new Error(`unexpected request ${options.url}`)
  }
  const api = await import('../src/services/api')
  await api.logout()
  await api.loginAccount('a@example.com', 'password-1234')
  const logoutResult = await api.logout()
  assert.equal((logoutResult as any).serverRevoked, false)
  await api.loginAccount('a@example.com', 'password-1234')
  mode = 'refresh-cross-account'
  await assert.rejects(api.getPrivacyStatus())
  assert.equal(api.isAuthenticated(), false)
})
