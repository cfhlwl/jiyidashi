export type PersonRead = {
  id: string
  display_name: string
  relationship_label: string | null
  note: string | null
  aliases: string[]
  revision: number
  created_at: string
  updated_at: string
}

export type PersonCreatePayload = {
  display_name: string
  relationship_label?: string
  note?: string
  aliases?: string[]
}

export type PersonPatchPayload = {
  expected_revision: number
  display_name?: string
  relationship_label?: string | null
  note?: string | null
  aliases?: string[]
}

export type PersonFormDraft = {
  displayName: string
  relationshipLabel: string
  note: string
  aliases: string[]
}

export type PeopleAuthoritySnapshot = Readonly<{
  generation: number
  owner: string
  sessionEpoch: number
  identity: string
}>

const DISPLAY_NAME_MAX = 200
const RELATIONSHIP_MAX = 120
const NOTE_MAX = 5000
const ALIAS_MAX = 200
const ALIASES_MAX = 100

function invalidPersonResponse(): never {
  throw new Error('人物数据异常，请稍后重试')
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return invalidPersonResponse()
  }
  return value as Record<string, unknown>
}

function responseString(value: unknown, maxLength?: number): string {
  if (typeof value !== 'string' || !value.trim()) return invalidPersonResponse()
  if (maxLength !== undefined && value.length > maxLength) return invalidPersonResponse()
  return value
}

function nullableResponseString(value: unknown, maxLength: number): string | null {
  if (value === null) return null
  return responseString(value, maxLength)
}

function responseRevision(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    return invalidPersonResponse()
  }
  return value
}

function normalizeRequired(value: string, maxLength: number, label: string): string {
  const normalized = value.trim()
  if (!normalized) throw new Error(`${label}不能为空`)
  if (normalized.length > maxLength) throw new Error(`${label}不能超过 ${maxLength} 个字符`)
  return normalized
}

function normalizeNullableInput(value: string, maxLength: number, label: string): string | null {
  const normalized = value.trim()
  if (!normalized) return null
  if (normalized.length > maxLength) throw new Error(`${label}不能超过 ${maxLength} 个字符`)
  return normalized
}

export function normalizePersonAliases(values: readonly string[]): string[] {
  if (values.length > ALIASES_MAX) throw new Error('别名最多 100 个')
  return values.map((value) => normalizeRequired(value, ALIAS_MAX, '别名'))
}

export function parsePersonRead(value: unknown, expectedPersonId?: string): PersonRead {
  const raw = record(value)
  const id = responseString(raw.id)
  if (
    expectedPersonId !== undefined
    && id.toLowerCase() !== expectedPersonId.trim().toLowerCase()
  ) {
    return invalidPersonResponse()
  }
  if (!Array.isArray(raw.aliases)) return invalidPersonResponse()
  const aliases = raw.aliases.map((alias) => responseString(alias, ALIAS_MAX))
  if (aliases.length > ALIASES_MAX) return invalidPersonResponse()

  return {
    id,
    display_name: responseString(raw.display_name, DISPLAY_NAME_MAX),
    relationship_label: nullableResponseString(raw.relationship_label, RELATIONSHIP_MAX),
    note: nullableResponseString(raw.note, NOTE_MAX),
    aliases,
    revision: responseRevision(raw.revision),
    created_at: responseString(raw.created_at),
    updated_at: responseString(raw.updated_at),
  }
}

export function parsePersonList(value: unknown): PersonRead[] {
  if (!Array.isArray(value)) return invalidPersonResponse()
  if (value.length > 100) return invalidPersonResponse()
  const people = value.map((item) => parsePersonRead(item))
  const ids = people.map((item) => item.id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidPersonResponse()
  return people
}

export function buildPeoplePath(limit = 100): string {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('人物列表数量必须在 1 到 100 之间')
  }
  return `/people?limit=${limit}`
}

export function personDetailRoute(personId: string): string {
  const normalized = personId.trim()
  if (!normalized) throw new Error('人物参数无效')
  return `/pages/person-detail/index?personId=${encodeURIComponent(normalized)}`
}

export function buildPersonCreatePayload(input: PersonFormDraft): PersonCreatePayload {
  const payload: PersonCreatePayload = {
    display_name: normalizeRequired(input.displayName, DISPLAY_NAME_MAX, '姓名'),
  }
  const relationship = normalizeNullableInput(
    input.relationshipLabel,
    RELATIONSHIP_MAX,
    '关系备注',
  )
  const note = normalizeNullableInput(input.note, NOTE_MAX, '备注')
  const aliases = normalizePersonAliases(input.aliases)

  if (relationship !== null) payload.relationship_label = relationship
  if (note !== null) payload.note = note
  if (aliases.length > 0) payload.aliases = aliases
  return payload
}

export function buildPersonPatchPayload(
  base: PersonRead,
  draft: PersonFormDraft,
): PersonPatchPayload {
  const payload: PersonPatchPayload = { expected_revision: base.revision }
  const displayName = normalizeRequired(draft.displayName, DISPLAY_NAME_MAX, '姓名')
  const relationship = normalizeNullableInput(
    draft.relationshipLabel,
    RELATIONSHIP_MAX,
    '关系备注',
  )
  const note = normalizeNullableInput(draft.note, NOTE_MAX, '备注')
  const aliases = normalizePersonAliases(draft.aliases)

  if (displayName !== base.display_name) payload.display_name = displayName
  if (relationship !== base.relationship_label) payload.relationship_label = relationship
  if (note !== base.note) payload.note = note
  if (
    aliases.length !== base.aliases.length
    || aliases.some((alias, index) => alias !== base.aliases[index])
  ) {
    // Explicit [] is meaningful: it clears all aliases.
    payload.aliases = aliases
  }
  return payload
}

export function hasPersonPatchChanges(payload: PersonPatchPayload): boolean {
  return Object.keys(payload).some((key) => key !== 'expected_revision')
}

export function boundedAliasSummary(person: PersonRead, limit = 3): string {
  if (person.aliases.length === 0) return ''
  const visible = person.aliases.slice(0, Math.max(1, limit))
  const suffix = person.aliases.length > visible.length ? ` 等 ${person.aliases.length} 个` : ''
  return `${visible.join(' / ')}${suffix}`
}

export function isPersonRevisionConflict(code: string | null): boolean {
  return code === 'PERSON_REVISION_CONFLICT'
}

export function personErrorMessage(code: string | null): string | null {
  if (code === 'PERSON_NOT_FOUND') return '这个人物已不存在，请返回人物列表刷新'
  if (code === 'PERSON_REVISION_CONFLICT') {
    return '人物已发生变化，请查看最新内容后重新提交'
  }
  return null
}

// This is a page/action generation guard only. Authentication authority remains the
// existing api.ts owner + authSessionEpoch; callers pass those canonical values in.
export class PeopleUiAuthority {
  private generation = 0

  invalidate(): void {
    this.generation += 1
  }

  capture(owner: string | null, sessionEpoch: number, identity: string): PeopleAuthoritySnapshot {
    if (!owner || !owner.trim()) throw new Error('请先登录')
    if (!Number.isSafeInteger(sessionEpoch) || sessionEpoch < 0) {
      throw new Error('登录状态异常，请重新登录')
    }
    if (!identity.trim()) throw new Error('人物操作身份无效')
    return {
      generation: this.generation,
      owner,
      sessionEpoch,
      identity,
    }
  }

  isCurrent(
    snapshot: PeopleAuthoritySnapshot,
    owner: string | null,
    sessionEpoch: number,
    identity: string,
  ): boolean {
    return (
      snapshot.generation === this.generation
      && snapshot.owner === owner
      && snapshot.sessionEpoch === sessionEpoch
      && snapshot.identity === identity
    )
  }
}
