import Taro from '@tarojs/taro'
import type {
  ImageContentType,
  MediaRead,
  MediaUploadResponse,
  PhotoMemoryResponse,
  SignedTransfer,
} from './photoCapture'
import {
  assertPlaceDetailIdentity,
  buildPlaceDetailPath,
  buildPlacesPath,
  parsePlaceDetail,
  parsePlaceList,
  type PlaceDetailPage,
  type PlaceRead,
} from './placeDetail'
import type {
  AudioContentType,
  AudioMediaRead,
  AudioMediaUploadResponse,
  VoiceMemoryResponse,
} from './voiceCapture'
import {
  parseTodayFootprintResponse,
  type TodayFootprintResponse,
} from './todayFootprint'
import {
  parseFamilyCurrentLocation,
  parseFamilyInvite,
  parseFamilyMemories,
  parseFamilyPermissionGrant,
  parseFamilyPermissions,
  parseFamilyPhotoDownload,
  parseFamilyPhotos,
  parseFamilyResponse,
  parseFamilyTodayFootprint,
  type FamilyCurrentLocation,
  type FamilyMemory,
  type FamilyInvite,
  type FamilyPermissionGrant,
  type FamilyPhoto,
  type FamilyPhotoDownload,
  type FamilyResponse,
} from './family'
import {
  parseAnnualTrustedSummary,
  parseDailyTrustedSummary,
  parseMonthlyTrustedSummary,
  type AnnualTrustedSummary,
  type DailyTrustedSummary,
  type MonthlyTrustedSummary,
} from './memorySummaries'
import {
  buildApiHeaders,
  parseMemoryFeedbackRead,
  parseMemoryRead,
  type MemoryFeedbackPayload,
  type MemoryFeedbackRead,
  type MemoryRead,
  type SafeRequestOptions,
} from './memoryFeedback'
export type {
  TodayFootprintResponse,
  TodayFootprintVisit,
} from './todayFootprint'
export type {
  MemoryFeedbackAction,
  MemoryFeedbackOperation,
  MemoryFeedbackPayload,
  MemoryFeedbackRead,
  MemoryRead,
} from './memoryFeedback'

const TOKEN_KEY = 'jiyi_access_token'
const API_BASE_KEY = 'jiyi_api_base_url'

export type Evidence = {
  kind: string
  id: string
  source_type: string
  memory_source_id: string
  occurred_at: string
  excerpt: string
  confidence: number
  provenance?: 'ORIGINAL_SOURCE' | 'USER_EDIT'
  // [人工注释][S1-005][S1-007] 图片/语音 Evidence 的 media_id 只能消费服务端 MediaEvidenceLink 返回值；客户端不自行合成。
  media_id?: string | null
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
  id: string
  nickname: string
  email?: string | null
  timezone: string
  locale: string
}

export type PrivacyStatus = {
  recording_paused: boolean
  paused_since?: string | null
  paused_until?: string | null
}

export type UserObject = {
  id: string
  name: string
}

export function canEditApiBaseUrl(): boolean {
  return JIYI_ALLOW_API_BASE_EDIT
}

export function getApiBaseUrl(): string {
  // [人工注释][S1-FIX-007] 仅开发构建允许本地覆盖；生产产物始终使用 build-time endpoint。
  if (JIYI_ALLOW_API_BASE_EDIT) {
    return Taro.getStorageSync<string>(API_BASE_KEY) || JIYI_API_BASE_URL
  }
  return JIYI_API_BASE_URL
}

export function setApiBaseUrl(value: string): void {
  if (!JIYI_ALLOW_API_BASE_EDIT) {
    throw new Error('生产构建不允许修改 API 地址')
  }
  Taro.setStorageSync(API_BASE_KEY, value.replace(/\/$/, ''))
}

export function isAuthenticated(): boolean {
  return Boolean(Taro.getStorageSync<string>(TOKEN_KEY))
}

export function logout(): void {
  Taro.removeStorageSync(TOKEN_KEY)
}

// [人工注释][S1-019] 统一传输层显式包含 DELETE，单条记忆删除必须真正到达服务端；
// 非 2xx 始终抛出服务端错误，客户端不能把失败请求当作本地删除成功。
export class ApiRequestError extends Error {
  readonly statusCode: number
  readonly code: string

  constructor(statusCode: number, code: string, message: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.statusCode = statusCode
    this.code = code
  }
}

export function apiErrorCode(error: unknown): string | null {
  return error instanceof ApiRequestError ? error.code : null
}

async function request<T>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  data?: unknown,
  options: SafeRequestOptions = {},
): Promise<T> {
  const token = Taro.getStorageSync<string>(TOKEN_KEY)
  const response = await Taro.request<T>({
    url: `${getApiBaseUrl()}${path}`,
    method,
    data,
    header: buildApiHeaders(token, options),
  })

  if (response.statusCode < 200 || response.statusCode >= 300) {
    const payload = response.data as unknown as { detail?: string | Array<{ msg?: string }> }
    const detail = Array.isArray(payload?.detail)
      ? payload.detail.map((item) => item.msg).filter(Boolean).join('；')
      : payload?.detail
    const code = typeof payload?.detail === 'string'
      ? payload.detail
      : `HTTP_${response.statusCode}`
    throw new ApiRequestError(
      response.statusCode,
      code,
      detail || `HTTP_${response.statusCode}`,
    )
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

export async function getTodayFootprint(): Promise<TodayFootprintResponse> {
  // [人工注释][S2-012] 小程序与 Flutter 共用服务端“今天”边界；
  // 不上传设备日期/时区。200 response 也必须先过 runtime parser，
  // 禁止 TypeScript 类型断言把 malformed JSON 降级成真实足迹状态。
  const raw = await request<unknown>('GET', '/today/footprint')
  return parseTodayFootprintResponse(raw)
}

export async function generateDailyTrustedSummary(): Promise<DailyTrustedSummary> {
  // [人工注释][#103] AI generation is POST-only and only called by an explicit UI action.
  // The client supplies no user_id, timezone, or arbitrary UTC range.
  const raw = await request<unknown>('POST', '/memory/summaries/daily', {})
  return parseDailyTrustedSummary(raw)
}

export async function generateMonthlyTrustedSummary(
  targetMonth?: string,
): Promise<MonthlyTrustedSummary> {
  const raw = await request<unknown>(
    'POST',
    '/memory/summaries/monthly',
    targetMonth ? { target_month: targetMonth } : {},
  )
  return parseMonthlyTrustedSummary(raw)
}

export async function generateAnnualTrustedSummary(
  targetYear?: string,
): Promise<AnnualTrustedSummary> {
  const raw = await request<unknown>(
    'POST',
    '/memory/summaries/annual',
    targetYear ? { target_year: targetYear } : {},
  )
  return parseAnnualTrustedSummary(raw)
}

export async function getFamily(): Promise<FamilyResponse> {
  const raw = await request<unknown>('GET', '/family')
  return parseFamilyResponse(raw)
}

export async function createFamily(): Promise<FamilyResponse> {
  const raw = await request<unknown>('POST', '/family')
  return parseFamilyResponse(raw)
}

export async function createFamilyInvite(): Promise<FamilyInvite> {
  const raw = await request<unknown>('POST', '/family/invites')
  return parseFamilyInvite(raw)
}

export async function acceptFamilyInvite(token: string): Promise<FamilyResponse> {
  // [人工注释][S4-010] invite token 对客户端保持 opaque；仅移除用户粘贴时的首尾空白。
  const raw = await request<unknown>('POST', '/family/invites/accept', {
    token: token.trim(),
  })
  return parseFamilyResponse(raw)
}

export function revokeFamilyInvite(inviteId: string): Promise<void> {
  return request('DELETE', `/family/invites/${encodeURIComponent(inviteId)}`)
}

export function removeFamilyMember(userId: string): Promise<void> {
  return request('DELETE', `/family/members/${encodeURIComponent(userId)}`)
}

export async function getFamilyPermissions(): Promise<FamilyPermissionGrant[]> {
  const raw = await request<unknown>('GET', '/family/permissions')
  return parseFamilyPermissions(raw)
}

export async function replaceFamilyPermissions(
  granteeUserId: string,
  permissions: readonly string[],
): Promise<FamilyPermissionGrant> {
  // [人工注释][S4-010] 这是服务端权威 complete replacement，而不是 toggle endpoint。
  const raw = await request<unknown>(
    'PUT',
    `/family/permissions/${encodeURIComponent(granteeUserId)}`,
    { permissions: [...permissions] },
  )
  return parseFamilyPermissionGrant(raw)
}

export async function getFamilyCurrentLocation(
  resourceOwnerUserId: string,
): Promise<FamilyCurrentLocation> {
  const raw = await request<unknown>(
    'GET',
    `/family/members/${encodeURIComponent(resourceOwnerUserId)}/current-location`,
  )
  return parseFamilyCurrentLocation(raw, resourceOwnerUserId)
}

export async function getFamilyTodayFootprint(
  resourceOwnerUserId: string,
): Promise<TodayFootprintResponse> {
  const raw = await request<unknown>(
    'GET',
    `/family/members/${encodeURIComponent(resourceOwnerUserId)}/today/footprint`,
  )
  return parseFamilyTodayFootprint(raw)
}

export async function getFamilyMemories(
  resourceOwnerUserId: string,
): Promise<FamilyMemory[]> {
  // #107 is bounded list/read-only. No query/RAG/summary endpoint is involved.
  const raw = await request<unknown>(
    'GET',
    `/family/members/${encodeURIComponent(resourceOwnerUserId)}/memories?limit=50`,
  )
  return parseFamilyMemories(raw)
}

export async function getFamilyPhotos(
  resourceOwnerUserId: string,
): Promise<FamilyPhoto[]> {
  const raw = await request<unknown>(
    'GET',
    `/family/members/${encodeURIComponent(resourceOwnerUserId)}/photos`,
  )
  return parseFamilyPhotos(raw)
}

export async function getFamilyPhotoDownload(
  resourceOwnerUserId: string,
  mediaId: string,
): Promise<FamilyPhotoDownload> {
  const raw = await request<unknown>(
    'POST',
    `/family/members/${encodeURIComponent(resourceOwnerUserId)}/photos/${encodeURIComponent(mediaId)}/download`,
  )
  return parseFamilyPhotoDownload(raw, mediaId)
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

// [人工注释][S1-005] 图片链严格消费 PR #7 冻结协议。客户端只提交 opaque 幂等 ID、文件业务元数据，
// 从不提交 bucket/object key/endpoint/ETag，也不声明 READY/confidence/confirmed。
export function createImageMediaUpload(input: {
  clientUploadId: string
  contentType: ImageContentType
  sizeBytes: number
  originalFilename?: string | null
}): Promise<MediaUploadResponse> {
  return request('POST', '/media/uploads', {
    client_upload_id: input.clientUploadId,
    kind: 'IMAGE',
    content_type: input.contentType,
    size_bytes: input.sizeBytes,
    ...(input.originalFilename ? { original_filename: input.originalFilename } : {}),
  })
}

// [人工注释][S1-004][S1-007] 语音复用同一媒体上传协议；客户端只声明 RecorderManager
// 生成的 MP3 业务元数据，不提交 transcript/confidence/provider/confirmed。
export function createAudioMediaUpload(input: {
  clientUploadId: string
  contentType: AudioContentType
  sizeBytes: number
  originalFilename?: string | null
}): Promise<AudioMediaUploadResponse> {
  return request('POST', '/media/uploads', {
    client_upload_id: input.clientUploadId,
    kind: 'AUDIO',
    content_type: input.contentType,
    size_bytes: input.sizeBytes,
    ...(input.originalFilename ? { original_filename: input.originalFilename } : {}),
  })
}

// [人工注释][S1-004][S1-005] signed PUT 是对象存储临时能力票据，不携带业务 API Authorization；
// 必须原样使用服务端 method/headers 发送原始 ArrayBuffer，禁止用 multipart uploadFile 改写请求体。
export async function putSignedMediaObject(transfer: SignedTransfer, body: ArrayBuffer): Promise<void> {
  if (transfer.method.toUpperCase() !== 'PUT') {
    throw new Error('服务端返回了不支持的媒体上传方式')
  }
  const response = await Taro.request({
    url: transfer.url,
    method: 'PUT',
    data: body,
    header: transfer.headers,
  })
  if (response.statusCode < 200 || response.statusCode >= 300) {
    throw new Error(`媒体上传失败（HTTP_${response.statusCode}）`)
  }
}

export function completeImageMediaUpload(mediaId: string): Promise<MediaRead> {
  return request('POST', `/media/${mediaId}/complete`)
}

export function completeAudioMediaUpload(mediaId: string): Promise<AudioMediaRead> {
  return request('POST', `/media/${mediaId}/complete`)
}

export function createPhotoMemory(
  mediaId: string,
  input: { title?: string; content: string },
): Promise<PhotoMemoryResponse> {
  return request('POST', `/media/${mediaId}/memory`, {
    ...(input.title?.trim() ? { title: input.title.trim() } : {}),
    content: input.content.trim(),
  })
}

export function createVoiceMemory(
  mediaId: string,
  input: { title?: string; occurredAt?: string },
): Promise<VoiceMemoryResponse> {
  // [人工注释][S1-007] 小程序只可提交标题与录音发生时间；转写文字与可信度全部由服务端 ASR 派生。
  return request('POST', `/media/${mediaId}/voice-memory`, {
    ...(input.title?.trim() ? { title: input.title.trim() } : {}),
    ...(input.occurredAt ? { occurred_at: input.occurredAt } : {}),
  })
}

export async function getMemory(memoryId: string): Promise<MemoryRead> {
  const raw = await request<unknown>('GET', `/memories/${encodeURIComponent(memoryId)}`)
  return parseMemoryRead(raw, memoryId)
}

export async function submitMemoryFeedback(
  memoryId: string,
  payload: MemoryFeedbackPayload,
  idempotencyKey: string,
): Promise<MemoryFeedbackRead> {
  // [人工注释][S3-018] Idempotency-Key 由一次显式用户操作创建并由重试复用；
  // Authorization / Content-Type 仍由统一传输层控制，调用方不能覆盖。
  const raw = await request<unknown>(
    'POST',
    `/memories/${encodeURIComponent(memoryId)}/feedback`,
    payload,
    { idempotencyKey },
  )
  return parseMemoryFeedbackRead(raw, {
    memoryId,
    action: payload.action,
    memoryRevision: payload.expected_revision,
  })
}

export function deleteMemory(memoryId: string): Promise<void> {
  // [人工注释][S1-019] 其他产品面仍可使用通用直接删除；Query 反馈 UX 不调用此函数。
  return request('DELETE', `/memories/${memoryId}`)
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

export async function markObjectLocationStale(objectName: string): Promise<void> {
  // [人工注释][S1-011] 只从已有 Object 中精确定位，不通过 POST 创建不存在的空对象。
  const objects = await request<UserObject[]>('GET', '/objects')
  const normalized = objectName.trim().toLocaleLowerCase()
  const matched = objects.find((item) => item.name.trim().toLocaleLowerCase() === normalized)
  if (!matched) throw new Error('没有找到这个物品')
  await request('POST', `/objects/${matched.id}/location/stale`)
}

export async function listPlaces(limit = 25): Promise<PlaceRead[]> {
  const raw = await request<unknown>('GET', buildPlacesPath(limit))
  return parsePlaceList(raw)
}

export async function getPlaceDetail(
  placeId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<PlaceDetailPage> {
  const normalized = placeId.trim()
  const raw = await request<unknown>(
    'GET',
    buildPlaceDetailPath(normalized, options.limit ?? 20, options.cursor),
  )
  return assertPlaceDetailIdentity(parsePlaceDetail(raw), normalized)
}

export function getPrivacyStatus(): Promise<PrivacyStatus> {
  return request('GET', '/privacy/status')
}

export function pauseMemory(minutes: number): Promise<PrivacyStatus> {
  // [人工注释][S1-023] 小程序只选择暂停时长，历史 pause interval 由服务端持久化。
  return request('POST', '/privacy/pause', { duration_minutes: minutes })
}

export function pauseMemoryToday(): Promise<PrivacyStatus> {
  // [人工注释][S1-023] “今天”交给服务端按用户 IANA timezone 计算本地午夜。
  return request('POST', '/privacy/pause/today')
}

export function resumeMemory(): Promise<PrivacyStatus> {
  // [人工注释][S1-024] 手动恢复只结束当前 pause interval；历史暂停区间仍保留。
  return request('POST', '/privacy/resume')
}

export function queryMemory(question: string): Promise<MemoryQueryResult> {
  // [人工注释][S1-013] 查询只展示服务端 Evidence gate 返回值，客户端不得本地生成个人事实答案。
  return request('POST', '/memory/query', { question: question.trim() })
}
