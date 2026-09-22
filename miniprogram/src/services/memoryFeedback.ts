export type MemoryType =
  | 'NOTE'
  | 'VOICE'
  | 'PHOTO'
  | 'PLACE'
  | 'OBJECT_LOCATION'
  | 'REMINDER'
  | 'EVENT'

export type MemorySourceType =
  | 'USER_TEXT'
  | 'USER_VOICE'
  | 'USER_PHOTO'
  | 'GPS'
  | 'PHOTO_EXIF'
  | 'SYSTEM_PLACE'
  | 'AI_INFERENCE'

export type MemoryRead = {
  id: string
  user_id: string
  memory_type: MemoryType
  title: string | null
  content: string
  occurred_at: string
  source_type: MemorySourceType
  confidence: number
  place_id: string | null
  latitude: number | null
  longitude: number | null
  is_confirmed: boolean
  metadata_json: Record<string, unknown>
  edit_revision: number
  edited_at: string | null
  created_at: string
}

export type MemoryFeedbackAction = 'CONFIRM' | 'CORRECT' | 'DELETE'

export type MemoryFeedbackPayload = {
  action: MemoryFeedbackAction
  expected_revision: number
  title?: string
  content?: string
}

export type MemoryFeedbackRead = {
  id: string
  user_id: string
  memory_id: string
  memory_revision: number
  result_revision: number | null
  action: MemoryFeedbackAction
  created_at: string
}

export type SafeRequestOptions = Readonly<{
  idempotencyKey?: string
}>

export type MemoryFeedbackOperation = Readonly<{
  memoryId: string
  idempotencyKey: string
  payload: Readonly<MemoryFeedbackPayload>
}>

export type TrustPresentation = {
  label: string
  detail: string
  tone: 'supported' | 'insufficient' | 'neutral'
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const MEMORY_TYPES = new Set<MemoryType>([
  'NOTE',
  'VOICE',
  'PHOTO',
  'PLACE',
  'OBJECT_LOCATION',
  'REMINDER',
  'EVENT',
])
const SOURCE_TYPES = new Set<MemorySourceType>([
  'USER_TEXT',
  'USER_VOICE',
  'USER_PHOTO',
  'GPS',
  'PHOTO_EXIF',
  'SYSTEM_PLACE',
  'AI_INFERENCE',
])
const FEEDBACK_ACTIONS = new Set<MemoryFeedbackAction>(['CONFIRM', 'CORRECT', 'DELETE'])

function invalidMemoryResponse(): never {
  throw new Error('记忆数据异常，请稍后重试')
}

function invalidFeedbackResponse(): never {
  throw new Error('记忆反馈数据异常，请稍后重试')
}

function asRecord(value: unknown, invalid: () => never): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return invalid()
  return value as Record<string, unknown>
}

export function isUuid(value: unknown): value is string {
  return typeof value === 'string' && UUID_PATTERN.test(value)
}

function nonNegativeInteger(value: unknown, invalid: () => never): number {
  if (!Number.isInteger(value) || Number(value) < 0) return invalid()
  return Number(value)
}

function finiteNumber(value: unknown, invalid: () => never): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return invalid()
  return value
}

function nullableFiniteNumber(value: unknown, invalid: () => never): number | null {
  if (value === null) return null
  return finiteNumber(value, invalid)
}

function awareIsoDateTime(value: unknown, invalid: () => never): string {
  if (
    typeof value !== 'string'
    || !/T/.test(value)
    || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    || !Number.isFinite(Date.parse(value))
  ) {
    return invalid()
  }
  return value
}

function nullableAwareIsoDateTime(value: unknown, invalid: () => never): string | null {
  if (value === null) return null
  return awareIsoDateTime(value, invalid)
}

function nullableUuid(value: unknown, invalid: () => never): string | null {
  if (value === null) return null
  if (!isUuid(value)) return invalid()
  return value
}

function stringOrNull(value: unknown, invalid: () => never): string | null {
  if (value === null) return null
  if (typeof value !== 'string') return invalid()
  return value
}

export function parseMemoryRead(value: unknown, expectedMemoryId?: string): MemoryRead {
  const raw = asRecord(value, invalidMemoryResponse)
  if (!isUuid(raw.id) || !isUuid(raw.user_id)) return invalidMemoryResponse()
  if (expectedMemoryId !== undefined) {
    if (!isUuid(expectedMemoryId) || raw.id.toLowerCase() !== expectedMemoryId.toLowerCase()) {
      return invalidMemoryResponse()
    }
  }
  if (typeof raw.memory_type !== 'string' || !MEMORY_TYPES.has(raw.memory_type as MemoryType)) {
    return invalidMemoryResponse()
  }
  if (typeof raw.source_type !== 'string' || !SOURCE_TYPES.has(raw.source_type as MemorySourceType)) {
    return invalidMemoryResponse()
  }
  const title = stringOrNull(raw.title, invalidMemoryResponse)
  // MemoryRead itself does not publish correction-form length caps. Validate the
  // response type/required content only; feedback input limits remain server-owned.
  if (typeof raw.content !== 'string' || !raw.content.trim()) {
    return invalidMemoryResponse()
  }
  const confidence = finiteNumber(raw.confidence, invalidMemoryResponse)
  if (confidence < 0 || confidence > 1) return invalidMemoryResponse()
  const latitude = nullableFiniteNumber(raw.latitude, invalidMemoryResponse)
  const longitude = nullableFiniteNumber(raw.longitude, invalidMemoryResponse)
  if (latitude !== null && (latitude < -90 || latitude > 90)) return invalidMemoryResponse()
  if (longitude !== null && (longitude < -180 || longitude > 180)) return invalidMemoryResponse()
  if (typeof raw.is_confirmed !== 'boolean') return invalidMemoryResponse()
  const metadata = asRecord(raw.metadata_json, invalidMemoryResponse)

  return {
    id: raw.id,
    user_id: raw.user_id,
    memory_type: raw.memory_type as MemoryType,
    title,
    content: raw.content,
    occurred_at: awareIsoDateTime(raw.occurred_at, invalidMemoryResponse),
    source_type: raw.source_type as MemorySourceType,
    confidence,
    place_id: nullableUuid(raw.place_id, invalidMemoryResponse),
    latitude,
    longitude,
    is_confirmed: raw.is_confirmed,
    metadata_json: { ...metadata },
    edit_revision: nonNegativeInteger(raw.edit_revision, invalidMemoryResponse),
    edited_at: nullableAwareIsoDateTime(raw.edited_at, invalidMemoryResponse),
    created_at: awareIsoDateTime(raw.created_at, invalidMemoryResponse),
  }
}

export function parseMemoryFeedbackRead(
  value: unknown,
  expected?: {
    memoryId: string
    action: MemoryFeedbackAction
    memoryRevision: number
  },
): MemoryFeedbackRead {
  const raw = asRecord(value, invalidFeedbackResponse)
  if (!isUuid(raw.id) || !isUuid(raw.user_id) || !isUuid(raw.memory_id)) {
    return invalidFeedbackResponse()
  }
  if (typeof raw.action !== 'string' || !FEEDBACK_ACTIONS.has(raw.action as MemoryFeedbackAction)) {
    return invalidFeedbackResponse()
  }
  const memoryRevision = nonNegativeInteger(raw.memory_revision, invalidFeedbackResponse)
  const resultRevision = raw.result_revision === null
    ? null
    : nonNegativeInteger(raw.result_revision, invalidFeedbackResponse)

  if (expected) {
    if (
      !isUuid(expected.memoryId)
      || raw.memory_id.toLowerCase() !== expected.memoryId.toLowerCase()
      || raw.action !== expected.action
      || memoryRevision !== expected.memoryRevision
    ) {
      return invalidFeedbackResponse()
    }
  }

  return {
    id: raw.id,
    user_id: raw.user_id,
    memory_id: raw.memory_id,
    memory_revision: memoryRevision,
    result_revision: resultRevision,
    action: raw.action as MemoryFeedbackAction,
    created_at: awareIsoDateTime(raw.created_at, invalidFeedbackResponse),
  }
}

// Request callers receive only this typed option. Runtime extra keys are ignored, so
// Authorization and Content-Type remain transport-owned even if an untyped caller passes them.
export function buildApiHeaders(
  token: string,
  options: SafeRequestOptions = {},
): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (options.idempotencyKey !== undefined) {
    if (!isUuid(options.idempotencyKey)) {
      throw new Error('无效的操作标识，请重新发起')
    }
    headers['Idempotency-Key'] = options.idempotencyKey
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

// Same UUID-v4 pattern as the existing media upload helper, without adding a dependency.
export function createFeedbackOperationId(random: () => number = Math.random): string {
  const bytes = Array.from({ length: 16 }, () => Math.floor(random() * 256) & 0xff)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = bytes.map((byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function validatePayload(payload: MemoryFeedbackPayload): MemoryFeedbackPayload {
  if (!FEEDBACK_ACTIONS.has(payload.action)) {
    throw new Error('不支持的记忆反馈操作')
  }
  if (!Number.isInteger(payload.expected_revision) || payload.expected_revision < 0) {
    throw new Error('记忆版本无效，请重新读取')
  }
  const hasTitle = Object.prototype.hasOwnProperty.call(payload, 'title')
  const hasContent = Object.prototype.hasOwnProperty.call(payload, 'content')
  if (payload.action === 'CORRECT') {
    if (!hasTitle && !hasContent) throw new Error('请先修改需要纠正的内容')
    if (hasContent && (typeof payload.content !== 'string' || !payload.content.trim())) {
      throw new Error('记忆内容不能为空')
    }
    if (hasTitle && typeof payload.title !== 'string') {
      throw new Error('记忆标题格式无效')
    }
  } else if (hasTitle || hasContent) {
    throw new Error('当前操作不能携带纠正内容')
  }
  return { ...payload }
}

export function createMemoryFeedbackOperation(
  memoryId: string,
  payload: MemoryFeedbackPayload,
  random: () => number = Math.random,
): MemoryFeedbackOperation {
  if (!isUuid(memoryId)) throw new Error('记忆标识无效，请重新查询')
  const normalized = Object.freeze(validatePayload(payload))
  return Object.freeze({
    memoryId,
    idempotencyKey: createFeedbackOperationId(random),
    payload: normalized,
  })
}

export async function executeMemoryFeedbackOperation<T>(
  operation: MemoryFeedbackOperation,
  sender: (
    memoryId: string,
    payload: MemoryFeedbackPayload,
    idempotencyKey: string,
  ) => Promise<T>,
): Promise<T> {
  return sender(operation.memoryId, { ...operation.payload }, operation.idempotencyKey)
}

export class MemoryFeedbackSingleFlightGate {
  private pending = false

  begin(): boolean {
    if (this.pending) return false
    this.pending = true
    return true
  }

  end(): void {
    this.pending = false
  }

  isPending(): boolean {
    return this.pending
  }
}

export class MemoryReviewEpoch {
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

export function buildCorrectionFeedback(
  memory: MemoryRead,
  titleDraft: string,
  contentDraft: string,
): MemoryFeedbackPayload {
  const title = titleDraft.trim()
  const content = contentDraft.trim()
  if (!content) throw new Error('记忆内容不能为空')

  const payload: MemoryFeedbackPayload = {
    action: 'CORRECT',
    expected_revision: memory.edit_revision,
  }
  if (title !== (memory.title || '').trim()) payload.title = title
  if (content !== memory.content.trim()) payload.content = content
  if (!Object.prototype.hasOwnProperty.call(payload, 'title')
    && !Object.prototype.hasOwnProperty.call(payload, 'content')) {
    throw new Error('内容没有变化，无需纠正')
  }
  return payload
}

export function trustPresentation(input: {
  can_answer: boolean
  certainty: string
}): TrustPresentation {
  if (!input.can_answer) {
    return {
      label: '没有足够证据',
      detail: '当前记录不足以把答案作为事实展示。',
      tone: 'insufficient',
    }
  }
  if (input.certainty === 'confirmed' || input.certainty === 'evidence') {
    return {
      label: '有证据支持',
      detail: '这个答案来自当前公开证据链，可继续查看下面的来源。',
      tone: 'supported',
    }
  }
  return {
    label: '答案状态待确认',
    detail: '服务端返回了新的可信状态，当前版本不会把它提升为已确认事实。',
    tone: 'neutral',
  }
}

export function isDisplayableEvidence(sourceType: string): boolean {
  return sourceType !== 'AI_INFERENCE'
}

export function provenanceLabel(provenance: string | null | undefined): string | null {
  if (provenance === 'ORIGINAL_SOURCE') return '原始来源'
  if (provenance === 'USER_EDIT') return '用户修正'
  return null
}

export function isRevisionConflictCode(code: string | null): boolean {
  return code === 'MEMORY_FEEDBACK_REVISION_CONFLICT' || code === 'MEMORY_EDIT_REVISION_CONFLICT'
}

export function feedbackErrorMessage(code: string | null): string | null {
  switch (code) {
    case 'MEMORY_NOT_FOUND':
      return '这条记忆已不存在，请重新查询'
    case 'MEMORY_FEEDBACK_REVISION_CONFLICT':
    case 'MEMORY_EDIT_REVISION_CONFLICT':
      return '记录已发生变化，请重新确认'
    case 'OBJECT_LOCATION_FEEDBACK_REQUIRES_STRUCTURED_FLOW':
    case 'OBJECT_LOCATION_EDIT_REQUIRES_STRUCTURED_FLOW':
      return '这类位置记忆需要在对应的位置功能中修改'
    case 'MEMORY_FEEDBACK_CORRECTION_NO_CHANGE':
      return '没有检测到需要纠正的内容'
    case 'IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST':
      return '本次操作状态不一致，请重新发起'
    case 'IDEMPOTENT_RESOURCE_GONE':
      return '本次操作对应的记录已不可用，请重新查询'
    default:
      return null
  }
}
