import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const USER_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const SESSION_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const IDENTITY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'

function tokenResponse() {
  return {
    access_token: 'access-mini',
    refresh_token: 'refresh-mini',
    session_id: SESSION_ID,
    token_type: 'bearer',
    user_id: USER_ID,
    access_expires_at: '2099-01-01T00:00:00Z',
    refresh_expires_at: '2099-02-01T00:00:00Z',
    account_deletion_in_progress: false,
  }
}

test('identity list parser is strict and preserves only masked server hints', async () => {
  const api = await import('../src/services/api')
  const result = api.parseAuthIdentityList({
    identities: [{
      identity_id: IDENTITY_ID,
      provider: 'PHONE',
      subject_hint: '+86138****5678',
      verified_at: null,
      linked_at: '2026-10-01T00:00:00Z',
    }],
  })
  assert.deepEqual(result[0], {
    identity_id: IDENTITY_ID,
    provider: 'PHONE',
    subject_hint: '+86138****5678',
    verified_at: null,
    linked_at: '2026-10-01T00:00:00Z',
  })
  const futureProvider = api.parseAuthIdentityList({
    identities: [{
      identity_id: IDENTITY_ID,
      provider: 'FUTURE_PROVIDER',
      subject_hint: 'future***@example.test',
      verified_at: null,
      linked_at: '2026-10-01T00:00:00Z',
    }],
  })
  assert.equal(futureProvider[0].provider, 'FUTURE_PROVIDER')
  const pageSource = readFileSync('src/pages/account-security/index.tsx', 'utf8')
  assert.match(pageSource, /default: return '其他登录方式'/)
  assert.throws(() => api.parseAuthIdentityList({ identities: [{ provider: 'PHONE' }] }), /认证响应异常/)
})

test('identity GET uses the current session and mutation adapters are not called by provider-off page', async () => {
  ;(globalThis as Record<string, unknown>).JIYI_API_BASE_URL = 'https://api.example.test/v1'
  ;(globalThis as Record<string, unknown>).JIYI_ALLOW_API_BASE_EDIT = false
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>([['jiyi_auth_session', tokenResponse()]])
  const calls: any[] = []
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: any) => {
    calls.push(options)
    assert.equal(options.url, 'https://api.example.test/v1/auth/identities')
    assert.equal(options.method, 'GET')
    assert.equal(options.header.Authorization, 'Bearer access-mini')
    return { statusCode: 200, data: { identities: [] } }
  }
  const api = await import('../src/services/api')
  const identities = await api.getAuthIdentities()
  assert.deepEqual(identities, [])
  assert.equal(calls.length, 1)

  const source = readFileSync('src/pages/account-security/index.tsx', 'utf8')
  assert.match(source, /const manageDisabled = true/)
  assert.match(source, /getAuthIdentities\(\)/)
  assert.match(source, /disabled=\{manageDisabled\}/)
})

test('account-security controller clears A before B and ignores a late A response', async () => {
  ;(globalThis as Record<string, unknown>).JIYI_API_BASE_URL = 'https://api.example.test/v1'
  ;(globalThis as Record<string, unknown>).JIYI_ALLOW_API_BASE_EDIT = false
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const sessionA = { ...tokenResponse(), user_id: USER_ID }
  const sessionB = { ...tokenResponse(), user_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee', session_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff' }
  const storage = new Map<string, unknown>([['jiyi_auth_session', sessionA]])
  let identityCalls = 0
  let releaseA: ((value: unknown) => void) | null = null
  const pendingA = new Promise<unknown>((resolve) => { releaseA = resolve })
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: any) => {
    if (options.url.endsWith('/auth/logout')) return { statusCode: 200, data: {} }
    if (options.url.endsWith('/auth/login')) return { statusCode: 200, data: sessionB }
    assert.equal(options.url, 'https://api.example.test/v1/auth/identities')
    identityCalls += 1
    if (identityCalls === 1) return pendingA
    return {
      statusCode: 200,
      data: {
        identities: [{
          identity_id: IDENTITY_ID,
          provider: 'EMAIL_PASSWORD',
          subject_hint: 'b***@example.test',
          verified_at: '2026-10-01T00:00:00Z',
          linked_at: '2026-10-01T00:00:00Z',
        }],
      },
    }
  }
  const api = await import('../src/services/api')
  const page = await import('../src/pages/account-security/index')
  const controller = page.createAccountSecurityController(api.getAuthIdentities)
  controller.start()
  const states: Array<import('../src/pages/account-security/index').AccountSecurityViewState> = []
  const unsubscribe = controller.subscribe((state) => states.push(state))

  await api.logout()
  await api.loginAccount('b@example.test', 'password-123456')
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
  assert.equal(controller.getState().identities?.[0]?.subject_hint, 'b***@example.test')
  assert.equal(controller.getState().error, '')
  assert.equal(states.some((state) => state.identities === null), true)

  releaseA?.({
    statusCode: 200,
    data: { identities: [{
      identity_id: IDENTITY_ID,
      provider: 'EMAIL_PASSWORD',
      subject_hint: 'a***@example.test',
      verified_at: '2026-10-01T00:00:00Z',
      linked_at: '2026-10-01T00:00:00Z',
    }] },
  })
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
  assert.equal(controller.getState().identities?.[0]?.subject_hint, 'b***@example.test')
  unsubscribe()
  controller.dispose()
})

test('identity mutation adapters keep opaque proof transient and parse provider results', async () => {
  const Taro = (await import('@tarojs/taro')).default as unknown as Record<string, any>
  const storage = new Map<string, unknown>([['jiyi_auth_session', tokenResponse()]])
  let mutationCount = 0
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  Taro.request = async (options: any) => {
    mutationCount += 1
    assert.equal(options.header.Authorization, 'Bearer access-mini')
    assert.equal(options.data.reauth_credential, 'opaque-reauth')
    assert.equal(options.data.credential, undefined, 'unlink must not receive a second credential')
    return {
      statusCode: 200,
      data: {
        request_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
        operation: 'UNLINK',
        identity: null,
      },
    }
  }
  const api = await import('../src/services/api')
  const result = await api.unlinkAuthIdentity({
    identity_id: IDENTITY_ID,
    request_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    reauth_credential: 'opaque-reauth',
  })
  assert.equal(result.operation, 'UNLINK')
  assert.equal(mutationCount, 1)
  assert.equal(storage.has('opaque-reauth'), false)
})

test('profile exposes a separate account-security route without provider fake success', () => {
  const source = readFileSync('src/pages/profile/index.tsx', 'utf8')
  assert.match(source, /pages\/account-security\/index/)
})

test('account-security visual capture mounts the production page with masked identities', () => {
  const capture = readFileSync('scripts/capture-visual-review.mjs', 'utf8')
  assert.match(capture, /#\/pages\/account-security\/index/)
  assert.match(capture, /jiyi_auth_session/)
  assert.match(capture, /g\*\*\*@example\.test/)
  assert.match(capture, /route\.request\(\)\.method\(\) !== 'GET'/)
  assert.match(capture, /account-security-empty/)
})
