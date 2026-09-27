import {
  isUuid,
  parseMemoryRead,
  type MemoryRead,
  type MemoryType,
} from './memoryFeedback'

export type PersonMemoryRelationKind = 'RELATED' | 'MET'

export type PersonMemoryLinkRead = {
  id: string
  person_id: string
  memory_id: string
  relation_kind: PersonMemoryRelationKind
  revision: number
  created_at: string
  updated_at: string
}

export type PersonMemoryTimelineRow = PersonMemoryLinkRead & {
  occurred_at: string
  memory_title: string | null
  memory_content: string
  memory_type: MemoryType
}

export type PersonInteractionRow = PersonMemoryLinkRead & {
  person_display_name: string
  occurred_at: string
}

export type PersonMemoryLinkPatchPayload = {
  relation_kind: PersonMemoryRelationKind
  expected_revision: number
}

export type PersonMemoryAuthoritySnapshot = Readonly<{
  generation: number
  owner: string
  sessionEpoch: number
  personId: string | null
  action: string
  memoryId: string | null
  linkRevision: number | null
}>

const RELATIONS = new Set<PersonMemoryRelationKind>(['RELATED', 'MET'])
const MEMORY_TYPES = new Set<MemoryType>([
  'NOTE',
  'VOICE',
  'PHOTO',
  'PLACE',
  'OBJECT_LOCATION',
  'REMINDER',
  'EVENT',
])

function invalid(): never {
  throw new Error('人物记忆数据异常，请稍后重试')
}

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return invalid()
  return value as Record<string, unknown>
}

function nonEmptyString(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return invalid()
  return value
}

function nullableString(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string') return invalid()
  return value
}

function nonNegativeInteger(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) return invalid()
  return Number(value)
}

function awareIso(value: unknown): string {
  if (
    typeof value !== 'string'
    || !/T/.test(value)
    || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    || !Number.isFinite(Date.parse(value))
  ) return invalid()
  return value
}

function relation(value: unknown): PersonMemoryRelationKind {
  if (typeof value !== 'string' || !RELATIONS.has(value as PersonMemoryRelationKind)) return invalid()
  return value as PersonMemoryRelationKind
}

function parseLinkBase(
  value: unknown,
  expectedPersonId?: string,
  expectedMemoryId?: string,
): PersonMemoryLinkRead {
  const raw = asRecord(value)
  if (!isUuid(raw.id) || !isUuid(raw.person_id) || !isUuid(raw.memory_id)) return invalid()
  if (
    expectedPersonId !== undefined
    && (!isUuid(expectedPersonId) || raw.person_id.toLowerCase() !== expectedPersonId.toLowerCase())
  ) return invalid()
  if (
    expectedMemoryId !== undefined
    && (!isUuid(expectedMemoryId) || raw.memory_id.toLowerCase() !== expectedMemoryId.toLowerCase())
  ) return invalid()

  return {
    id: raw.id,
    person_id: raw.person_id,
    memory_id: raw.memory_id,
    relation_kind: relation(raw.relation_kind),
    revision: nonNegativeInteger(raw.revision),
    created_at: awareIso(raw.created_at),
    updated_at: awareIso(raw.updated_at),
  }
}

export function parsePersonMemoryLink(
  value: unknown,
  expectedPersonId?: string,
  expectedMemoryId?: string,
): PersonMemoryLinkRead {
  return parseLinkBase(value, expectedPersonId, expectedMemoryId)
}

export function parsePersonMemoryTimeline(
  value: unknown,
  expectedPersonId: string,
  limit = 50,
): PersonMemoryTimelineRow[] {
  if (!isUuid(expectedPersonId)) return invalid()
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('人物记忆列表数量必须在 1 到 100 之间')
  }
  if (!Array.isArray(value) || value.length > limit || value.length > 100) return invalid()

  return value.map((item) => {
    const raw = asRecord(item)
    const base = parseLinkBase(raw, expectedPersonId)
    if (typeof raw.memory_type !== 'string' || !MEMORY_TYPES.has(raw.memory_type as MemoryType)) {
      return invalid()
    }
    if (typeof raw.memory_content !== 'string' || !raw.memory_content.trim()) return invalid()
    return {
      ...base,
      occurred_at: awareIso(raw.occurred_at),
      memory_title: nullableString(raw.memory_title),
      memory_content: raw.memory_content,
      memory_type: raw.memory_type as MemoryType,
    }
  })
}

export function parsePersonInteractions(value: unknown, limit = 20): PersonInteractionRow[] {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('最近互动数量必须在 1 到 100 之间')
  }
  if (!Array.isArray(value) || value.length > limit || value.length > 100) return invalid()

  return value.map((item) => {
    const raw = asRecord(item)
    const base = parseLinkBase(raw)
    if (base.relation_kind !== 'MET') return invalid()
    return {
      ...base,
      person_display_name: nonEmptyString(raw.person_display_name),
      occurred_at: awareIso(raw.occurred_at),
    }
  })
}

export function parseMemoryPickerRows(
  value: unknown,
  expectedOwner: string,
  limit = 50,
): MemoryRead[] {
  if (!isUuid(expectedOwner)) throw new Error('当前账号身份无效，请重新登录')
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('记忆选择数量必须在 1 到 100 之间')
  }
  if (!Array.isArray(value) || value.length > limit || value.length > 100) return invalid()

  // Parse the collection completely before filtering by owner. A malformed row
  // invalidates the whole response so the picker never publishes a partially
  // trusted subset from one server response.
  const parsedRows = value.map((item) => parseMemoryRead(item))
  return parsedRows.filter(
    (row) => row.user_id.toLowerCase() === expectedOwner.toLowerCase(),
  )
}

export function buildPersonMemoryTimelinePath(personId: string, limit = 50): string {
  if (!isUuid(personId)) throw new Error('人物参数无效')
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('人物记忆列表数量必须在 1 到 100 之间')
  }
  return `/people/${encodeURIComponent(personId)}/memories?limit=${limit}`
}

export function buildPersonMemoryLinkPath(personId: string, memoryId: string): string {
  if (!isUuid(personId) || !isUuid(memoryId)) throw new Error('人物或记忆参数无效')
  return `/people/${encodeURIComponent(personId)}/memories/${encodeURIComponent(memoryId)}`
}

export function buildPersonInteractionsPath(limit = 20): string {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('最近互动数量必须在 1 到 100 之间')
  }
  return `/people/interactions?limit=${limit}`
}

export function buildMemoryPickerPath(limit = 50): string {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('记忆选择数量必须在 1 到 100 之间')
  }
  return `/timeline?limit=${limit}`
}

export function buildPersonMemoryCreatePayload(
  relationKind: PersonMemoryRelationKind,
): { relation_kind: PersonMemoryRelationKind } {
  if (!RELATIONS.has(relationKind)) throw new Error('人物记忆关系无效')
  return { relation_kind: relationKind }
}

export function buildPersonMemoryPatchPayload(
  link: PersonMemoryLinkRead,
  relationKind: PersonMemoryRelationKind,
): PersonMemoryLinkPatchPayload | null {
  if (!RELATIONS.has(relationKind)) throw new Error('人物记忆关系无效')
  if (link.relation_kind === relationKind) return null
  return { relation_kind: relationKind, expected_revision: link.revision }
}

export function personMemoryRelationLabel(kind: PersonMemoryRelationKind): string {
  return kind === 'RELATED' ? '相关' : '见过 / 互动过'
}

export function personMemoryTypeLabel(kind: MemoryType): string {
  const labels: Record<MemoryType, string> = {
    NOTE: '文字',
    VOICE: '语音',
    PHOTO: '照片',
    PLACE: '地点',
    OBJECT_LOCATION: '物品位置',
    REMINDER: '提醒',
    EVENT: '事件',
  }
  return labels[kind]
}

export function personMemoryPreview(content: string, maxLength = 88): string {
  const normalized = content.replace(/\s+/g, ' ').trim()
  return normalized.length <= maxLength ? normalized : `${normalized.slice(0, maxLength)}…`
}

export function formatPersonMemoryTime(value: string): string {
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) return ''
  const pad = (input: number) => String(input).padStart(2, '0')
  return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
}

export function personMemoryErrorMessage(code: string | null): string | null {
  switch (code) {
    case 'PERSON_NOT_FOUND':
    case 'MEMORY_NOT_FOUND':
    case 'PERSON_MEMORY_LINK_NOT_FOUND':
      return '这条关联当前不可用，请刷新后重试'
    case 'PERSON_MEMORY_LINK_RELATION_CONFLICT':
      return '这条记忆已经以另一种关系关联，请先刷新或修改关系'
    case 'PERSON_MEMORY_LINK_REVISION_CONFLICT':
      return '这条人物记忆关联已经变化，请刷新后重新选择关系'
    default:
      return null
  }
}

export class PersonMemoryUiAuthority {
  private generation = 0

  invalidate(): void {
    this.generation += 1
  }

  capture(input: {
    owner: string | null
    sessionEpoch: number
    personId?: string | null
    action: string
    memoryId?: string | null
    linkRevision?: number | null
  }): PersonMemoryAuthoritySnapshot {
    if (!input.owner || !isUuid(input.owner)) throw new Error('请先登录')
    if (!Number.isSafeInteger(input.sessionEpoch) || input.sessionEpoch < 0) {
      throw new Error('登录状态异常，请重新登录')
    }
    const personId = input.personId ?? null
    const memoryId = input.memoryId ?? null
    const linkRevision = input.linkRevision ?? null
    if (personId !== null && !isUuid(personId)) throw new Error('人物参数无效')
    if (memoryId !== null && !isUuid(memoryId)) throw new Error('记忆参数无效')
    if (linkRevision !== null && (!Number.isSafeInteger(linkRevision) || linkRevision < 0)) {
      throw new Error('关联版本无效，请刷新')
    }
    if (!input.action.trim()) throw new Error('人物记忆操作无效')
    return {
      generation: this.generation,
      owner: input.owner,
      sessionEpoch: input.sessionEpoch,
      personId,
      action: input.action,
      memoryId,
      linkRevision,
    }
  }

  isCurrent(
    snapshot: PersonMemoryAuthoritySnapshot,
    input: {
      owner: string | null
      sessionEpoch: number
      personId?: string | null
      action: string
      memoryId?: string | null
      linkRevision?: number | null
    },
  ): boolean {
    return (
      snapshot.generation === this.generation
      && snapshot.owner === input.owner
      && snapshot.sessionEpoch === input.sessionEpoch
      && snapshot.personId === (input.personId ?? null)
      && snapshot.action === input.action
      && snapshot.memoryId === (input.memoryId ?? null)
      && snapshot.linkRevision === (input.linkRevision ?? null)
    )
  }
}
