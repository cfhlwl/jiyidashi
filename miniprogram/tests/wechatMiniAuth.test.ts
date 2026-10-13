import assert from 'node:assert/strict'
import test from 'node:test'

const USER_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const SESSION_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

function tokenResponse(overrides: Record<string, unknown> = {}) {
  return {
    access_token: 'access-mini',
    refresh_token: 'refresh-mini',
    session_id: SESSION_ID,
    token_type: 'bearer',
    user_id: USER_ID,
    access_expires_at: '2099-01-01T00:00:00Z',
    refresh_expires_at: '2099-02-01T00:00:00Z',
    account_deletion_in_progress: false,
    ...overrides,
  }
}

test('AUTH-002 explicit Mini Program login uses opaque code and installs full Session', async () => {
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
  const calls: any[] = []
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.login = async () => ({ code: 'wx-one-shot-code' })
  Taro.request = async (options: any) => {
    calls.push(options)
    if (options.url.endsWith('/auth/wechat-mini/exchange')) {
      assert.equal(options.data.code, 'wx-one-shot-code')
      assert.equal(options.data.client_platform, 'miniprogram')
      assert.equal('secret' in options.data, false)
      assert.equal('session_key' in options.data, false)
      return { statusCode: 200, data: tokenResponse() }
    }
    if (options.url.endsWith('/auth/logout')) return { statusCode: 204, data: undefined }
    throw new Error(`unexpected request ${options.url}`)
  }
  const api = await import('../src/services/api')
  await api.logout()
  await api.loginWechatMiniProgram()
  assert.equal(api.currentAuthenticatedUserId(), USER_ID)
  assert.equal(calls.filter((call) => call.url.endsWith('/auth/wechat-mini/exchange')).length, 1)
  assert.equal(storage.has('jiyi_access_token'), false)
})

test('AUTH-002 stale Mini Program success after logout cannot install Session', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>()
  let resolveExchange!: (value: unknown) => void
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.login = async () => ({ code: 'wx-late-code' })
  Taro.request = (options: any) => {
    if (options.url.endsWith('/auth/wechat-mini/exchange')) {
      return new Promise((resolve) => { resolveExchange = resolve })
    }
    if (options.url.endsWith('/auth/logout')) return Promise.resolve({ statusCode: 204, data: undefined })
    return Promise.reject(new Error(`unexpected request ${options.url}`))
  }
  const api = await import('../src/services/api')
  await api.logout()
  const pending = api.loginWechatMiniProgram()
  await Promise.resolve()
  await api.logout()
  resolveExchange({ statusCode: 200, data: tokenResponse() })
  await assert.rejects(pending, /登录状态已变化/)
  assert.equal(api.isAuthenticated(), false)
})

test('AUTH-002 capability parser keeps Mini Program provider separate and fail-closed', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  Taro.request = async (options: any) => {
    assert.equal(options.url.endsWith('/auth/capabilities'), true)
    return {
      statusCode: 200,
      data: {
        email: 'AVAILABLE',
        sms_otp: 'UNAVAILABLE',
        phone_one_tap: 'UNAVAILABLE',
        wechat: 'DISABLED',
        wechat_miniprogram: 'DISABLED',
      },
    }
  }
  const api = await import('../src/services/api')
  const capabilities = await api.getAuthCapabilities()
  assert.equal(capabilities.wechat, 'DISABLED')
  assert.equal(capabilities.wechat_miniprogram, 'DISABLED')
})
