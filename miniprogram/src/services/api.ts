import Taro from '@tarojs/taro'
import {
  ElderProjectionStore,
  parseElderUserProfile,
  type ElderProjectionListener,
  type ElderUserProfile,
} from './elderMode'
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
  parseMemoryQueryResult,
  type MemoryQueryResult,
} from './memoryQuery'
import {
  parseEmergencyFamilyCurrentLocation,
  parseFamilyArrivalReminders,
  parseFamilyAudit,
  parseFamilyCurrentLocation,
  parseFamilyEmergencyShares,
  parseFamilyInvite,
  parseFamilyMemories,
  parseFamilyPermissionGrant,
  parseFamilyPermissions,
  parseFamilyPhotoDownload,
  parseFamilyPhotos,
  parseFamilyResponse,
  parseFamilyTodayFootprint,
  type FamilyArrivalReminder,
  type FamilyAuditEvent,
  type FamilyEmergencyLocationShare,
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
import {
  buildMemoryPickerPath,
  buildPersonInteractionsPath,
  buildPersonMemoryCreatePayload,
  buildPersonMemoryLinkPath,
  buildPersonMemoryTimelinePath,
  parseMemoryPickerRows,
  parsePersonInteractions,
  parsePersonMemoryLink,
  parsePersonMemoryTimeline,
  type PersonInteractionRow,
  type PersonMemoryLinkPatchPayload,
  type PersonMemoryLinkRead,
  type PersonMemoryRelationKind,
  type PersonMemoryTimelineRow,
} from './personMemories'
import {
  buildPersonRelationshipPath,
  buildPersonRelationshipsPath,
  parsePersonRelationshipList,
  parsePersonRelationshipRead,
  type PersonRelationshipCreatePayload,
  type PersonRelationshipPatchPayload,
  type PersonRelationshipProjection,
  type PersonRelationshipRead,
} from './personRelationships'
import {
  graphNeighborhoodPath,
  parseGraphNeighborhood,
  type GraphNeighborhood,
  type GraphNodeKind,
} from './unifiedGraph'
import {
  annualMemoirPhotosPath,
  lifeEventMemoriesPath,
  lifeEventMemoryPath,
  lifeEventPath,
  lifeEventsPath,
  lifeHistoryPath,
  lifeMemoirStagesPath,
  lifeStageEventPath,
  lifeStageEventsPath,
  lifeStagePath,
  lifeStagesPath,
  knownDurationPath,
  parseAnnualMemoir,
  parseAnnualMemoirPhotos,
  parseKnownDuration,
  parseLifeEvent,
  parseLifeEventEvidence,
  parseLifeEventEvidenceList,
  parseLifeEventList,
  parseLifeHistory,
  parseLifeMemoirChapter,
  parseLifeMemoirStageIndex,
  parseLifeStage,
  parseLifeStageEvidence,
  parseLifeStageEvidenceList,
  parseLifeStageList,
  parseLongTermReasoning,
  parseVerifiedMediaDownload,
  type AnnualMemoir,
  type AnnualMemoirPhotoPage,
  type LifeEventCreatePayload,
  type LifeEventMemoryEvidence,
  type LifeEventPatchPayload,
  type LifeEventRead,
  type LifeHistoryPage,
  type LifeMemoirChapter,
  type LifeMemoirStageIndexPage,
  type LifeStageCreatePayload,
  type LifeStageEventEvidence,
  type LifeStagePatchPayload,
  type LifeStageRead,
  type LongTermReasoningResult,
  type PersonKnownDuration,
  type VerifiedMediaDownload,
} from './advancedV2'
import {
  buildPeoplePath,
  parsePersonList,
  parsePersonRead,
  type PersonCreatePayload,
  type PersonPatchPayload,
  type PersonRead,
} from './people'
export type {
  TodayFootprintResponse,
  TodayFootprintVisit,
} from './todayFootprint'
export type {
  AnnualMemoir,
  AnnualMemoirPhotoPage,
  LifeEventMemoryEvidence,
  LifeEventRead,
  LifeHistoryPage,
  LifeMemoirChapter,
  LifeMemoirStageIndexPage,
  LifeStageEventEvidence,
  LifeStageRead,
  LongTermReasoningResult,
  PersonKnownDuration,
  VerifiedMediaDownload,
} from './advancedV2'
export type {
  MemoryFeedbackAction,
  MemoryFeedbackOperation,
  MemoryFeedbackPayload,
  MemoryFeedbackRead,
  MemoryRead,
} from './memoryFeedback'
export type {
  Evidence,
  MemoryQueryResult,
} from './memoryQuery'

const TOKEN_KEY = 'jiyi_access_token'
const API_BASE_KEY = 'jiyi_api_base_url'
const AUTH_OWNER_KEY = 'jiyi_authenticated_user_id'
const AUTH_SESSION_KEY = 'jiyi_auth_session'
const AUTH_DEVICE_ID_KEY = 'jiyi_auth_device_id'
const ACCESS_REFRESH_SKEW_MS = 30_000
const PHONE_E164_PATTERN = /^\+[1-9][0-9]{7,14}$/
let authSessionEpoch = 0
let authAttemptGeneration = 0
let refreshFlight: { sessionId: string; promise: Promise<MiniAuthSession> } | null = null
const elderProjection = new ElderProjectionStore()
type AuthSessionListener = (owner: string | null, epoch: number) => void
const authSessionListeners = new Set<AuthSessionListener>()

export type UserProfile = ElderUserProfile

export type PrivacyStatus = {
  recording_paused: boolean
  paused_since?: string | null
  paused_until?: string | null
}

export type UserObject = {
  id: string
  name: string
}

export type MiniAuthSession = {
  access_token: string
  refresh_token: string
  session_id: string
  token_type: 'bearer'
  user_id: string
  access_expires_at: string
  refresh_expires_at: string
  account_deletion_in_progress: boolean
}

export type AuthSessionSnapshot = {
  epoch: number
  owner: string
  sessionId: string
}

export type LogoutResult = {
  localCleared: true
  serverRevoked: boolean
  serverStatus: 'CONFIRMED' | 'UNCONFIRMED' | 'NOT_ATTEMPTED'
}

export type RegistrationResponse = {
  user_id: string
  verification_required: boolean
  verification_delivery_pending: boolean
}

export type EmailVerificationResponse = {
  verified: boolean
  already_verified: boolean
  session: MiniAuthSession | null
}

export type SmsOtpRequestResponse = {
  request_id: string
  expires_at: string
  cooldown_until: string
}

export type AuthCapabilityStatus = 'AVAILABLE' | 'PLANNED' | 'DISABLED' | 'UNAVAILABLE' | 'UNSUPPORTED'

export type AuthCapabilities = {
  email: AuthCapabilityStatus
  sms_otp: AuthCapabilityStatus
  phone_one_tap: AuthCapabilityStatus
  wechat: AuthCapabilityStatus
  wechat_miniprogram: AuthCapabilityStatus
}

type RequestOptions = SafeRequestOptions & Readonly<{
  anonymous?: boolean
  skipSessionRefresh?: boolean
  tokenOverride?: string
}>

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function invalidAuthResponse(): never {
  throw new Error('认证响应异常，请稍后重试')
}

function parseAuthDate(value: unknown): string {
  if (
    typeof value !== 'string'
    || !/T/.test(value)
    || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    || !Number.isFinite(Date.parse(value))
  ) return invalidAuthResponse()
  return value
}

export function parseMiniAuthSession(raw: unknown): MiniAuthSession {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return invalidAuthResponse()
  const value = raw as Record<string, unknown>
  if (
    typeof value.access_token !== 'string' || !value.access_token
    || typeof value.refresh_token !== 'string' || !value.refresh_token
    || typeof value.session_id !== 'string' || !UUID_PATTERN.test(value.session_id)
    || value.token_type !== 'bearer'
    || typeof value.user_id !== 'string' || !UUID_PATTERN.test(value.user_id)
    || typeof value.account_deletion_in_progress !== 'boolean'
  ) return invalidAuthResponse()
  return {
    access_token: value.access_token,
    refresh_token: value.refresh_token,
    session_id: value.session_id,
    token_type: 'bearer',
    user_id: value.user_id,
    access_expires_at: parseAuthDate(value.access_expires_at),
    refresh_expires_at: parseAuthDate(value.refresh_expires_at),
    account_deletion_in_progress: value.account_deletion_in_progress,
  }
}

function parseRegistrationResponse(raw: unknown): RegistrationResponse {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return invalidAuthResponse()
  const value = raw as Record<string, unknown>
  if (
    typeof value.user_id !== 'string' || !UUID_PATTERN.test(value.user_id)
    || typeof value.verification_required !== 'boolean'
    || typeof value.verification_delivery_pending !== 'boolean'
  ) return invalidAuthResponse()
  return {
    user_id: value.user_id,
    verification_required: value.verification_required,
    verification_delivery_pending: value.verification_delivery_pending,
  }
}

function parseEmailVerificationResponse(raw: unknown): EmailVerificationResponse {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return invalidAuthResponse()
  const value = raw as Record<string, unknown>
  if (
    typeof value.verified !== 'boolean'
    || typeof value.already_verified !== 'boolean'
    || !Object.prototype.hasOwnProperty.call(value, 'session')
  ) {
    return invalidAuthResponse()
  }
  if (value.session !== null) {
    return {
      verified: value.verified,
      already_verified: value.already_verified,
      session: parseMiniAuthSession(value.session),
    }
  }
  return {
    verified: value.verified,
    already_verified: value.already_verified,
    session: null,
  }
}

export function parseSmsOtpRequestResponse(raw: unknown): SmsOtpRequestResponse {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return invalidAuthResponse()
  const value = raw as Record<string, unknown>
  if (
    typeof value.request_id !== 'string' || !UUID_PATTERN.test(value.request_id)
    || typeof value.expires_at !== 'string' || !Number.isFinite(Date.parse(value.expires_at))
    || typeof value.cooldown_until !== 'string' || !Number.isFinite(Date.parse(value.cooldown_until))
  ) return invalidAuthResponse()
  return {
    request_id: value.request_id,
    expires_at: parseAuthDate(value.expires_at),
    cooldown_until: parseAuthDate(value.cooldown_until),
  }
}

function parseAuthCapabilities(raw: unknown): AuthCapabilities {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return invalidAuthResponse()
  const value = raw as Record<string, unknown>
  const statuses = new Set<AuthCapabilityStatus>(['AVAILABLE', 'PLANNED', 'DISABLED', 'UNAVAILABLE', 'UNSUPPORTED'])
  const fields = ['email', 'sms_otp', 'phone_one_tap', 'wechat', 'wechat_miniprogram'] as const
  for (const field of fields) {
    if (typeof value[field] !== 'string' || !statuses.has(value[field] as AuthCapabilityStatus)) return invalidAuthResponse()
  }
  return {
    email: value.email as AuthCapabilityStatus,
    sms_otp: value.sms_otp as AuthCapabilityStatus,
    phone_one_tap: value.phone_one_tap as AuthCapabilityStatus,
    wechat: value.wechat as AuthCapabilityStatus,
    wechat_miniprogram: value.wechat_miniprogram as AuthCapabilityStatus,
  }
}

function sameSession(left: MiniAuthSession | null, right: MiniAuthSession): boolean {
  return Boolean(left && left.session_id === right.session_id && left.refresh_token === right.refresh_token)
}

function sameSessionIdentity(left: MiniAuthSession | null, right: MiniAuthSession): boolean {
  return Boolean(left && left.session_id === right.session_id && left.user_id === right.user_id)
}

function sameSessionSnapshot(snapshot: AuthSessionSnapshot): boolean {
  const current = currentStoredSession()
  return Boolean(
    current
    && snapshot.epoch === authSessionEpoch
    && current.user_id === snapshot.owner
    && current.session_id === snapshot.sessionId,
  )
}

function currentStoredSession(): MiniAuthSession | null {
  const raw = Taro.getStorageSync<unknown>(AUTH_SESSION_KEY)
  if (raw === undefined || raw === null || raw === '') return null
  try {
    return parseMiniAuthSession(raw)
  } catch {
    return null
  }
}

function removeLegacyAuthKeys(): void {
  Taro.removeStorageSync(TOKEN_KEY)
  Taro.removeStorageSync(AUTH_OWNER_KEY)
}

function clearLocalSession(invalidate = true): void {
  if (invalidate) authSessionEpoch += 1
  Taro.removeStorageSync(AUTH_SESSION_KEY)
  removeLegacyAuthKeys()
  resetElderProjection()
  emitAuthSessionChanged()
}

function persistSession(session: MiniAuthSession): void {
  Taro.setStorageSync(AUTH_SESSION_KEY, session)
  removeLegacyAuthKeys()
}

function installSession(session: MiniAuthSession, invalidate = true): void {
  if (invalidate) authSessionEpoch += 1
  persistSession(session)
  resetElderProjection()
  emitAuthSessionChanged()
}

function accessNeedsRefresh(session: MiniAuthSession, now = Date.now()): boolean {
  return Date.parse(session.access_expires_at) <= now + ACCESS_REFRESH_SKEW_MS
}

function randomDeviceId(): string {
  const bytes = new Uint8Array(16)
  const cryptoApi = (globalThis as { crypto?: { getRandomValues?: (target: Uint8Array) => Uint8Array } }).crypto
  if (cryptoApi?.getRandomValues) cryptoApi.getRandomValues(bytes)
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function getAuthDeviceId(): string {
  const existing = Taro.getStorageSync<string>(AUTH_DEVICE_ID_KEY)
  if (typeof existing === 'string' && UUID_PATTERN.test(existing)) return existing
  const created = randomDeviceId()
  Taro.setStorageSync(AUTH_DEVICE_ID_KEY, created)
  return created
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
  return currentStoredSession() !== null
}

export function currentAuthenticatedUserId(): string | null {
  return currentAuthOwner()
}

export function currentAuthSessionEpoch(): number {
  return authSessionEpoch
}

function emitAuthSessionChanged(): void {
  const owner = currentAuthOwner()
  for (const listener of authSessionListeners) listener(owner, authSessionEpoch)
}

export function subscribeAuthSession(listener: AuthSessionListener): () => void {
  authSessionListeners.add(listener)
  listener(currentAuthOwner(), authSessionEpoch)
  return () => {
    authSessionListeners.delete(listener)
  }
}

export function logout(): Promise<LogoutResult> {
  return logoutAndRevoke()
}

/**
 * Fence a pre-login operation without changing an already installed session's
 * identity or epoch. Leaving an auth surface is not an account transition.
 * The SMS page uses this when the user changes authentication method or leaves
 * the flow; OTP values remain only in component memory and are never stored.
 */
export function cancelPendingAuthAttempt(): void {
  authAttemptGeneration += 1
}

export function isCanonicalPhoneInput(value: string): boolean {
  return PHONE_E164_PATTERN.test(value)
}

export function captureAuthSession(): AuthSessionSnapshot {
  const session = currentStoredSession()
  if (!session) throw new Error('请先登录')
  return { epoch: authSessionEpoch, owner: session.user_id, sessionId: session.session_id }
}

export function isAuthSessionCurrent(snapshot: AuthSessionSnapshot): boolean {
  return sameSessionSnapshot(snapshot)
}

export async function getAuthCapabilities(): Promise<AuthCapabilities> {
  return parseAuthCapabilities(await request<unknown>('GET', '/auth/capabilities', undefined, { anonymous: true }))
}

function resetElderProjection(): void {
  elderProjection.reset()
}

function publishElderProjection(profile: UserProfile, snapshot: AuthSessionSnapshot): void {
  if (!sameSessionSnapshot(snapshot)) throw new Error('登录状态已变化，请重试')
  if (profile.id !== snapshot.owner) throw new Error('个人资料账号不匹配')
  elderProjection.publish(profile.id, profile.elder_mode_enabled)
}

function currentAuthOwner(): string | null {
  return currentStoredSession()?.user_id || null
}

export function currentElderModeEnabled(): boolean {
  return elderProjection.current(currentAuthOwner())
}

export function subscribeElderMode(listener: ElderProjectionListener): () => void {
  return elderProjection.subscribe(currentAuthOwner, listener)
}

export function createCaptureSessionGuard(): () => void {
  const epoch = authSessionEpoch
  const owner = currentAuthOwner()
  if (!owner) throw new Error('请先登录')
  return () => {
    if (epoch !== authSessionEpoch || currentAuthOwner() !== owner) {
      throw new Error('登录状态已变化；本次记录已停止，请在当前账号重新操作')
    }
  }
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
  options: RequestOptions = {},
): Promise<T> {
  if (!options.anonymous && !options.skipSessionRefresh) await ensureFreshSession()
  const requestEpoch = authSessionEpoch
  const requestSession = options.anonymous ? null : currentStoredSession()
  if (!options.anonymous && !requestSession) throw new Error('请先登录')
  const token = options.tokenOverride !== undefined
    ? options.tokenOverride
    : options.anonymous ? '' : requestSession?.access_token || ''
  const assertCurrent = () => {
    if (!options.anonymous && (
      requestEpoch !== authSessionEpoch
      || !requestSession
      || !sameSessionIdentity(currentStoredSession(), requestSession)
    )) throw new Error('登录状态已变化，请重试')
  }

  let response: { statusCode: number; data: T }
  try {
    response = await rawRequest<T>(method, path, data, token, options)
  } catch (error) {
    // A transport rejection is still a protected response boundary. Re-check
    // the frozen owner before exposing the error to a consumer; otherwise an
    // A-only network error can be rendered by the page now showing account B.
    assertCurrent()
    throw error
  }

  if (response.statusCode < 200 || response.statusCode >= 300) {
    const payload = response.data as unknown as { detail?: string | Array<{ msg?: string }> }
    const detail = Array.isArray(payload?.detail)
      ? payload.detail.map((item) => item.msg).filter(Boolean).join('；')
      : payload?.detail
    const code = typeof payload?.detail === 'string'
      ? payload.detail
      : `HTTP_${response.statusCode}`
    const error = new ApiRequestError(
      response.statusCode,
      code,
      detail || `HTTP_${response.statusCode}`,
    )
    if (
      response.statusCode === 401
      && !options.anonymous
      && !options.skipSessionRefresh
      && requestSession
    ) {
      const current = currentStoredSession()
      if (
        requestEpoch !== authSessionEpoch
        || !sameSessionIdentity(current, requestSession)
      ) throw new Error('登录状态已变化，请重试')
      if (current?.refresh_token === requestSession.refresh_token) {
        await refreshAuthSession(requestSession)
      }
      const rotated = currentStoredSession()
      if (
        requestEpoch !== authSessionEpoch
        || !sameSessionIdentity(rotated, requestSession)
        || !rotated
      ) throw new Error('登录状态已变化，请重试')
      return request(method, path, data, {
        ...options,
        skipSessionRefresh: true,
        tokenOverride: rotated.access_token,
      })
    }
    assertCurrent()
    throw error
  }
  assertCurrent()
  return response.data
}

async function rawRequest<T>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  data: unknown,
  token: string,
  options: SafeRequestOptions = {},
): Promise<{ statusCode: number; data: T }> {
  return Taro.request<T>({
    url: `${getApiBaseUrl()}${path}`,
    method,
    data,
    header: buildApiHeaders(token, options),
  })
}

async function refreshAuthSession(expected: MiniAuthSession): Promise<MiniAuthSession> {
  const existingFlight = refreshFlight
  if (existingFlight?.sessionId === expected.session_id) return existingFlight.promise
  const expectedEpoch = authSessionEpoch
  if (
    !sameSession(currentStoredSession(), expected)
    || expectedEpoch !== authSessionEpoch
  ) throw new Error('登录状态已变化，请重试')
  let promise!: Promise<MiniAuthSession>
  promise = (async () => {
    try {
      const response = await rawRequest<unknown>(
        'POST',
        '/auth/refresh',
        { refresh_token: expected.refresh_token },
        '',
      )
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw new ApiRequestError(
          response.statusCode,
          `HTTP_${response.statusCode}`,
          `HTTP_${response.statusCode}`,
        )
      }
      const next = parseMiniAuthSession(response.data)
      if (
        expectedEpoch !== authSessionEpoch
        || !sameSession(currentStoredSession(), expected)
        || !sameSessionIdentity(next, expected)
      ) throw new Error('登录状态已变化，请重试')
      // Refresh is the only path allowed to replace a session without changing
      // the account epoch. The rotated token is immediately the only token kept.
      installSession(next, false)
      return next
    } catch (error) {
      if (expectedEpoch === authSessionEpoch && sameSession(currentStoredSession(), expected)) {
        clearLocalSession()
      }
      throw error
    } finally {
      if (refreshFlight?.promise === promise) refreshFlight = null
    }
  })()
  refreshFlight = { sessionId: expected.session_id, promise }
  return promise
}

async function ensureFreshSession(): Promise<void> {
  const session = currentStoredSession()
  if (session && accessNeedsRefresh(session)) await refreshAuthSession(session)
}

export async function restoreAuthSession(): Promise<boolean> {
  const raw = Taro.getStorageSync<unknown>(AUTH_SESSION_KEY)
  if (raw === undefined || raw === null || raw === '') return false
  let session: MiniAuthSession
  try {
    session = parseMiniAuthSession(raw)
  } catch {
    clearLocalSession()
    return false
  }
  removeLegacyAuthKeys()
  if (accessNeedsRefresh(session)) {
    try {
      await refreshAuthSession(session)
      return true
    } catch {
      return false
    }
  }
  return true
}

export async function resumeAuthSession(): Promise<boolean> {
  return restoreAuthSession()
}

async function logoutAndRevoke(): Promise<LogoutResult> {
  authAttemptGeneration += 1
  const previous = currentStoredSession()
  clearLocalSession()
  if (!previous) return { localCleared: true, serverRevoked: false, serverStatus: 'NOT_ATTEMPTED' }
  try {
    const response = await rawRequest('POST', '/auth/logout', undefined, previous.access_token)
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return { localCleared: true, serverRevoked: true, serverStatus: 'CONFIRMED' }
    }
    return { localCleared: true, serverRevoked: false, serverStatus: 'UNCONFIRMED' }
  } catch {
    // Local fencing is authoritative for this client. A failed server revoke
    // never restores the old account or session into the UI.
    return { localCleared: true, serverRevoked: false, serverStatus: 'UNCONFIRMED' }
  }
}

export async function registerAccount(input: {
  email: string
  password: string
  nickname: string
}): Promise<RegistrationResponse> {
  // [人工注释][S1-001] 小程序正式注册只提交凭证与公开资料，user_id 永远由服务端生成。
  const result = parseRegistrationResponse(await request<unknown>('POST', '/auth/register', {
    email: input.email.trim(),
    password: input.password,
    nickname: input.nickname.trim(),
    timezone: 'Asia/Shanghai',
    locale: 'zh-CN',
  }, { anonymous: true }))
  return result
}

export async function loginAccount(email: string, password: string): Promise<void> {
  const attempt = ++authAttemptGeneration
  clearLocalSession(false)
  // Account switching invalidates the prior owner before the network request,
  // so an in-flight response from account A cannot publish into account B.
  authSessionEpoch += 1
  const expectedEpoch = authSessionEpoch
  resetElderProjection()
  const result = parseMiniAuthSession(await request<unknown>('POST', '/auth/login', {
    email: email.trim(),
    password,
    device_id: getAuthDeviceId(),
    client_platform: 'miniprogram',
  }, { anonymous: true }))
  if (attempt !== authAttemptGeneration || expectedEpoch !== authSessionEpoch || currentStoredSession()) {
    throw new Error('登录状态已变化，请重试')
  }
  installSession(result, false)
}

export async function requestSmsOtp(phone: string): Promise<SmsOtpRequestResponse> {
  const normalizedPhone = phone.trim()
  if (!isCanonicalPhoneInput(normalizedPhone)) {
    throw new Error('请输入国际格式手机号（例如 +8613812345678）')
  }
  const result = await request<unknown>('POST', '/auth/phone/sms/request', {
    phone: normalizedPhone,
    device_id: getAuthDeviceId(),
    client_platform: 'miniprogram',
  }, { anonymous: true })
  return parseSmsOtpRequestResponse(result)
}

export async function verifySmsOtp(requestId: string, code: string): Promise<void> {
  const normalizedRequestId = requestId.trim()
  const normalizedCode = code.trim()
  if (!UUID_PATTERN.test(normalizedRequestId) || !/^\d{6}$/.test(normalizedCode)) {
    throw new Error('请输入有效的验证码')
  }
  const attempt = ++authAttemptGeneration
  clearLocalSession(false)
  authSessionEpoch += 1
  const expectedEpoch = authSessionEpoch
  const result = parseMiniAuthSession(await request<unknown>('POST', '/auth/phone/sms/verify', {
    request_id: normalizedRequestId,
    code: normalizedCode,
    device_id: getAuthDeviceId(),
    client_platform: 'miniprogram',
  }, { anonymous: true }))
  if (attempt !== authAttemptGeneration || expectedEpoch !== authSessionEpoch || currentStoredSession()) {
    throw new Error('登录状态已变化，请重试')
  }
  installSession(result, false)
}

export async function loginWechatMiniProgram(): Promise<void> {
  const attempt = ++authAttemptGeneration
  clearLocalSession(false)
  authSessionEpoch += 1
  const expectedEpoch = authSessionEpoch
  const loginResult = await Taro.login()
  const code = loginResult?.code
  if (typeof code !== 'string' || !code.trim()) throw new Error('微信登录凭证无效')
  const result = parseMiniAuthSession(await request<unknown>('POST', '/auth/wechat-mini/exchange', {
    code,
    request_id: randomDeviceId(),
    device_id: getAuthDeviceId(),
    client_platform: 'miniprogram',
  }, { anonymous: true }))
  if (attempt !== authAttemptGeneration || expectedEpoch !== authSessionEpoch || currentStoredSession()) {
    throw new Error('登录状态已变化，请重试')
  }
  installSession(result, false)
}

export async function verifyEmail(token: string): Promise<EmailVerificationResponse> {
  const attempt = ++authAttemptGeneration
  const expectedEpoch = authSessionEpoch
  const result = parseEmailVerificationResponse(await request<unknown>('POST', '/auth/verify-email', {
    token: token.trim(),
    device_id: getAuthDeviceId(),
    client_platform: 'miniprogram',
  }, { anonymous: true }))
  if (
    attempt !== authAttemptGeneration
    || expectedEpoch !== authSessionEpoch
    || currentStoredSession()
  ) throw new Error('登录状态已变化，请重试')
  if (result.session) installSession(result.session)
  return result
}

export async function resendVerification(email: string): Promise<void> {
  await request('POST', '/auth/resend-verification', { email: email.trim() }, { anonymous: true })
}

export async function getProfile(): Promise<UserProfile> {
  const snapshot = captureAuthSession()
  const raw = await request<unknown>('GET', '/user')
  const profile = parseElderUserProfile(raw)
  publishElderProjection(profile, snapshot)
  return profile
}

export async function getTodayFootprint(): Promise<TodayFootprintResponse> {
  // [人工注释][S2-012][S4-014] “今天”完全由服务端账号时区决定；
  // 同时冻结当前 auth epoch + owner，旧账号的 late response 不能进入新账号 UI。
  const epoch = authSessionEpoch
  const owner = currentAuthOwner()
  if (!owner) throw new Error('请先登录')
  const raw = await request<unknown>('GET', '/today/footprint')
  if (epoch !== authSessionEpoch || currentAuthOwner() !== owner) {
    throw new Error('登录状态已变化，请重试')
  }
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



export async function getGraphNeighborhood(
  kind: GraphNodeKind,
  entityId: string,
  limit = 50,
): Promise<GraphNeighborhood> {
  const raw = await request<unknown>(
    'GET',
    graphNeighborhoodPath(kind, entityId, limit),
  )
  return parseGraphNeighborhood(raw, kind, entityId, limit)
}

function createPeopleRequestSessionGuard(): () => void {
  const epoch = authSessionEpoch
  const owner = currentAuthOwner()
  if (!owner) throw new Error('请先登录')
  return () => {
    if (epoch !== authSessionEpoch || currentAuthOwner() !== owner) {
      throw new Error('登录状态已变化，请重试')
    }
  }
}

async function guardedPeopleRequest<T>(operation: () => Promise<T>): Promise<T> {
  const assertCurrentSession = createPeopleRequestSessionGuard()
  try {
    const result = await operation()
    assertCurrentSession()
    return result
  } catch (error) {
    // Stale old-owner success and stale old-owner error are both discarded.
    assertCurrentSession()
    throw error
  }
}

function createAdvancedV2RequestSessionGuard(): () => void {
  const epoch = authSessionEpoch
  const owner = currentAuthOwner()
  if (!owner) throw new Error('请先登录')
  return () => {
    if (epoch !== authSessionEpoch || currentAuthOwner() !== owner) {
      throw new Error('登录状态已变化，请重试')
    }
  }
}

async function guardedAdvancedV2Request<T>(operation: () => Promise<T>): Promise<T> {
  const assertCurrent = createAdvancedV2RequestSessionGuard()
  try {
    const result = await operation()
    assertCurrent()
    return result
  } catch (error) {
    assertCurrent()
    throw error
  }
}

export async function listLifeEvents(limit = 50): Promise<LifeEventRead[]> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', lifeEventsPath(limit))
    return parseLifeEventList(raw)
  })
}
export async function createLifeEvent(payload: LifeEventCreatePayload): Promise<LifeEventRead> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', '/life-events', payload)
    return parseLifeEvent(raw)
  })
}
export async function getLifeEvent(eventId: string): Promise<LifeEventRead> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', lifeEventPath(eventId))
    return parseLifeEvent(raw, eventId)
  })
}
export async function patchLifeEvent(eventId: string, payload: LifeEventPatchPayload): Promise<LifeEventRead> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('PATCH', lifeEventPath(eventId), payload)
    return parseLifeEvent(raw, eventId)
  })
}
export async function deleteLifeEvent(eventId: string): Promise<void> {
  return guardedAdvancedV2Request(async () => {
    await request<void>('DELETE', lifeEventPath(eventId))
  })
}
export async function listLifeEventMemories(eventId: string, limit = 50): Promise<LifeEventMemoryEvidence[]> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', lifeEventMemoriesPath(eventId, limit))
    return parseLifeEventEvidenceList(raw)
  })
}
export async function linkLifeEventMemory(eventId: string, memoryId: string): Promise<LifeEventMemoryEvidence> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', lifeEventMemoryPath(eventId, memoryId))
    return parseLifeEventEvidence(raw)
  })
}
export async function unlinkLifeEventMemory(eventId: string, memoryId: string): Promise<void> {
  return guardedAdvancedV2Request(async () => {
    await request<void>('DELETE', lifeEventMemoryPath(eventId, memoryId))
  })
}

export async function listLifeStages(limit = 50): Promise<LifeStageRead[]> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', lifeStagesPath(limit))
    return parseLifeStageList(raw)
  })
}
export async function createLifeStage(payload: LifeStageCreatePayload): Promise<LifeStageRead> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', '/life-stages', payload)
    return parseLifeStage(raw)
  })
}
export async function getLifeStage(stageId: string): Promise<LifeStageRead> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', lifeStagePath(stageId))
    return parseLifeStage(raw, stageId)
  })
}
export async function patchLifeStage(stageId: string, payload: LifeStagePatchPayload): Promise<LifeStageRead> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('PATCH', lifeStagePath(stageId), payload)
    return parseLifeStage(raw, stageId)
  })
}
export async function deleteLifeStage(stageId: string): Promise<void> {
  return guardedAdvancedV2Request(async () => {
    await request<void>('DELETE', lifeStagePath(stageId))
  })
}
export async function listLifeStageEvents(stageId: string, limit = 50): Promise<LifeStageEventEvidence[]> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', lifeStageEventsPath(stageId, limit))
    return parseLifeStageEvidenceList(raw)
  })
}
export async function linkLifeStageEvent(stageId: string, eventId: string): Promise<LifeStageEventEvidence> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', lifeStageEventPath(stageId, eventId))
    return parseLifeStageEvidence(raw)
  })
}
export async function unlinkLifeStageEvent(stageId: string, eventId: string): Promise<void> {
  return guardedAdvancedV2Request(async () => {
    await request<void>('DELETE', lifeStageEventPath(stageId, eventId))
  })
}

export async function getPersonKnownDuration(personId: string): Promise<PersonKnownDuration> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', knownDurationPath(personId))
    return parseKnownDuration(raw, personId)
  })
}
export async function reasonAboutLifeStage(stageId: string, question: string): Promise<LongTermReasoningResult> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', lifeStagePath(stageId) + '/reason', { question: question.trim() })
    return parseLongTermReasoning(raw, stageId)
  })
}
export async function getLifeHistory(
  startYear: number,
  endYear: number,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<LifeHistoryPage> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('GET', lifeHistoryPath(startYear, endYear, options.limit ?? 50, options.cursor))
    return parseLifeHistory(raw, { startYear, endYear })
  })
}
export async function generateAnnualMemoir(targetYear: string): Promise<AnnualMemoir> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', '/memoirs/annual', { target_year: targetYear })
    return parseAnnualMemoir(raw, targetYear)
  })
}
export async function getVerifiedMediaDownload(mediaId: string): Promise<VerifiedMediaDownload> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', '/media/' + encodeURIComponent(mediaId) + '/download')
    return parseVerifiedMediaDownload(raw, mediaId)
  })
}

export async function getAnnualMemoirPhotos(
  targetYear: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<AnnualMemoirPhotoPage> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>(
      'GET',
      annualMemoirPhotosPath(targetYear, options.limit ?? 24, options.cursor),
    )
    return parseAnnualMemoirPhotos(raw, targetYear)
  })
}
export async function getLifeMemoirStages(
  options: { limit?: number; cursor?: string | null } = {},
): Promise<LifeMemoirStageIndexPage> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>(
      'GET',
      lifeMemoirStagesPath(options.limit ?? 50, options.cursor),
    )
    return parseLifeMemoirStageIndex(raw)
  })
}
export async function generateLifeMemoirChapter(stageId: string): Promise<LifeMemoirChapter> {
  return guardedAdvancedV2Request(async () => {
    const raw = await request<unknown>('POST', '/memoirs/life/stages/' + encodeURIComponent(stageId))
    return parseLifeMemoirChapter(raw, stageId)
  })
}

export async function listPeople(limit = 100): Promise<PersonRead[]> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('GET', buildPeoplePath(limit))
    return parsePersonList(raw)
  })
}

export async function createPerson(payload: PersonCreatePayload): Promise<PersonRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('POST', '/people', payload)
    return parsePersonRead(raw)
  })
}

export async function getPerson(personId: string): Promise<PersonRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>(
      'GET',
      `/people/${encodeURIComponent(personId)}`,
    )
    return parsePersonRead(raw, personId)
  })
}

export async function patchPerson(
  personId: string,
  payload: PersonPatchPayload,
): Promise<PersonRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>(
      'PATCH',
      `/people/${encodeURIComponent(personId)}`,
      payload,
    )
    return parsePersonRead(raw, personId)
  })
}

export async function deletePerson(personId: string): Promise<void> {
  return guardedPeopleRequest(async () => {
    await request<void>('DELETE', `/people/${encodeURIComponent(personId)}`)
  })
}



export async function listPersonRelationships(
  personId: string,
  limit = 100,
): Promise<PersonRelationshipProjection[]> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('GET', buildPersonRelationshipsPath(personId, limit))
    return parsePersonRelationshipList(raw, personId, limit)
  })
}

export async function createPersonRelationship(
  payload: PersonRelationshipCreatePayload,
  currentPersonId: string,
  otherPersonId: string,
): Promise<PersonRelationshipRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('POST', '/people/relationships', payload)
    return parsePersonRelationshipRead(raw, undefined, currentPersonId, otherPersonId)
  })
}

export async function getPersonRelationship(
  relationshipId: string,
): Promise<PersonRelationshipRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('GET', buildPersonRelationshipPath(relationshipId))
    return parsePersonRelationshipRead(raw, relationshipId)
  })
}

export async function patchPersonRelationship(
  relationshipId: string,
  payload: PersonRelationshipPatchPayload,
  currentPersonId: string,
  otherPersonId: string,
): Promise<PersonRelationshipRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>(
      'PATCH',
      buildPersonRelationshipPath(relationshipId),
      payload,
    )
    return parsePersonRelationshipRead(
      raw,
      relationshipId,
      currentPersonId,
      otherPersonId,
    )
  })
}

export async function deletePersonRelationship(relationshipId: string): Promise<void> {
  return guardedPeopleRequest(async () => {
    await request<void>('DELETE', buildPersonRelationshipPath(relationshipId))
  })
}

export async function listPersonMemoryTimeline(
  personId: string,
  limit = 50,
): Promise<PersonMemoryTimelineRow[]> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('GET', buildPersonMemoryTimelinePath(personId, limit))
    return parsePersonMemoryTimeline(raw, personId, limit)
  })
}

export async function createPersonMemoryLink(
  personId: string,
  memoryId: string,
  relationKind: PersonMemoryRelationKind,
): Promise<PersonMemoryLinkRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>(
      'POST',
      buildPersonMemoryLinkPath(personId, memoryId),
      buildPersonMemoryCreatePayload(relationKind),
    )
    return parsePersonMemoryLink(raw, personId, memoryId)
  })
}

export async function patchPersonMemoryLink(
  personId: string,
  memoryId: string,
  payload: PersonMemoryLinkPatchPayload,
): Promise<PersonMemoryLinkRead> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>(
      'PATCH',
      buildPersonMemoryLinkPath(personId, memoryId),
      payload,
    )
    return parsePersonMemoryLink(raw, personId, memoryId)
  })
}

export async function deletePersonMemoryLink(
  personId: string,
  memoryId: string,
): Promise<void> {
  return guardedPeopleRequest(async () => {
    await request<void>('DELETE', buildPersonMemoryLinkPath(personId, memoryId))
  })
}

export async function listMemoryPickerRows(
  currentOwner: string,
  limit = 50,
): Promise<MemoryRead[]> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('GET', buildMemoryPickerPath(limit))
    return parseMemoryPickerRows(raw, currentOwner, limit)
  })
}

export async function listPersonInteractions(limit = 20): Promise<PersonInteractionRow[]> {
  return guardedPeopleRequest(async () => {
    const raw = await request<unknown>('GET', buildPersonInteractionsPath(limit))
    return parsePersonInteractions(raw, limit)
  })
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

export async function getFamilyArrivalReminders(
  currentUserId: string,
): Promise<FamilyArrivalReminder[]> {
  const raw = await request<unknown>('GET', '/family/arrival-reminders')
  return parseFamilyArrivalReminders(raw, currentUserId)
}

export async function createFamilyArrivalReminder(
  granteeUserId: string,
  destinationPlaceId: string,
  validityMinutes: 120 | 360 | 720,
  currentUserId: string,
): Promise<FamilyArrivalReminder> {
  const raw = await request<unknown>('POST', '/family/arrival-reminders', {
    grantee_user_id: granteeUserId,
    destination_place_id: destinationPlaceId,
    validity_minutes: validityMinutes,
  })
  const rows = parseFamilyArrivalReminders([raw], currentUserId)
  if (rows.length !== 1 || rows[0].direction !== 'OUTGOING') {
    throw new Error('家庭数据异常')
  }
  return rows[0]
}

export function cancelFamilyArrivalReminder(reminderId: string): Promise<void> {
  return request(
    'POST',
    `/family/arrival-reminders/${encodeURIComponent(reminderId)}/cancel`,
  )
}

export async function getFamilyAudit(): Promise<FamilyAuditEvent[]> {
  // [S4-015] Audit history is OWNER-only and explicit; Family tab refresh never calls this.
  const raw = await request<unknown>('GET', '/family/audit?limit=50')
  return parseFamilyAudit(raw)
}

export async function getFamilyEmergencyShares(
  currentUserId: string,
): Promise<FamilyEmergencyLocationShare[]> {
  const raw = await request<unknown>('GET', '/family/emergency-location-shares')
  return parseFamilyEmergencyShares(raw, currentUserId)
}

export async function createFamilyEmergencyShare(
  granteeUserId: string,
  durationMinutes: 30 | 60 | 180,
): Promise<FamilyEmergencyLocationShare> {
  const raw = await request<unknown>('POST', '/family/emergency-location-shares', {
    grantee_user_id: granteeUserId,
    duration_minutes: durationMinutes,
  })
  const rows = parseFamilyEmergencyShares([raw])
  if (rows.length !== 1 || rows[0].direction !== 'OUTGOING') {
    throw new Error('家庭数据异常')
  }
  return rows[0]
}

export function revokeFamilyEmergencyShare(shareId: string): Promise<void> {
  return request(
    'POST',
    `/family/emergency-location-shares/${encodeURIComponent(shareId)}/revoke`,
  )
}

export async function getFamilyEmergencyLocation(
  shareId: string,
  resourceOwnerUserId: string,
): Promise<FamilyCurrentLocation> {
  const raw = await request<unknown>(
    'GET',
    `/family/emergency-location-shares/${encodeURIComponent(shareId)}/location`,
  )
  return parseEmergencyFamilyCurrentLocation(raw, resourceOwnerUserId)
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

export async function updateProfile(input: {
  nickname?: string
  timezone?: string
  locale?: string
  elder_mode_enabled?: boolean
}): Promise<UserProfile> {
  const snapshot = captureAuthSession()
  const payload: Record<string, unknown> = {}
  if (input.nickname !== undefined) payload.nickname = input.nickname.trim()
  if (input.timezone !== undefined) payload.timezone = input.timezone.trim()
  if (input.locale !== undefined) payload.locale = input.locale.trim()
  if (input.elder_mode_enabled !== undefined) {
    payload.elder_mode_enabled = input.elder_mode_enabled
  }
  const raw = await request<unknown>('PATCH', '/user', payload)
  const profile = parseElderUserProfile(raw)
  publishElderProjection(profile, snapshot)
  return profile
}

export function updateElderMode(enabled: boolean): Promise<UserProfile> {
  return updateProfile({ elder_mode_enabled: enabled })
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

export async function queryMemory(question: string): Promise<MemoryQueryResult> {
  // [人工注释][S1-013][S4-013] 查询只展示服务端 Evidence gate 返回值；2xx malformed response 必须 fail closed。
  const raw = await request<unknown>('POST', '/memory/query', { question: question.trim() })
  return parseMemoryQueryResult(raw)
}
