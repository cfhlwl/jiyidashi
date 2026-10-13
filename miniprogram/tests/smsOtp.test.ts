import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

type RequestOptions = { url: string; method: string; data?: unknown; header?: Record<string, string> }

const USER_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const USER_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const REQUEST_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'

function tokenResponse(userId: string) {
  return {
    access_token: `access-${userId}`,
    refresh_token: `refresh-${userId}-abcdefghijklmnopqrstuvwxyz`,
    session_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    token_type: 'bearer',
    user_id: userId,
    access_expires_at: '2099-01-01T00:00:00Z',
    refresh_expires_at: '2099-02-01T00:00:00Z',
    account_deletion_in_progress: false,
  }
}

async function setup() {
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
  Taro.getStorageSync = (key: string) => storage.get(key)
  Taro.setStorageSync = (key: string, value: unknown) => { storage.set(key, value) }
  Taro.removeStorageSync = (key: string) => { storage.delete(key) }
  return { Taro, storage, calls }
}

test('SMS request uses server capability contract and keeps OTP transient', async () => {
  const { Taro, storage, calls } = await setup()
  Taro.request = async (options: RequestOptions) => {
    calls.push(options)
    assert.equal(options.url, 'https://api.example.test/v1/auth/phone/sms/request')
    assert.deepEqual(options.data, {
      phone: '+8613812345678',
      device_id: storage.get('jiyi_auth_device_id'),
      client_platform: 'miniprogram',
    })
    return {
      statusCode: 200,
      data: {
        request_id: REQUEST_ID,
        expires_at: '2099-01-01T00:05:00Z',
        cooldown_until: '2099-01-01T00:01:00Z',
      },
    }
  }
  const api = await import('../src/services/api')
  await api.logout()
  const response = await api.requestSmsOtp('+8613812345678')
  assert.equal(response.request_id, REQUEST_ID)
  assert.equal(storage.has('jiyi_auth_session'), false)
  assert.equal(storage.has('sms_otp'), false)
  assert.equal(calls.length, 1)
})

test('late SMS verify cannot install after a newer login attempt', async () => {
  const { Taro, storage } = await setup()
  let resolveSms!: (value: { statusCode: number; data: unknown }) => void
  Taro.request = (options: RequestOptions) => {
    if (options.url.endsWith('/auth/phone/sms/verify')) {
      assert.deepEqual(options.data, {
        request_id: REQUEST_ID,
        code: '123456',
        device_id: storage.get('jiyi_auth_device_id'),
        client_platform: 'miniprogram',
      })
      return new Promise((resolve) => { resolveSms = resolve })
    }
    if (options.url.endsWith('/auth/login')) {
      return Promise.resolve({ statusCode: 200, data: tokenResponse(USER_B) })
    }
    if (options.url.endsWith('/auth/logout')) return Promise.resolve({ statusCode: 204, data: undefined })
    throw new Error(`unexpected request ${options.url}`)
  }
  const api = await import('../src/services/api')
  await api.logout()
  const smsVerify = api.verifySmsOtp(REQUEST_ID, '123456')
  await api.loginAccount('b@example.com', 'password-1234')
  resolveSms({ statusCode: 200, data: tokenResponse(USER_A) })
  await assert.rejects(smsVerify, /登录状态已变化/)
  assert.equal(api.currentAuthenticatedUserId(), USER_B)
  assert.equal((storage.get('jiyi_auth_session') as { user_id: string }).user_id, USER_B)
})

test('SMS request response parser rejects incomplete provider-shaped data', async () => {
  const api = await import('../src/services/api')
  assert.throws(
    () => api.parseSmsOtpRequestResponse({ request_id: REQUEST_ID, expires_at: '2099-01-01T00:05:00Z' }),
    /认证响应异常/,
  )
})

test('Mini SMS entry is capability-gated and uses transient component state', () => {
  const source = readFileSync('src/pages/profile/index.tsx', 'utf8')
  assert.match(source, /smsOtpAvailable && !smsMode/)
  assert.match(source, /requestSmsOtp\(smsPhone\)/)
  assert.match(source, /verifySmsOtp\(smsRequestId, smsCode\)/)
  assert.match(source, /setSmsCode\(''\)/)
  assert.doesNotMatch(source, /setStorageSync\([^\n]*sms/i)
})
