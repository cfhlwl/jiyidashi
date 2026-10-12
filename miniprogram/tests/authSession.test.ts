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
