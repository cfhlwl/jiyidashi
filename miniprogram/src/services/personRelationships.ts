import { isUuid, type PersonRead } from './people'

export type PersonRelationshipKind =
  | 'FAMILY'
  | 'FRIEND'
  | 'COLLEAGUE'
  | 'CLASSMATE'
  | 'OTHER'

export type PersonRelationshipOtherPerson = {
  id: string
  display_name: string
}

export type PersonRelationshipProjection = {
  relationship_id: string
  relationship_kind: PersonRelationshipKind
  custom_label: string | null
  note: string | null
  revision: number
  other_person: PersonRelationshipOtherPerson
  created_at: string
  updated_at: string
}

export type PersonRelationshipRead = {
  id: string
  person_a_id: string
  person_b_id: string
  relationship_kind: PersonRelationshipKind
  custom_label: string | null
  note: string | null
  revision: number
  created_at: string
  updated_at: string
}

export type PersonRelationshipDraft = {
  relationshipKind: PersonRelationshipKind
  customLabel: string
  note: string
}

export type PersonRelationshipCreatePayload = {
  person_a_id: string
  person_b_id: string
  relationship_kind: PersonRelationshipKind
  custom_label?: string
  note?: string
}

export type PersonRelationshipPatchPayload = {
  expected_revision: number
  relationship_kind?: PersonRelationshipKind
  custom_label?: string
  note?: string | null
}

export type PersonRelationshipConflictField = 'relationship' | 'note'

export type PersonRelationshipConflictRebase = {
  keepUserDraft: PersonRelationshipDraft
  keepServerDraft: PersonRelationshipDraft
  conflicts: PersonRelationshipConflictField[]
}

export type PersonRelationshipAuthoritySnapshot = Readonly<{
  generation: number
  owner: string
  sessionEpoch: number
  personId: string
  action: string
  relationshipId: string | null
  revision: number | null
  otherPersonId: string | null
}>

const RELATIONSHIP_KINDS = new Set<PersonRelationshipKind>([
  'FAMILY',
  'FRIEND',
  'COLLEAGUE',
  'CLASSMATE',
  'OTHER',
])

const DISPLAY_NAME_MAX = 200
const CUSTOM_LABEL_MAX = 120
const NOTE_MAX = 5000

function invalidRelationshipResponse(): never {
  throw new Error('人物关系数据异常，请稍后重试')
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return invalidRelationshipResponse()
  }
  return value as Record<string, unknown>
}

function responseString(value: unknown, maxLength: number, allowEmpty = false): string {
  if (typeof value !== 'string') return invalidRelationshipResponse()
  if ((!allowEmpty && !value.trim()) || value.length > maxLength) {
    return invalidRelationshipResponse()
  }
  return value
}

function nullableResponseString(value: unknown, maxLength: number): string | null {
  if (value === null) return null
  return responseString(value, maxLength, true)
}

function responseRevision(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    return invalidRelationshipResponse()
  }
  return value
}

function awareIsoDateTime(value: unknown): string {
  if (
    typeof value !== 'string'
    || !value.includes('T')
    || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    || !Number.isFinite(Date.parse(value))
  ) {
    return invalidRelationshipResponse()
  }
  return value
}

function parseRelationshipKind(value: unknown): PersonRelationshipKind {
  if (
    typeof value !== 'string'
    || !RELATIONSHIP_KINDS.has(value as PersonRelationshipKind)
  ) {
    return invalidRelationshipResponse()
  }
  return value as PersonRelationshipKind
}

function validateRelationshipShape(
  kind: PersonRelationshipKind,
  customLabel: string | null,
): void {
  if (kind === 'OTHER') {
    if (customLabel === null || !customLabel.trim() || customLabel.length > CUSTOM_LABEL_MAX) {
      return invalidRelationshipResponse()
    }
    return
  }
  if (customLabel !== null) return invalidRelationshipResponse()
}

export function parsePersonRelationshipProjection(
  value: unknown,
  requestedPersonId: string,
): PersonRelationshipProjection {
  if (!isUuid(requestedPersonId)) throw new Error('人物参数无效')
  const raw = record(value)
  const other = record(raw.other_person)
  if (!isUuid(raw.relationship_id) || !isUuid(other.id)) return invalidRelationshipResponse()
  if (other.id.toLowerCase() === requestedPersonId.toLowerCase()) {
    return invalidRelationshipResponse()
  }

  const kind = parseRelationshipKind(raw.relationship_kind)
  const customLabel = nullableResponseString(raw.custom_label, CUSTOM_LABEL_MAX)
  validateRelationshipShape(kind, customLabel)

  return {
    relationship_id: raw.relationship_id,
    relationship_kind: kind,
    custom_label: customLabel,
    note: nullableResponseString(raw.note, NOTE_MAX),
    revision: responseRevision(raw.revision),
    other_person: {
      id: other.id,
      display_name: responseString(other.display_name, DISPLAY_NAME_MAX),
    },
    created_at: awareIsoDateTime(raw.created_at),
    updated_at: awareIsoDateTime(raw.updated_at),
  }
}

export function parsePersonRelationshipList(
  value: unknown,
  requestedPersonId: string,
  limit = 100,
): PersonRelationshipProjection[] {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('人物关系列表数量必须在 1 到 100 之间')
  }
  if (!Array.isArray(value) || value.length > limit || value.length > 100) {
    return invalidRelationshipResponse()
  }

  // Parse the complete collection before publishing any row. A malformed edge
  // invalidates the entire response so direct-edge authority is never partial.
  const rows = value.map((item) => parsePersonRelationshipProjection(item, requestedPersonId))
  const ids = rows.map((row) => row.relationship_id.toLowerCase())
  if (new Set(ids).size !== ids.length) return invalidRelationshipResponse()
  return rows
}

export function parsePersonRelationshipRead(
  value: unknown,
  expectedRelationshipId?: string,
  expectedPersonAId?: string,
  expectedPersonBId?: string,
): PersonRelationshipRead {
  const raw = record(value)
  if (!isUuid(raw.id) || !isUuid(raw.person_a_id) || !isUuid(raw.person_b_id)) {
    return invalidRelationshipResponse()
  }
  if (raw.person_a_id.toLowerCase() === raw.person_b_id.toLowerCase()) {
    return invalidRelationshipResponse()
  }
  if (
    expectedRelationshipId !== undefined
    && (!isUuid(expectedRelationshipId) || raw.id.toLowerCase() !== expectedRelationshipId.toLowerCase())
  ) {
    return invalidRelationshipResponse()
  }
  if (expectedPersonAId !== undefined || expectedPersonBId !== undefined) {
    if (
      expectedPersonAId === undefined
      || expectedPersonBId === undefined
      || !isUuid(expectedPersonAId)
      || !isUuid(expectedPersonBId)
      || expectedPersonAId.toLowerCase() === expectedPersonBId.toLowerCase()
    ) {
      return invalidRelationshipResponse()
    }
    const actual = new Set([
      raw.person_a_id.toLowerCase(),
      raw.person_b_id.toLowerCase(),
    ])
    if (
      actual.size !== 2
      || !actual.has(expectedPersonAId.toLowerCase())
      || !actual.has(expectedPersonBId.toLowerCase())
    ) {
      return invalidRelationshipResponse()
    }
  }

  const kind = parseRelationshipKind(raw.relationship_kind)
  const customLabel = nullableResponseString(raw.custom_label, CUSTOM_LABEL_MAX)
  validateRelationshipShape(kind, customLabel)

  return {
    id: raw.id,
    person_a_id: raw.person_a_id,
    person_b_id: raw.person_b_id,
    relationship_kind: kind,
    custom_label: customLabel,
    note: nullableResponseString(raw.note, NOTE_MAX),
    revision: responseRevision(raw.revision),
    created_at: awareIsoDateTime(raw.created_at),
    updated_at: awareIsoDateTime(raw.updated_at),
  }
}

function normalizeKind(value: PersonRelationshipKind): PersonRelationshipKind {
  if (!RELATIONSHIP_KINDS.has(value)) throw new Error('人物关系类型无效')
  return value
}

function normalizeOtherLabel(value: string): string {
  const normalized = value.trim().replace(/\s+/g, ' ')
  if (!normalized) throw new Error('“其他”关系必须填写自定义关系')
  if (normalized.length > CUSTOM_LABEL_MAX) {
    throw new Error('自定义关系不能超过 120 个字符')
  }
  return normalized
}

function normalizeNote(value: string): string | null {
  const normalized = value.trim()
  if (!normalized) return null
  if (normalized.length > NOTE_MAX) throw new Error('关系备注不能超过 5000 个字符')
  return normalized
}

function semanticDraft(draft: PersonRelationshipDraft): {
  kind: PersonRelationshipKind
  customLabel: string | null
  note: string | null
} {
  const kind = normalizeKind(draft.relationshipKind)
  return {
    kind,
    customLabel: kind === 'OTHER' ? normalizeOtherLabel(draft.customLabel) : null,
    note: normalizeNote(draft.note),
  }
}

export function relationshipDraftFromProjection(
  row: PersonRelationshipProjection,
): PersonRelationshipDraft {
  return {
    relationshipKind: row.relationship_kind,
    customLabel: row.custom_label || '',
    note: row.note || '',
  }
}

export function buildPersonRelationshipCreatePayload(
  currentPersonId: string,
  otherPersonId: string,
  draft: PersonRelationshipDraft,
): PersonRelationshipCreatePayload {
  if (!isUuid(currentPersonId) || !isUuid(otherPersonId)) throw new Error('人物参数无效')
  if (currentPersonId.toLowerCase() === otherPersonId.toLowerCase()) {
    throw new Error('不能把人物与自己建立关系')
  }
  const next = semanticDraft(draft)
  const payload: PersonRelationshipCreatePayload = {
    person_a_id: currentPersonId,
    person_b_id: otherPersonId,
    relationship_kind: next.kind,
  }
  if (next.kind === 'OTHER' && next.customLabel !== null) {
    payload.custom_label = next.customLabel
  }
  if (next.note !== null) payload.note = next.note
  return payload
}

export function buildPersonRelationshipPatchPayload(
  base: PersonRelationshipProjection,
  draft: PersonRelationshipDraft,
): PersonRelationshipPatchPayload | null {
  const next = semanticDraft(draft)
  const payload: PersonRelationshipPatchPayload = {
    expected_revision: base.revision,
  }

  if (next.kind !== base.relationship_kind) {
    payload.relationship_kind = next.kind
    if (next.kind === 'OTHER' && next.customLabel !== null) {
      payload.custom_label = next.customLabel
    }
    // OTHER -> non-OTHER deliberately omits custom_label. Backend semantics clear it.
  } else if (next.kind === 'OTHER' && next.customLabel !== base.custom_label) {
    payload.custom_label = next.customLabel || undefined
  }

  if (next.note !== base.note) payload.note = next.note

  return Object.keys(payload).length === 1 ? null : payload
}

function sameRelationshipShape(
  left: { kind: PersonRelationshipKind; customLabel: string | null },
  right: { kind: PersonRelationshipKind; customLabel: string | null },
): boolean {
  return left.kind === right.kind && left.customLabel === right.customLabel
}

export function relationshipConflictFieldLabel(
  field: PersonRelationshipConflictField,
): string {
  return field === 'relationship' ? '关系类型 / 自定义关系' : '关系备注'
}

export function rebasePersonRelationshipDraft(
  editBase: PersonRelationshipProjection,
  userDraft: PersonRelationshipDraft,
  latest: PersonRelationshipProjection,
): PersonRelationshipConflictRebase {
  if (
    editBase.relationship_id.toLowerCase() !== latest.relationship_id.toLowerCase()
    || editBase.other_person.id.toLowerCase() !== latest.other_person.id.toLowerCase()
  ) {
    throw new Error('人物关系数据异常，请刷新后重试')
  }

  const user = semanticDraft(userDraft)
  const baseShape = {
    kind: editBase.relationship_kind,
    customLabel: editBase.custom_label,
  }
  const userShape = { kind: user.kind, customLabel: user.customLabel }
  const latestShape = {
    kind: latest.relationship_kind,
    customLabel: latest.custom_label,
  }

  const userShapeChanged = !sameRelationshipShape(userShape, baseShape)
  const serverShapeChanged = !sameRelationshipShape(latestShape, baseShape)
  const shapeConflict = (
    userShapeChanged
    && serverShapeChanged
    && !sameRelationshipShape(userShape, latestShape)
  )

  const userNoteChanged = user.note !== editBase.note
  const serverNoteChanged = latest.note !== editBase.note
  const noteConflict = (
    userNoteChanged
    && serverNoteChanged
    && user.note !== latest.note
  )

  const conflicts: PersonRelationshipConflictField[] = []
  if (shapeConflict) conflicts.push('relationship')
  if (noteConflict) conflicts.push('note')

  const keepUserShape = userShapeChanged ? userShape : latestShape
  const keepServerShape = shapeConflict ? latestShape : keepUserShape
  const keepUserNote = userNoteChanged ? user.note : latest.note
  const keepServerNote = noteConflict ? latest.note : keepUserNote

  return {
    keepUserDraft: {
      relationshipKind: keepUserShape.kind,
      customLabel: keepUserShape.customLabel || '',
      note: keepUserNote || '',
    },
    keepServerDraft: {
      relationshipKind: keepServerShape.kind,
      customLabel: keepServerShape.customLabel || '',
      note: keepServerNote || '',
    },
    conflicts,
  }
}

export function candidatePeopleForRelationship(
  people: readonly PersonRead[],
  currentPersonId: string,
): PersonRead[] {
  if (!isUuid(currentPersonId)) throw new Error('人物参数无效')
  return people.filter((person) => person.id.toLowerCase() !== currentPersonId.toLowerCase())
}

export function buildPersonRelationshipsPath(personId: string, limit = 100): string {
  if (!isUuid(personId)) throw new Error('人物参数无效')
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('人物关系列表数量必须在 1 到 100 之间')
  }
  return '/people/' + encodeURIComponent(personId) + '/relationships?limit=' + limit
}

export function buildPersonRelationshipPath(relationshipId: string): string {
  if (!isUuid(relationshipId)) throw new Error('人物关系参数无效')
  return '/people/relationships/' + encodeURIComponent(relationshipId)
}

export function relationshipKindLabel(kind: PersonRelationshipKind): string {
  const labels: Record<PersonRelationshipKind, string> = {
    FAMILY: '家人',
    FRIEND: '朋友',
    COLLEAGUE: '同事',
    CLASSMATE: '同学',
    OTHER: '其他',
  }
  return labels[kind]
}

export function personRelationshipErrorMessage(code: string | null): string | null {
  switch (code) {
    case 'PERSON_NOT_FOUND':
    case 'PERSON_RELATIONSHIP_NOT_FOUND':
      return '这条人物关系当前不可用，请刷新后重试'
    case 'PERSON_RELATIONSHIP_SELF_EDGE':
      return '不能把人物与自己建立关系'
    case 'PERSON_RELATIONSHIP_CONFLICT':
      return '这两个人之间已经存在不同的人物关系，请刷新后重新操作'
    case 'PERSON_RELATIONSHIP_REVISION_CONFLICT':
      return '人物关系已经变化，请核对最新内容后重新保存'
    case 'PERSON_RELATIONSHIP_CUSTOM_LABEL_REQUIRED':
      return '“其他”关系必须填写自定义关系'
    case 'PERSON_RELATIONSHIP_CUSTOM_LABEL_ONLY_FOR_OTHER':
      return '只有“其他”关系可以填写自定义关系'
    default:
      return null
  }
}

export class PersonRelationshipUiAuthority {
  private generation = 0

  invalidate(): void {
    this.generation += 1
  }

  capture(input: {
    owner: string | null
    sessionEpoch: number
    personId: string
    action: string
    relationshipId?: string | null
    revision?: number | null
    otherPersonId?: string | null
  }): PersonRelationshipAuthoritySnapshot {
    if (!input.owner || !isUuid(input.owner)) throw new Error('请先登录')
    if (!Number.isSafeInteger(input.sessionEpoch) || input.sessionEpoch < 0) {
      throw new Error('登录状态异常，请重新登录')
    }
    if (!isUuid(input.personId)) throw new Error('人物参数无效')
    if (!input.action.trim()) throw new Error('人物关系操作无效')

    const relationshipId = input.relationshipId ?? null
    const revision = input.revision ?? null
    const otherPersonId = input.otherPersonId ?? null
    if (relationshipId !== null && !isUuid(relationshipId)) throw new Error('人物关系参数无效')
    if (otherPersonId !== null && !isUuid(otherPersonId)) throw new Error('关联人物参数无效')
    if (revision !== null && (!Number.isSafeInteger(revision) || revision < 0)) {
      throw new Error('关系版本无效，请刷新')
    }

    return {
      generation: this.generation,
      owner: input.owner,
      sessionEpoch: input.sessionEpoch,
      personId: input.personId,
      action: input.action,
      relationshipId,
      revision,
      otherPersonId,
    }
  }

  isCurrent(
    snapshot: PersonRelationshipAuthoritySnapshot,
    input: {
      owner: string | null
      sessionEpoch: number
      personId: string
      action: string
      relationshipId?: string | null
      revision?: number | null
      otherPersonId?: string | null
    },
  ): boolean {
    return (
      snapshot.generation === this.generation
      && snapshot.owner === input.owner
      && snapshot.sessionEpoch === input.sessionEpoch
      && snapshot.personId === input.personId
      && snapshot.action === input.action
      && snapshot.relationshipId === (input.relationshipId ?? null)
      && snapshot.revision === (input.revision ?? null)
      && snapshot.otherPersonId === (input.otherPersonId ?? null)
    )
  }
}
