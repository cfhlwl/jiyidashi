import {
  parseTodayFootprintResponse,
  type TodayFootprintResponse,
} from './todayFootprint'

export type FamilyRole = 'OWNER' | 'MEMBER'

export const FAMILY_PERMISSION = {
  VIEW_CURRENT_LOCATION: 'VIEW_CURRENT_LOCATION',
  VIEW_FOOTPRINT: 'VIEW_FOOTPRINT',
  VIEW_MEMORY: 'VIEW_MEMORY',
  VIEW_PHOTOS: 'VIEW_PHOTOS',
} as const

export type FamilyPermissionCode = typeof FAMILY_PERMISSION[keyof typeof FAMILY_PERMISSION]
export type InteractiveFamilyPermissionCode =
  | typeof FAMILY_PERMISSION.VIEW_CURRENT_LOCATION
  | typeof FAMILY_PERMISSION.VIEW_FOOTPRINT
  | typeof FAMILY_PERMISSION.VIEW_MEMORY
  | typeof FAMILY_PERMISSION.VIEW_PHOTOS

export const INTERACTIVE_FAMILY_PERMISSIONS: readonly InteractiveFamilyPermissionCode[] = [
  FAMILY_PERMISSION.VIEW_CURRENT_LOCATION,
  FAMILY_PERMISSION.VIEW_FOOTPRINT,
  FAMILY_PERMISSION.VIEW_MEMORY,
  FAMILY_PERMISSION.VIEW_PHOTOS,
]

export type FamilyMember = {
  user_id: string
  role: FamilyRole
  created_at: string
}

export type FamilyResponse = {
  family_id: string
  current_user_role: FamilyRole
  members: FamilyMember[]
}

export type FamilyInvite = {
  invite_id: string
  token: string
  expires_at: string
}

// Permission codes intentionally remain strings after validation. The server currently
// exposes four known codes, but replacement must preserve a future code that a newer
// server may return instead of silently deleting it during a visible toggle.
export type FamilyPermissionGrant = {
  grantee_user_id: string
  permissions: string[]
}

export type FamilyCurrentLocation = {
  latitude: number
  longitude: number
  accuracy: number | null
  recorded_at: string
  fresh_until: string
}

export type FamilyMemory = {
  memory_id: string
  memory_type: string
  title: string | null
  content: string
  occurred_at: string
  source_type: string
  is_confirmed: boolean
  edit_revision: number
  created_at: string
}

export type FamilyPhoto = {
  media_id: string
  content_type: string
  size_bytes: number
  created_at: string
  completed_at: string | null
}

export type FamilyPhotoSignedTransfer = {
  method: 'GET'
  url: string
  headers: Record<string, string>
  expires_at: string
}

export type FamilyPhotoDownload = {
  media_id: string
  download: FamilyPhotoSignedTransfer
}

export type FamilyAuditResourceType = 'CURRENT_LOCATION' | 'TODAY_FOOTPRINT' | 'MEMORY' | 'PHOTO'
export type FamilyAuditAuthorityType = 'EXACT_GRANT' | 'EMERGENCY_SHARE'
export type FamilyAuditAction =
  | 'READ_CURRENT_LOCATION'
  | 'READ_TODAY_FOOTPRINT'
  | 'READ_MEMORY'
  | 'LIST_PHOTOS'
  | 'DOWNLOAD_PHOTO'
  | 'READ_EMERGENCY_LOCATION'
export type FamilyAuditResult = 'ALLOWED' | 'DENIED' | 'UNAVAILABLE'

export type FamilyAuditEvent = {
  event_id: string
  actor_user_id: string
  resource_owner_user_id: string
  authority_type: FamilyAuditAuthorityType
  permission_code: FamilyPermissionCode | null
  resource_type: FamilyAuditResourceType
  action: FamilyAuditAction
  result: FamilyAuditResult
  created_at: string
}

export type FamilyEmergencyShareDirection = 'OUTGOING' | 'INCOMING'

export type FamilyArrivalReminderStatus = 'ACTIVE' | 'ARRIVED' | 'CANCELLED' | 'EXPIRED'
export type FamilyArrivalReminderDirection = 'OUTGOING' | 'INCOMING'

export type FamilyArrivalReminder = {
  reminder_id: string
  resource_owner_user_id: string
  grantee_user_id: string
  destination_place_id: string
  destination_display_name: string
  status: FamilyArrivalReminderStatus
  created_at: string
  expires_at: string
  arrived_at: string | null
  direction: FamilyArrivalReminderDirection
}

export type FamilyEmergencyLocationShare = {
  share_id: string
  resource_owner_user_id: string
  grantee_user_id: string
  expires_at: string
  created_at: string
  direction: FamilyEmergencyShareDirection
}

export type FamilyPagePhase =
  | 'signed-out'
  | 'loading'
  | 'no-family'
  | 'family-ready'
  | 'error'

export type FamilyMemberActions = {
  isSelf: boolean
  showPermissionControls: boolean
  showSensitiveReads: boolean
  showOwnerRemove: boolean
  showMemberLeave: boolean
}

type JsonRecord = Record<string, unknown>

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ISO_DATE_TIME =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/

function invalidFamilyResponse(): never {
  throw new Error('家庭数据异常')
}

function asRecord(value: unknown): JsonRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return invalidFamilyResponse()
  }
  return value as JsonRecord
}

function nonEmptyString(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return invalidFamilyResponse()
  return value
}

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value)
}

function uuid(value: unknown): string {
  const text = nonEmptyString(value)
  if (!isUuid(text)) return invalidFamilyResponse()
  return text
}

function role(value: unknown): FamilyRole {
  if (value !== 'OWNER' && value !== 'MEMBER') return invalidFamilyResponse()
  return value
}

function validDateOnly(value: string): void {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) invalidFamilyResponse()
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(Date.UTC(year, month - 1, day))
  if (
    !Number.isFinite(date.getTime())
    || date.getUTCFullYear() !== year
    || date.getUTCMonth() !== month - 1
    || date.getUTCDate() !== day
  ) {
    invalidFamilyResponse()
  }
}

function isoDateTime(value: unknown): string {
  const text = nonEmptyString(value)
  if (!ISO_DATE_TIME.test(text)) return invalidFamilyResponse()
  validDateOnly(text.slice(0, 10))
  if (!Number.isFinite(Date.parse(text))) return invalidFamilyResponse()
  return text
}

function finiteNumber(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return invalidFamilyResponse()
  }
  return value
}

function stringValue(value: unknown, maxLength?: number): string {
  if (typeof value !== 'string') return invalidFamilyResponse()
  if (maxLength !== undefined && value.length > maxLength) return invalidFamilyResponse()
  return value
}

function nullableString(value: unknown, maxLength: number): string | null {
  if (value === null) return null
  return stringValue(value, maxLength)
}

function booleanValue(value: unknown): boolean {
  if (typeof value !== 'boolean') return invalidFamilyResponse()
  return value
}

function nonNegativeInteger(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    return invalidFamilyResponse()
  }
  return value
}

function nullableAccuracy(value: unknown): number | null {
  if (value === null) return null
  const result = finiteNumber(value)
  if (result < 0) return invalidFamilyResponse()
  return result
}

function permissionCode(value: unknown): string {
  const code = nonEmptyString(value)
  if (code.length > 80) return invalidFamilyResponse()
  return code
}

function parseMember(value: unknown): FamilyMember {
  const raw = asRecord(value)
  return {
    user_id: uuid(raw.user_id),
    role: role(raw.role),
    created_at: isoDateTime(raw.created_at),
  }
}

export function parseFamilyResponse(value: unknown): FamilyResponse {
  const raw = asRecord(value)
  if (!Array.isArray(raw.members)) return invalidFamilyResponse()
  const members = raw.members.map(parseMember)
  if (members.length === 0) return invalidFamilyResponse()
  const memberIds = new Set(members.map((item) => item.user_id.toLowerCase()))
  if (memberIds.size !== members.length) return invalidFamilyResponse()
  if (members.filter((item) => item.role === 'OWNER').length !== 1) {
    return invalidFamilyResponse()
  }
  return {
    family_id: uuid(raw.family_id),
    current_user_role: role(raw.current_user_role),
    members,
  }
}

export function parseFamilyInvite(value: unknown): FamilyInvite {
  const raw = asRecord(value)
  return {
    invite_id: uuid(raw.invite_id),
    token: nonEmptyString(raw.token),
    expires_at: isoDateTime(raw.expires_at),
  }
}

function parsePermissionGrant(value: unknown): FamilyPermissionGrant {
  const raw = asRecord(value)
  if (!Array.isArray(raw.permissions)) return invalidFamilyResponse()
  const permissions = raw.permissions.map(permissionCode)
  if (new Set(permissions).size !== permissions.length) return invalidFamilyResponse()
  return {
    grantee_user_id: uuid(raw.grantee_user_id),
    permissions,
  }
}

export function parseFamilyPermissionGrant(value: unknown): FamilyPermissionGrant {
  return parsePermissionGrant(value)
}

export function parseFamilyPermissions(value: unknown): FamilyPermissionGrant[] {
  if (!Array.isArray(value)) return invalidFamilyResponse()
  const grants = value.map(parsePermissionGrant)
  const ids = grants.map((item) => item.grantee_user_id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidFamilyResponse()
  return grants
}

export function parseFamilyCurrentLocation(
  value: unknown,
  expectedResourceOwnerUserId: string,
): FamilyCurrentLocation {
  if (!isUuid(expectedResourceOwnerUserId)) return invalidFamilyResponse()
  const raw = asRecord(value)
  const ownerId = uuid(raw.resource_owner_user_id)
  if (ownerId.toLowerCase() !== expectedResourceOwnerUserId.toLowerCase()) {
    return invalidFamilyResponse()
  }
  const latitude = finiteNumber(raw.latitude)
  const longitude = finiteNumber(raw.longitude)
  if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
    return invalidFamilyResponse()
  }
  const recordedAt = isoDateTime(raw.recorded_at)
  const freshUntil = isoDateTime(raw.fresh_until)
  if (Date.parse(freshUntil) < Date.parse(recordedAt)) return invalidFamilyResponse()

  // Deliberately return only the display whitelist. Any future server fields such as
  // device identifiers or speed cannot accidentally become Family UI state.
  return {
    latitude,
    longitude,
    accuracy: nullableAccuracy(raw.accuracy),
    recorded_at: recordedAt,
    fresh_until: freshUntil,
  }
}

export function parseFamilyTodayFootprint(value: unknown): TodayFootprintResponse {
  // Reuse the exact same strict parser as the first-party Today page. It already
  // rejects malformed visit state and its read model contains no raw coordinates.
  return parseTodayFootprintResponse(value)
}

function parseFamilyMemory(value: unknown): FamilyMemory {
  const raw = asRecord(value)
  return {
    memory_id: uuid(raw.memory_id),
    memory_type: nonEmptyString(raw.memory_type),
    title: nullableString(raw.title, 240),
    content: stringValue(raw.content),
    occurred_at: isoDateTime(raw.occurred_at),
    source_type: nonEmptyString(raw.source_type),
    is_confirmed: booleanValue(raw.is_confirmed),
    edit_revision: nonNegativeInteger(raw.edit_revision),
    created_at: isoDateTime(raw.created_at),
  }
}

export function parseFamilyMemories(value: unknown): FamilyMemory[] {
  if (!Array.isArray(value) || value.length > 50) return invalidFamilyResponse()
  const memories = value.map(parseFamilyMemory)
  const ids = memories.map((item) => item.memory_id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidFamilyResponse()

  // Return only the explicit Family-safe projection. Unknown server fields are ignored
  // so metadata/location/internal source identifiers cannot become UI state.
  return memories
}

export function parseFamilyPhotos(value: unknown): FamilyPhoto[] {
  if (!Array.isArray(value) || value.length > 50) return invalidFamilyResponse()
  const photos = value.map((item) => {
    const raw = asRecord(item)
    const contentType = nonEmptyString(raw.content_type)
    if (!contentType.startsWith('image/') || contentType.length > 100) return invalidFamilyResponse()
    if (typeof raw.size_bytes !== 'number' || !Number.isSafeInteger(raw.size_bytes) || raw.size_bytes <= 0) {
      return invalidFamilyResponse()
    }
    return {
      media_id: uuid(raw.media_id),
      content_type: contentType,
      size_bytes: raw.size_bytes,
      created_at: isoDateTime(raw.created_at),
      completed_at: raw.completed_at === null ? null : isoDateTime(raw.completed_at),
    }
  })
  const ids = photos.map((item) => item.media_id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidFamilyResponse()
  return photos
}

function exactFamilyPermissionCode(value: unknown): FamilyPermissionCode {
  if (
    value !== FAMILY_PERMISSION.VIEW_CURRENT_LOCATION
    && value !== FAMILY_PERMISSION.VIEW_FOOTPRINT
    && value !== FAMILY_PERMISSION.VIEW_MEMORY
    && value !== FAMILY_PERMISSION.VIEW_PHOTOS
  ) return invalidFamilyResponse()
  return value
}

function auditResourceType(value: unknown): FamilyAuditResourceType {
  if (value !== 'CURRENT_LOCATION' && value !== 'TODAY_FOOTPRINT' && value !== 'MEMORY' && value !== 'PHOTO') {
    return invalidFamilyResponse()
  }
  return value
}

function auditAuthorityType(value: unknown): FamilyAuditAuthorityType {
  if (value !== 'EXACT_GRANT' && value !== 'EMERGENCY_SHARE') {
    return invalidFamilyResponse()
  }
  return value
}

function auditAction(value: unknown): FamilyAuditAction {
  if (
    value !== 'READ_CURRENT_LOCATION'
    && value !== 'READ_TODAY_FOOTPRINT'
    && value !== 'READ_MEMORY'
    && value !== 'LIST_PHOTOS'
    && value !== 'DOWNLOAD_PHOTO'
    && value !== 'READ_EMERGENCY_LOCATION'
  ) return invalidFamilyResponse()
  return value
}

function auditResult(value: unknown): FamilyAuditResult {
  if (value !== 'ALLOWED' && value !== 'DENIED' && value !== 'UNAVAILABLE') {
    return invalidFamilyResponse()
  }
  return value
}

export function parseFamilyAudit(value: unknown): FamilyAuditEvent[] {
  if (!Array.isArray(value) || value.length > 50) return invalidFamilyResponse()
  const rows = value.map((item) => {
    const raw = asRecord(item)
    const authorityType = auditAuthorityType(raw.authority_type)
    const permission = raw.permission_code === null
      ? null
      : exactFamilyPermissionCode(raw.permission_code)
    if (
      (authorityType === 'EXACT_GRANT' && permission === null)
      || (authorityType === 'EMERGENCY_SHARE' && permission !== null)
    ) return invalidFamilyResponse()
    const action = auditAction(raw.action)
    if (
      (authorityType === 'EMERGENCY_SHARE'
        && (
          action !== 'READ_EMERGENCY_LOCATION'
          || raw.resource_type !== 'CURRENT_LOCATION'
        ))
      || (authorityType === 'EXACT_GRANT' && action === 'READ_EMERGENCY_LOCATION')
    ) return invalidFamilyResponse()
    return {
      event_id: uuid(raw.event_id),
      actor_user_id: uuid(raw.actor_user_id),
      resource_owner_user_id: uuid(raw.resource_owner_user_id),
      authority_type: authorityType,
      permission_code: permission,
      resource_type: auditResourceType(raw.resource_type),
      action,
      result: auditResult(raw.result),
      created_at: isoDateTime(raw.created_at),
    }
  })
  const ids = rows.map((item) => item.event_id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidFamilyResponse()
  for (let index = 1; index < rows.length; index += 1) {
    const previous = rows[index - 1]
    const current = rows[index]
    if (
      Date.parse(previous.created_at) < Date.parse(current.created_at)
      || (
        previous.created_at === current.created_at
        && previous.event_id.toLowerCase() < current.event_id.toLowerCase()
      )
    ) return invalidFamilyResponse()
  }
  return rows
}

export function familyAuditActionLabel(action: FamilyAuditAction): string {
  if (action === 'READ_CURRENT_LOCATION') return '查看当前位置'
  if (action === 'READ_TODAY_FOOTPRINT') return '查看今日足迹'
  if (action === 'READ_MEMORY') return '查看个人记忆'
  if (action === 'LIST_PHOTOS') return '查看照片列表'
  if (action === 'DOWNLOAD_PHOTO') return '打开照片'
  return '查看紧急位置'
}

export function familyAuditResultLabel(result: FamilyAuditResult): string {
  if (result === 'ALLOWED') return '已允许'
  if (result === 'DENIED') return '已拒绝'
  return '数据不可用'
}


function arrivalStatus(value: unknown): FamilyArrivalReminderStatus {
  if (
    value !== 'ACTIVE'
    && value !== 'ARRIVED'
    && value !== 'CANCELLED'
    && value !== 'EXPIRED'
  ) return invalidFamilyResponse()
  return value
}

export function parseFamilyArrivalReminders(
  value: unknown,
  expectedCurrentUserId?: string,
): FamilyArrivalReminder[] {
  if (!Array.isArray(value) || value.length > 50) return invalidFamilyResponse()
  if (expectedCurrentUserId !== undefined && !isUuid(expectedCurrentUserId)) {
    return invalidFamilyResponse()
  }
  const rows = value.map((item) => {
    const raw = asRecord(item)
    if (raw.direction !== 'OUTGOING' && raw.direction !== 'INCOMING') {
      return invalidFamilyResponse()
    }
    const direction: FamilyArrivalReminderDirection = raw.direction
    const ownerId = uuid(raw.resource_owner_user_id)
    const granteeId = uuid(raw.grantee_user_id)
    if (ownerId.toLowerCase() === granteeId.toLowerCase()) return invalidFamilyResponse()
    if (
      expectedCurrentUserId !== undefined
      && (
        (direction === 'OUTGOING'
          && ownerId.toLowerCase() !== expectedCurrentUserId.toLowerCase())
        || (direction === 'INCOMING'
          && granteeId.toLowerCase() !== expectedCurrentUserId.toLowerCase())
      )
    ) return invalidFamilyResponse()

    const createdAt = isoDateTime(raw.created_at)
    const expiresAt = isoDateTime(raw.expires_at)
    const validityMinutes = (Date.parse(expiresAt) - Date.parse(createdAt)) / 60000
    if (![120, 360, 720].includes(validityMinutes)) return invalidFamilyResponse()

    const status = arrivalStatus(raw.status)
    const arrivedAt = raw.arrived_at === null ? null : isoDateTime(raw.arrived_at)
    if ((status === 'ARRIVED') !== (arrivedAt !== null)) return invalidFamilyResponse()
    if (
      arrivedAt !== null
      && (
        Date.parse(arrivedAt) < Date.parse(createdAt)
        || Date.parse(arrivedAt) >= Date.parse(expiresAt)
      )
    ) {
      return invalidFamilyResponse()
    }

    const displayName = nonEmptyString(raw.destination_display_name)
    if (displayName.length > 200) return invalidFamilyResponse()

    return {
      reminder_id: uuid(raw.reminder_id),
      resource_owner_user_id: ownerId,
      grantee_user_id: granteeId,
      destination_place_id: uuid(raw.destination_place_id),
      destination_display_name: displayName,
      status,
      created_at: createdAt,
      expires_at: expiresAt,
      arrived_at: arrivedAt,
      direction,
    }
  })
  const ids = rows.map((item) => item.reminder_id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidFamilyResponse()
  return rows
}

export function familyArrivalStatusLabel(status: FamilyArrivalReminderStatus): string {
  if (status === 'ACTIVE') return '等待到达'
  if (status === 'ARRIVED') return '已到达'
  if (status === 'CANCELLED') return '已取消'
  return '已过期'
}

export function parseFamilyEmergencyShares(
  value: unknown,
  expectedCurrentUserId?: string,
): FamilyEmergencyLocationShare[] {
  if (!Array.isArray(value) || value.length > 50) return invalidFamilyResponse()
  if (expectedCurrentUserId !== undefined && !isUuid(expectedCurrentUserId)) {
    return invalidFamilyResponse()
  }
  const rows = value.map((item) => {
    const raw = asRecord(item)
    if (raw.direction !== 'OUTGOING' && raw.direction !== 'INCOMING') {
      return invalidFamilyResponse()
    }
    const direction: FamilyEmergencyShareDirection = raw.direction
    const ownerId = uuid(raw.resource_owner_user_id)
    const granteeId = uuid(raw.grantee_user_id)
    if (ownerId.toLowerCase() === granteeId.toLowerCase()) {
      return invalidFamilyResponse()
    }
    if (
      expectedCurrentUserId !== undefined
      && (
        (direction === 'OUTGOING'
          && ownerId.toLowerCase() !== expectedCurrentUserId.toLowerCase())
        || (direction === 'INCOMING'
          && granteeId.toLowerCase() !== expectedCurrentUserId.toLowerCase())
      )
    ) return invalidFamilyResponse()
    const createdAt = isoDateTime(raw.created_at)
    const expiresAt = isoDateTime(raw.expires_at)
    const durationMs = Date.parse(expiresAt) - Date.parse(createdAt)
    if (![30, 60, 180].includes(durationMs / 60000)) {
      return invalidFamilyResponse()
    }
    return {
      share_id: uuid(raw.share_id),
      resource_owner_user_id: ownerId,
      grantee_user_id: granteeId,
      expires_at: expiresAt,
      created_at: createdAt,
      direction,
    }
  })
  const ids = rows.map((item) => item.share_id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidFamilyResponse()
  return rows
}

export function parseEmergencyFamilyCurrentLocation(
  value: unknown,
  expectedResourceOwnerUserId: string,
): FamilyCurrentLocation {
  return parseFamilyCurrentLocation(value, expectedResourceOwnerUserId)
}

export function parseFamilyPhotoDownload(
  value: unknown,
  expectedMediaId: string,
): FamilyPhotoDownload {
  if (!isUuid(expectedMediaId)) return invalidFamilyResponse()
  const raw = asRecord(value)
  const mediaId = uuid(raw.media_id)
  if (mediaId.toLowerCase() !== expectedMediaId.toLowerCase()) return invalidFamilyResponse()

  const transfer = asRecord(raw.download)
  if (transfer.method !== 'GET') return invalidFamilyResponse()
  const url = nonEmptyString(transfer.url)
  if (!/^https:\/\//i.test(url) || url.length > 4096) return invalidFamilyResponse()

  const rawHeaders = asRecord(transfer.headers)
  const headers: Record<string, string> = {}
  for (const [key, headerValue] of Object.entries(rawHeaders)) {
    if (!key.trim() || key.length > 200 || typeof headerValue !== 'string') return invalidFamilyResponse()
    headers[key] = headerValue
  }
  return {
    media_id: mediaId,
    download: {
      method: 'GET',
      url,
      headers,
      expires_at: isoDateTime(transfer.expires_at),
    },
  }
}

export function assertCurrentFamilyMember(
  family: FamilyResponse,
  currentUserId: string,
): FamilyMember {
  if (!isUuid(currentUserId)) return invalidFamilyResponse()
  const member = family.members.find(
    (item) => item.user_id.toLowerCase() === currentUserId.toLowerCase(),
  )
  if (!member || member.role !== family.current_user_role) return invalidFamilyResponse()
  return member
}

export function familyMemberActions(
  currentUserId: string,
  currentUserRole: FamilyRole,
  member: FamilyMember,
): FamilyMemberActions {
  const isSelf = member.user_id.toLowerCase() === currentUserId.toLowerCase()
  return {
    isSelf,
    showPermissionControls: !isSelf,
    showSensitiveReads: !isSelf,
    showOwnerRemove: currentUserRole === 'OWNER' && !isSelf && member.role === 'MEMBER',
    showMemberLeave: currentUserRole === 'MEMBER' && isSelf,
  }
}

export function shortMemberId(userId: string): string {
  if (!isUuid(userId)) return '未知成员'
  return `${userId.slice(0, 4)}…${userId.slice(-4)}`
}

export function permissionLabel(code: InteractiveFamilyPermissionCode): string {
  if (code === FAMILY_PERMISSION.VIEW_CURRENT_LOCATION) {
    return '我允许 TA 查看我的当前位置'
  }
  if (code === FAMILY_PERMISSION.VIEW_FOOTPRINT) {
    return '我允许 TA 查看我的今日足迹'
  }
  if (code === FAMILY_PERMISSION.VIEW_MEMORY) {
    return '我允许 TA 查看我的个人记忆'
  }
  return '我允许 TA 查看我的照片'
}

export function replaceVisiblePermission(
  current: readonly string[],
  code: InteractiveFamilyPermissionCode,
  enabled: boolean,
): string[] {
  const next = current.filter((item) => item !== code)
  if (enabled) next.push(code)
  return next
}

export class FamilyPermissionMutationGate {
  private readonly pending = new Set<string>()

  begin(granteeUserId: string): boolean {
    const key = granteeUserId.toLowerCase()
    if (this.pending.has(key)) return false
    this.pending.add(key)
    return true
  }

  end(granteeUserId: string): void {
    this.pending.delete(granteeUserId.toLowerCase())
  }

  isPending(granteeUserId: string): boolean {
    return this.pending.has(granteeUserId.toLowerCase())
  }
}

export class FamilySensitiveReadEpoch {
  private generation = 0

  capture(): number {
    return this.generation
  }

  invalidate(): number {
    this.generation += 1
    return this.generation
  }

  isCurrent(capturedGeneration: number): boolean {
    return capturedGeneration === this.generation
  }
}

export type FamilyErrorContext =
  | 'load'
  | 'create'
  | 'join'
  | 'invite-create'
  | 'invite-revoke'
  | 'remove'
  | 'leave'
  | 'permission'
  | 'current-location'
  | 'footprint'
  | 'memory'
  | 'photos'
  | 'photo-download'
  | 'audit'
  | 'emergency-share'
  | 'emergency-location'
  | 'arrival-reminder'

export function familyErrorMessage(code: string | null, context: FamilyErrorContext): string | null {
  if (!code) return null
  switch (code) {
    case 'FAMILY_NOT_FOUND':
      return context === 'load' ? null : '当前还没有加入家庭'
    case 'FAMILY_ALREADY_JOINED':
      return '你已经加入了一个家庭'
    case 'FAMILY_OWNER_REQUIRED':
      return '只有家庭 OWNER 可以执行此操作'
    case 'FAMILY_MEMBER_NOT_FOUND':
      return '该家庭成员已不存在，请刷新后重试'
    case 'FAMILY_OWNER_CANNOT_LEAVE':
      return '家庭 OWNER 不能通过成员退出操作离开家庭'
    case 'FAMILY_OWNER_CANNOT_BE_REMOVED':
      return '家庭 OWNER 不能作为普通成员移除'
    case 'FAMILY_PERMISSION_SELF_GRANT_FORBIDDEN':
      return '不能给自己配置家庭查看权限'
    case 'FAMILY_PERMISSION_UNSUPPORTED':
      return '服务端不支持这项家庭权限，请刷新后重试'
    case 'FAMILY_INVITE_INVALID':
      return '邀请口令无效'
    case 'FAMILY_INVITE_EXPIRED':
      return '邀请口令已过期'
    case 'FAMILY_INVITE_NOT_ACTIVE':
      return '邀请口令已失效，可能已使用或已撤销'
    case 'FAMILY_INVITE_NOT_FOUND':
      return '邀请已不存在，请重新创建'
    case 'FAMILY_READ_NOT_AUTHORIZED':
      if (context === 'current-location') return '对方未授权查看当前位置'
      if (context === 'footprint') return '对方未授权查看今日足迹'
      if (context === 'memory') return '对方未授权查看个人记忆'
      if (context === 'photos' || context === 'photo-download') return '对方未授权查看照片'
      return '当前家庭读取未获授权'
    case 'FAMILY_PHOTO_UNAVAILABLE':
      return '这张照片已不可用'
    case 'FAMILY_PHOTO_STORAGE_UNAVAILABLE':
      return '照片暂时无法打开，请稍后重试'
    case 'FAMILY_SELF_READ_NOT_APPLICABLE':
      return '不能通过家庭共享入口查看自己的数据'
    case 'CURRENT_LOCATION_UNAVAILABLE':
      return '当前位置暂不可用'
    case 'OWNER_REQUIRED':
      return context === 'audit' ? '无权查看家庭隐私访问记录' : '只有家庭 OWNER 可以执行此操作'
    case 'EMERGENCY_SHARE_NOT_AVAILABLE':
      return context === 'emergency-location' ? '紧急位置共享已不可用' : '紧急位置共享不可用'
    case 'EMERGENCY_SHARE_TARGET_INVALID':
      return '只能选择当前家庭中的其他成员'
    case 'EMERGENCY_SHARE_DURATION_UNSUPPORTED':
      return '请选择 30、60 或 180 分钟'
    case 'ARRIVAL_REMINDER_NOT_AVAILABLE':
      return '到家提醒已不可用'
    case 'ARRIVAL_REMINDER_TARGET_INVALID':
      return '只能选择当前家庭中的其他成员'
    case 'ARRIVAL_REMINDER_DESTINATION_INVALID':
      return '只能选择你自己的已有地点'
    case 'ARRIVAL_REMINDER_VALIDITY_UNSUPPORTED':
      return '请选择 2、6 或 12 小时'
    default:
      return null
  }
}
