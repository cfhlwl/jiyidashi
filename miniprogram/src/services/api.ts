import Taro from '@tarojs/taro'

const TOKEN_KEY = 'jiyi_access_token'
const API_BASE_KEY = 'jiyi_api_base_url'
const DEFAULT_API_BASE = 'http://127.0.0.1:8000/v1'

export type Evidence = {
  kind: string
  id: string
  occurred_at: string
  excerpt: string
  confidence: number
}

export type MemoryQueryResult = {
  answer: string | null
  can_answer: boolean
  certainty: string
  reason?: string | null
  intent: string
  evidence: Evidence[]
  memory_ids: string[]
}

export type UserProfile = {
  nickname: string
  email?: string | null
  timezone: string
  locale: string
}

export function getApiBaseUrl(): string {
  return Taro.getStorageSync<string>(API_BASE_KEY) || DEFAULT_API_BASE
}

export function setApiBaseUrl(value: string): void {
  Taro.setStorageSync(API_BASE_KEY, value.replace(/\/$/, ''))
}

export function isAuthenticated(): boolean {
  return Boolean(Taro.getStorageSync<string>(TOKEN_KEY))
}

export function logout(): void {
  Taro.removeStorageSync(TOKEN_KEY)
}

async function request<T>(method: 'GET' | 'POST' | 'PATCH', path: string, data?: unknown): Promise<T> {
  const token = Taro.getStorageSync<string>(TOKEN_KEY)
  const response = await Taro.request<T>({
    url: `${getApiBaseUrl()}${path}`,
    method,
    data,
    header: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })

  if (response.statusCode < 200 || response.statusCode >= 300) {
    const payload = response.data as unknown as { detail?: string }
    throw new Error(payload?.detail || `HTTP_${response.statusCode}`)
  }
  return response.data
}

export async function registerAccount(input: {
  email: string
  password: string
  nickname: string
}): Promise<void> {
  // [人工注释][S1-001] 小程序正式注册只提交凭证与公开资料，user_id 永远由服务端生成。
  const result = await request<{ access_token: string }>('POST', '/auth/register', {
    email: input.email.trim(),
    password: input.password,
    nickname: input.nickname.trim(),
    timezone: 'Asia/Shanghai',
    locale: 'zh-CN',
  })
  Taro.setStorageSync(TOKEN_KEY, result.access_token)
}

export async function loginAccount(email: string, password: string): Promise<void> {
  const result = await request<{ access_token: string }>('POST', '/auth/login', {
    email: email.trim(),
    password,
  })
  Taro.setStorageSync(TOKEN_KEY, result.access_token)
}

export function getProfile(): Promise<UserProfile> {
  return request('GET', '/user')
}

export function updateProfile(input: {
  nickname: string
  timezone: string
  locale?: string
}): Promise<UserProfile> {
  // [人工注释][S1-002] 小程序只提交 IANA timezone 名称，服务端再次校验后才更新用户自然日边界。
  return request('PATCH', '/user', {
    nickname: input.nickname.trim(),
    timezone: input.timezone.trim(),
    locale: (input.locale || 'zh-CN').trim(),
  })
}

export function createTextMemory(content: string, title?: string): Promise<{ id: string }> {
  // [人工注释][S1-003] capture_source 固定为 USER_TEXT，客户端不拥有 confidence/confirmed 权限。
  return request('POST', '/memories', {
    memory_type: 'NOTE',
    ...(title?.trim() ? { title: title.trim() } : {}),
    content: content.trim(),
    capture_source: 'USER_TEXT',
  })
}

export async function rememberObjectLocation(objectName: string, locationText: string): Promise<void> {
  // [人工注释][S1-009] 小程序与 Flutter 共用 Object → ObjectLocation 的服务端可信链。
  const object = await request<{ id: string }>('POST', '/objects', {
    name: objectName.trim(),
  })
  await request('POST', `/objects/${object.id}/locations`, {
    location_text: locationText.trim(),
    capture_source: 'USER_TEXT',
  })
}

export function queryMemory(question: string): Promise<MemoryQueryResult> {
  // [人工注释][S1-013] 查询只展示服务端 Evidence gate 返回值，客户端不得本地生成个人事实答案。
  return request('POST', '/memory/query', { question: question.trim() })
}
