import {
  presentationForState,
  summaryAiPresentation,
  type AiPresentation,
} from './aiPresentation'

export const LIFE_EVENT_KINDS = [
  'TRAVEL', 'MEDICAL', 'GATHERING', 'WORK', 'EDUCATION', 'FAMILY', 'OTHER',
] as const
export type LifeEventKind = (typeof LIFE_EVENT_KINDS)[number]

export const LIFE_STAGE_KINDS = [
  'WORK', 'EDUCATION', 'FAMILY', 'RESIDENCE', 'TRAVEL', 'OTHER',
] as const
export type LifeStageKind = (typeof LIFE_STAGE_KINDS)[number]

export type AnswerTrustState =
  | 'CONFIRMED'
  | 'EVIDENCE_SUPPORTED'
  | 'INFERENCE_ONLY'
  | 'NO_EVIDENCE'

export type LifeEventRead = {
  id: string
  event_kind: LifeEventKind
  title: string
  custom_label: string | null
  note: string | null
  started_at: string
  ended_at: string | null
  place_id: string | null
  revision: number
  created_at: string
  updated_at: string
}

export type LifeEventCreatePayload = {
  event_kind: LifeEventKind
  title: string
  custom_label?: string | null
  note?: string | null
  started_at: string
  ended_at?: string | null
  place_id?: string | null
}

export type LifeEventPatchPayload = Partial<LifeEventCreatePayload> & {
  expected_revision: number
}

export type LifeEventMemoryEvidence = {
  link_id: string
  memory_id: string
  memory_type: string
  title: string | null
  content: string
  occurred_at: string
  source_type: string
  created_at: string
}

export type LifeStageRead = {
  id: string
  stage_kind: LifeStageKind
  title: string
  custom_label: string | null
  note: string | null
  started_at: string
  ended_at: string | null
  revision: number
  created_at: string
  updated_at: string
}

export type LifeStageCreatePayload = {
  stage_kind: LifeStageKind
  title: string
  custom_label?: string | null
  note?: string | null
  started_at: string
  ended_at?: string | null
}

export type LifeStagePatchPayload = Partial<LifeStageCreatePayload> & {
  expected_revision: number
}

export type LifeStageEventEvidence = {
  link_id: string
  life_event_id: string
  event_kind: LifeEventKind
  title: string
  custom_label: string | null
  note: string | null
  started_at: string
  ended_at: string | null
  place_id: string | null
  created_at: string
}

export type PersonKnownDurationStatus =
  | 'KNOWN_SINCE_MET'
  | 'RELATED_EVIDENCE_ONLY'
  | 'NO_TRUSTED_EVIDENCE'
  | 'EVIDENCE_INCOMPLETE'

export type PersonKnownDurationEvidence = {
  person_memory_link_id: string
  memory_id: string
  memory_source_id: string
  relation_kind: 'RELATED' | 'MET'
  trust_state: AnswerTrustState
  occurred_at: string
}

export type PersonKnownDuration = {
  status: PersonKnownDurationStatus
  person_id: string
  display_name: string
  as_of: string
  at_least_since_at: string | null
  elapsed_days: number | null
  earliest_related_at: string | null
  evidence: PersonKnownDurationEvidence | null
}

export type LongTermReasoningStatus =
  | 'ANSWERED'
  | 'NO_ANSWERABLE_EVIDENCE'
  | 'EVIDENCE_INCOMPLETE'
  | 'PROVIDER_FAILED'
  | 'MALFORMED_PROVIDER_OUTPUT'
  | 'INVALID_CITATION'
  | 'EVIDENCE_CHANGED_DURING_GENERATION'

export type LongTermEvidenceKind = 'LIFE_STAGE' | 'LIFE_EVENT' | 'MEMORY'

export type LongTermCitation = {
  slot: string
  kind: LongTermEvidenceKind
  life_stage_id: string | null
  life_event_id: string | null
  memory_id: string | null
  memory_source_id: string | null
  memory_trust_state: AnswerTrustState | null
}

export type LongTermReasoningResult = {
  status: LongTermReasoningStatus
  answer: string | null
  citations: LongTermCitation[]
}

export type LifeHistoryItemKind =
  | 'LIFE_EVENT'
  | 'LIFE_STAGE_STARTED'
  | 'LIFE_STAGE_ENDED'

export type LifeHistoryItem = {
  kind: LifeHistoryItemKind
  occurred_at: string
  title: string
  custom_label: string | null
  life_event_id: string | null
  event_kind: LifeEventKind | null
  event_ended_at: string | null
  place_id: string | null
  life_stage_id: string | null
  stage_kind: LifeStageKind | null
}

export type LifeHistoryPage = {
  timezone: string
  start_year: number
  end_year: number
  as_of: string
  items: LifeHistoryItem[]
  next_cursor: string | null
}

export type AnnualSummaryStatus =
  | 'ANNUAL_SUMMARY_READY'
  | 'NO_SUMMARIZABLE_EVIDENCE'
  | 'SUMMARY_INCOMPLETE'
  | 'PROVIDER_FAILED'
  | 'MALFORMED_PROVIDER_OUTPUT'
  | 'INVALID_CITATION'
  | 'DATA_CHANGED_DURING_GENERATION'

export type AnnualMemoirStatus = 'MEMOIR_READY' | 'MEMOIR_PARTIAL' | 'MEMOIR_EMPTY'
export type AnnualMemoirCitation = {
  slot: string
  kind: 'MEMORY' | 'VISIT'
  memory_id: string | null
  visit_id: string | null
  trust_state: AnswerTrustState | null
}
export type AnnualMemoirPhoto = {
  memory_id: string
  media_id: string
  occurred_at: string
  title: string | null
  content_type: string
}
export type AnnualMemoirPhotoPage = {
  timezone: string
  target_year: string
  items: AnnualMemoirPhoto[]
  next_cursor: string | null
}
export type AnnualMemoir = {
  status: AnnualMemoirStatus
  target_year: string
  timezone: string
  narrative_status: AnnualSummaryStatus
  narrative: string | null
  narrative_citations: AnnualMemoirCitation[]
  timeline_items: LifeHistoryItem[]
  timeline_next_cursor: string | null
  photo_items: AnnualMemoirPhoto[]
  photo_next_cursor: string | null
}

export type LifeMemoirStageIndexItem = {
  life_stage_id: string
  stage_kind: LifeStageKind
  title: string
  custom_label: string | null
  started_at: string
  ended_at: string | null
}
export type LifeMemoirStageIndexPage = {
  items: LifeMemoirStageIndexItem[]
  next_cursor: string | null
}
export type LifeMemoirCitation = {
  slot: string
  kind: LongTermEvidenceKind
  life_stage_id: string
  life_event_id: string | null
  memory_id: string | null
  memory_source_id: string | null
  memory_trust_state: AnswerTrustState | null
}
export type LifeMemoirChapterStatus = 'CHAPTER_READY' | 'CHAPTER_EMPTY' | 'CHAPTER_PARTIAL'
export type LifeMemoirChapter = {
  status: LifeMemoirChapterStatus
  life_stage_id: string
  reasoning_status: LongTermReasoningStatus
  narrative: string | null
  citations: LifeMemoirCitation[]
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const AWARE_RE = /(Z|[+-][0-9]{2}:[0-9]{2})$/
const YEAR_RE = /^[0-9]{4}$/
const EVENT_KIND_SET = new Set<string>(LIFE_EVENT_KINDS)
const STAGE_KIND_SET = new Set<string>(LIFE_STAGE_KINDS)
const TRUST_SET = new Set<string>([
  'CONFIRMED', 'EVIDENCE_SUPPORTED', 'INFERENCE_ONLY', 'NO_EVIDENCE',
])
const MEMORY_TYPE_SET = new Set<string>([
  'NOTE', 'VOICE', 'PHOTO', 'PLACE', 'OBJECT_LOCATION', 'REMINDER', 'EVENT',
])
const SOURCE_TYPE_SET = new Set<string>([
  'USER_TEXT', 'USER_VOICE', 'USER_PHOTO', 'GPS', 'PHOTO_EXIF', 'SYSTEM_PLACE', 'AI_INFERENCE',
])
const REASONING_STATUS_SET = new Set<string>([
  'ANSWERED',
  'NO_ANSWERABLE_EVIDENCE',
  'EVIDENCE_INCOMPLETE',
  'PROVIDER_FAILED',
  'MALFORMED_PROVIDER_OUTPUT',
  'INVALID_CITATION',
  'EVIDENCE_CHANGED_DURING_GENERATION',
])
const ANNUAL_STATUS_SET = new Set<string>([
  'ANNUAL_SUMMARY_READY',
  'NO_SUMMARIZABLE_EVIDENCE',
  'SUMMARY_INCOMPLETE',
  'PROVIDER_FAILED',
  'MALFORMED_PROVIDER_OUTPUT',
  'INVALID_CITATION',
  'DATA_CHANGED_DURING_GENERATION',
])

function invalid(label: string): never {
  throw new Error(label + ' 数据异常')
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return invalid(label)
  return value as Record<string, unknown>
}
function text(value: unknown, label: string, max = 5000): string {
  if (typeof value !== 'string') return invalid(label)
  const next = value.trim()
  if (!next || next.length > max) return invalid(label)
  return next
}
function nullableText(value: unknown, label: string, max = 5000): string | null {
  if (value === null) return null
  return text(value, label, max)
}
function uuid(value: unknown, label: string): string {
  if (typeof value !== 'string' || !UUID_RE.test(value)) return invalid(label)
  return value
}
function nullableUuid(value: unknown, label: string): string | null {
  if (value === null) return null
  return uuid(value, label)
}
function aware(value: unknown, label: string): string {
  if (typeof value !== 'string' || !AWARE_RE.test(value) || !Number.isFinite(Date.parse(value))) {
    return invalid(label)
  }
  return value
}
function nullableAware(value: unknown, label: string): string | null {
  if (value === null) return null
  return aware(value, label)
}
function integer(value: unknown, label: string, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isInteger(value) || Number(value) < min || Number(value) > max) return invalid(label)
  return Number(value)
}
function nullableInteger(value: unknown, label: string, min = 0): number | null {
  if (value === null) return null
  return integer(value, label, min)
}
function cursor(value: unknown, label: string): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !value || value.length > 4096) return invalid(label)
  return value
}
function enumValue<T extends string>(value: unknown, allowed: Set<string>, label: string): T {
  if (typeof value !== 'string' || !allowed.has(value)) return invalid(label)
  return value as T
}
function trust(value: unknown, label: string): AnswerTrustState {
  return enumValue<AnswerTrustState>(value, TRUST_SET, label)
}
function nullableTrust(value: unknown, label: string): AnswerTrustState | null {
  if (value === null) return null
  return trust(value, label)
}
function list(value: unknown, label: string, max = 100): unknown[] {
  if (!Array.isArray(value) || value.length > max) return invalid(label)
  return value
}

export function parseLifeEvent(raw: unknown, expectedId?: string): LifeEventRead {
  const v = record(raw, '人生事件')
  const result: LifeEventRead = {
    id: uuid(v.id, '人生事件'),
    event_kind: enumValue<LifeEventKind>(v.event_kind, EVENT_KIND_SET, '人生事件'),
    title: text(v.title, '人生事件', 240),
    custom_label: nullableText(v.custom_label, '人生事件', 120),
    note: nullableText(v.note, '人生事件', 5000),
    started_at: aware(v.started_at, '人生事件'),
    ended_at: nullableAware(v.ended_at, '人生事件'),
    place_id: nullableUuid(v.place_id, '人生事件'),
    revision: integer(v.revision, '人生事件'),
    created_at: aware(v.created_at, '人生事件'),
    updated_at: aware(v.updated_at, '人生事件'),
  }
  if (expectedId && result.id !== expectedId) return invalid('人生事件')
  if (result.event_kind === 'OTHER' ? !result.custom_label : result.custom_label !== null) {
    return invalid('人生事件')
  }
  if (result.ended_at && Date.parse(result.ended_at) < Date.parse(result.started_at)) return invalid('人生事件')
  return result
}

export function parseLifeEventList(raw: unknown): LifeEventRead[] {
  return list(raw, '人生事件').map((item) => parseLifeEvent(item))
}

export function parseLifeEventEvidence(raw: unknown): LifeEventMemoryEvidence {
  const v = record(raw, '事件证据')
  return {
    link_id: uuid(v.link_id, '事件证据'),
    memory_id: uuid(v.memory_id, '事件证据'),
    memory_type: enumValue<string>(v.memory_type, MEMORY_TYPE_SET, '事件证据'),
    title: nullableText(v.title, '事件证据', 240),
    content: text(v.content, '事件证据', 20000),
    occurred_at: aware(v.occurred_at, '事件证据'),
    source_type: enumValue<string>(v.source_type, SOURCE_TYPE_SET, '事件证据'),
    created_at: aware(v.created_at, '事件证据'),
  }
}
export function parseLifeEventEvidenceList(raw: unknown): LifeEventMemoryEvidence[] {
  return list(raw, '事件证据').map(parseLifeEventEvidence)
}

export function parseLifeStage(raw: unknown, expectedId?: string): LifeStageRead {
  const v = record(raw, '人生阶段')
  const result: LifeStageRead = {
    id: uuid(v.id, '人生阶段'),
    stage_kind: enumValue<LifeStageKind>(v.stage_kind, STAGE_KIND_SET, '人生阶段'),
    title: text(v.title, '人生阶段', 240),
    custom_label: nullableText(v.custom_label, '人生阶段', 120),
    note: nullableText(v.note, '人生阶段', 5000),
    started_at: aware(v.started_at, '人生阶段'),
    ended_at: nullableAware(v.ended_at, '人生阶段'),
    revision: integer(v.revision, '人生阶段'),
    created_at: aware(v.created_at, '人生阶段'),
    updated_at: aware(v.updated_at, '人生阶段'),
  }
  if (expectedId && result.id !== expectedId) return invalid('人生阶段')
  if (result.stage_kind === 'OTHER' ? !result.custom_label : result.custom_label !== null) {
    return invalid('人生阶段')
  }
  if (result.ended_at && Date.parse(result.ended_at) < Date.parse(result.started_at)) return invalid('人生阶段')
  return result
}
export function parseLifeStageList(raw: unknown): LifeStageRead[] {
  return list(raw, '人生阶段').map((item) => parseLifeStage(item))
}
export function parseLifeStageEvidence(raw: unknown): LifeStageEventEvidence {
  const v = record(raw, '阶段事件')
  return {
    link_id: uuid(v.link_id, '阶段事件'),
    life_event_id: uuid(v.life_event_id, '阶段事件'),
    event_kind: enumValue<LifeEventKind>(v.event_kind, EVENT_KIND_SET, '阶段事件'),
    title: text(v.title, '阶段事件', 240),
    custom_label: nullableText(v.custom_label, '阶段事件', 120),
    note: nullableText(v.note, '阶段事件', 5000),
    started_at: aware(v.started_at, '阶段事件'),
    ended_at: nullableAware(v.ended_at, '阶段事件'),
    place_id: nullableUuid(v.place_id, '阶段事件'),
    created_at: aware(v.created_at, '阶段事件'),
  }
}
export function parseLifeStageEvidenceList(raw: unknown): LifeStageEventEvidence[] {
  return list(raw, '阶段事件').map(parseLifeStageEvidence)
}

export function parseKnownDuration(raw: unknown, expectedPersonId?: string): PersonKnownDuration {
  const v = record(raw, '认识时长')
  const status = enumValue<PersonKnownDurationStatus>(
    v.status,
    new Set(['KNOWN_SINCE_MET', 'RELATED_EVIDENCE_ONLY', 'NO_TRUSTED_EVIDENCE', 'EVIDENCE_INCOMPLETE']),
    '认识时长',
  )
  const evidence = v.evidence === null ? null : (() => {
    const e = record(v.evidence, '认识时长证据')
    return {
      person_memory_link_id: uuid(e.person_memory_link_id, '认识时长证据'),
      memory_id: uuid(e.memory_id, '认识时长证据'),
      memory_source_id: uuid(e.memory_source_id, '认识时长证据'),
      relation_kind: enumValue<'RELATED' | 'MET'>(e.relation_kind, new Set(['RELATED', 'MET']), '认识时长证据'),
      trust_state: trust(e.trust_state, '认识时长证据'),
      occurred_at: aware(e.occurred_at, '认识时长证据'),
    } satisfies PersonKnownDurationEvidence
  })()
  const result: PersonKnownDuration = {
    status,
    person_id: uuid(v.person_id, '认识时长'),
    display_name: text(v.display_name, '认识时长', 200),
    as_of: aware(v.as_of, '认识时长'),
    at_least_since_at: nullableAware(v.at_least_since_at, '认识时长'),
    elapsed_days: nullableInteger(v.elapsed_days, '认识时长'),
    earliest_related_at: nullableAware(v.earliest_related_at, '认识时长'),
    evidence,
  }
  if (expectedPersonId && result.person_id !== expectedPersonId) return invalid('认识时长')
  if (status === 'KNOWN_SINCE_MET') {
    if (!result.at_least_since_at || result.elapsed_days === null || !result.evidence || result.evidence.relation_kind !== 'MET') {
      return invalid('认识时长')
    }
  } else if (result.at_least_since_at !== null || result.elapsed_days !== null) {
    return invalid('认识时长')
  }
  return result
}

function parseLongTermCitation(raw: unknown, label = 'AI 引用'): LongTermCitation {
  const v = record(raw, label)
  const kind = enumValue<LongTermEvidenceKind>(v.kind, new Set(['LIFE_STAGE', 'LIFE_EVENT', 'MEMORY']), label)
  const citation: LongTermCitation = {
    slot: text(v.slot, label, 120),
    kind,
    life_stage_id: nullableUuid(v.life_stage_id, label),
    life_event_id: nullableUuid(v.life_event_id, label),
    memory_id: nullableUuid(v.memory_id, label),
    memory_source_id: nullableUuid(v.memory_source_id, label),
    memory_trust_state: nullableTrust(v.memory_trust_state, label),
  }
  if (kind === 'LIFE_STAGE' && !citation.life_stage_id) return invalid(label)
  if (kind === 'LIFE_EVENT' && !citation.life_event_id) return invalid(label)
  if (kind === 'MEMORY' && (!citation.memory_id || !citation.memory_source_id || !citation.memory_trust_state)) {
    return invalid(label)
  }
  return citation
}

export function parseLongTermReasoning(raw: unknown): LongTermReasoningResult {
  const v = record(raw, '长期推理')
  const status = enumValue<LongTermReasoningStatus>(v.status, REASONING_STATUS_SET, '长期推理')
  const citations = list(v.citations, '长期推理', 100).map((item) => parseLongTermCitation(item))
  const answer = v.answer === null ? null : text(v.answer, '长期推理', 20000)
  if (status === 'ANSWERED') {
    if (!answer || citations.length === 0) return invalid('长期推理')
  } else if (answer !== null) {
    return invalid('长期推理')
  }
  return { status, answer, citations }
}

export function reasoningPresentation(status: LongTermReasoningStatus): AiPresentation {
  if (status === 'ANSWERED') return presentationForState('INFERRED')
  if (status === 'EVIDENCE_INCOMPLETE') return presentationForState('UNCERTAIN')
  return presentationForState('UNAVAILABLE')
}

function parseHistoryItem(raw: unknown): LifeHistoryItem {
  const v = record(raw, '多年时间线')
  const kind = enumValue<LifeHistoryItemKind>(
    v.kind,
    new Set(['LIFE_EVENT', 'LIFE_STAGE_STARTED', 'LIFE_STAGE_ENDED']),
    '多年时间线',
  )
  const item: LifeHistoryItem = {
    kind,
    occurred_at: aware(v.occurred_at, '多年时间线'),
    title: text(v.title, '多年时间线', 240),
    custom_label: nullableText(v.custom_label, '多年时间线', 120),
    life_event_id: nullableUuid(v.life_event_id, '多年时间线'),
    event_kind: v.event_kind === null ? null : enumValue<LifeEventKind>(v.event_kind, EVENT_KIND_SET, '多年时间线'),
    event_ended_at: nullableAware(v.event_ended_at, '多年时间线'),
    place_id: nullableUuid(v.place_id, '多年时间线'),
    life_stage_id: nullableUuid(v.life_stage_id, '多年时间线'),
    stage_kind: v.stage_kind === null ? null : enumValue<LifeStageKind>(v.stage_kind, STAGE_KIND_SET, '多年时间线'),
  }
  if (kind === 'LIFE_EVENT') {
    if (!item.life_event_id || !item.event_kind || item.life_stage_id || item.stage_kind) return invalid('多年时间线')
  } else if (!item.life_stage_id || !item.stage_kind || item.life_event_id || item.event_kind) {
    return invalid('多年时间线')
  }
  return item
}

export function parseLifeHistory(raw: unknown, expected?: { startYear: number; endYear: number }): LifeHistoryPage {
  const v = record(raw, '多年时间线')
  const result: LifeHistoryPage = {
    timezone: text(v.timezone, '多年时间线', 120),
    start_year: integer(v.start_year, '多年时间线', 1, 9998),
    end_year: integer(v.end_year, '多年时间线', 1, 9998),
    as_of: aware(v.as_of, '多年时间线'),
    items: list(v.items, '多年时间线', 100).map(parseHistoryItem),
    next_cursor: cursor(v.next_cursor, '多年时间线'),
  }
  if (result.start_year > result.end_year) return invalid('多年时间线')
  if (expected && (result.start_year !== expected.startYear || result.end_year !== expected.endYear)) {
    return invalid('多年时间线')
  }
  return result
}

function strictYear(value: unknown, label: string): string {
  if (typeof value !== 'string' || !YEAR_RE.test(value)) return invalid(label)
  const year = Number(value)
  if (year < 1 || year > 9998) return invalid(label)
  return value
}
function parseAnnualCitation(raw: unknown): AnnualMemoirCitation {
  const v = record(raw, '年度回忆录引用')
  const kind = enumValue<'MEMORY' | 'VISIT'>(v.kind, new Set(['MEMORY', 'VISIT']), '年度回忆录引用')
  const result: AnnualMemoirCitation = {
    slot: text(v.slot, '年度回忆录引用', 120),
    kind,
    memory_id: nullableUuid(v.memory_id, '年度回忆录引用'),
    visit_id: nullableUuid(v.visit_id, '年度回忆录引用'),
    trust_state: nullableTrust(v.trust_state, '年度回忆录引用'),
  }
  if (kind === 'MEMORY' ? !result.memory_id : !result.visit_id) return invalid('年度回忆录引用')
  return result
}
function parseAnnualPhoto(raw: unknown): AnnualMemoirPhoto {
  const v = record(raw, '年度照片')
  return {
    memory_id: uuid(v.memory_id, '年度照片'),
    media_id: uuid(v.media_id, '年度照片'),
    occurred_at: aware(v.occurred_at, '年度照片'),
    title: nullableText(v.title, '年度照片', 240),
    content_type: text(v.content_type, '年度照片', 120),
  }
}
export function parseAnnualMemoir(raw: unknown, expectedYear?: string): AnnualMemoir {
  const v = record(raw, '年度回忆录')
  const narrativeStatus = enumValue<AnnualSummaryStatus>(v.narrative_status, ANNUAL_STATUS_SET, '年度回忆录')
  const narrative = v.narrative === null ? null : text(v.narrative, '年度回忆录', 30000)
  const narrativeCitations = list(v.narrative_citations, '年度回忆录', 100).map(parseAnnualCitation)
  if (narrativeStatus === 'ANNUAL_SUMMARY_READY') {
    if (!narrative || narrativeCitations.length === 0) return invalid('年度回忆录')
  } else if (narrative !== null) {
    return invalid('年度回忆录')
  }
  const result: AnnualMemoir = {
    status: enumValue<AnnualMemoirStatus>(v.status, new Set(['MEMOIR_READY', 'MEMOIR_PARTIAL', 'MEMOIR_EMPTY']), '年度回忆录'),
    target_year: strictYear(v.target_year, '年度回忆录'),
    timezone: text(v.timezone, '年度回忆录', 120),
    narrative_status: narrativeStatus,
    narrative,
    narrative_citations: narrativeCitations,
    timeline_items: list(v.timeline_items, '年度回忆录', 100).map(parseHistoryItem),
    timeline_next_cursor: cursor(v.timeline_next_cursor, '年度回忆录'),
    photo_items: list(v.photo_items, '年度回忆录', 50).map(parseAnnualPhoto),
    photo_next_cursor: cursor(v.photo_next_cursor, '年度回忆录'),
  }
  if (expectedYear && result.target_year !== expectedYear) return invalid('年度回忆录')
  if (result.status === 'MEMOIR_READY' && narrativeStatus !== 'ANNUAL_SUMMARY_READY') return invalid('年度回忆录')
  return result
}
export function annualNarrativePresentation(status: AnnualSummaryStatus): AiPresentation {
  return summaryAiPresentation(status)
}
export function parseAnnualMemoirPhotos(raw: unknown, expectedYear?: string): AnnualMemoirPhotoPage {
  const v = record(raw, '年度照片')
  const result: AnnualMemoirPhotoPage = {
    timezone: text(v.timezone, '年度照片', 120),
    target_year: strictYear(v.target_year, '年度照片'),
    items: list(v.items, '年度照片', 50).map(parseAnnualPhoto),
    next_cursor: cursor(v.next_cursor, '年度照片'),
  }
  if (expectedYear && result.target_year !== expectedYear) return invalid('年度照片')
  return result
}

export function parseLifeMemoirStageIndex(raw: unknown): LifeMemoirStageIndexPage {
  const v = record(raw, '人生回忆录阶段')
  return {
    items: list(v.items, '人生回忆录阶段', 100).map((item) => {
      const row = record(item, '人生回忆录阶段')
      return {
        life_stage_id: uuid(row.life_stage_id, '人生回忆录阶段'),
        stage_kind: enumValue<LifeStageKind>(row.stage_kind, STAGE_KIND_SET, '人生回忆录阶段'),
        title: text(row.title, '人生回忆录阶段', 240),
        custom_label: nullableText(row.custom_label, '人生回忆录阶段', 120),
        started_at: aware(row.started_at, '人生回忆录阶段'),
        ended_at: nullableAware(row.ended_at, '人生回忆录阶段'),
      }
    }),
    next_cursor: cursor(v.next_cursor, '人生回忆录阶段'),
  }
}
export function parseLifeMemoirChapter(raw: unknown, expectedStageId?: string): LifeMemoirChapter {
  const v = record(raw, '人生回忆录章节')
  const status = enumValue<LifeMemoirChapterStatus>(
    v.status,
    new Set(['CHAPTER_READY', 'CHAPTER_EMPTY', 'CHAPTER_PARTIAL']),
    '人生回忆录章节',
  )
  const reasoningStatus = enumValue<LongTermReasoningStatus>(v.reasoning_status, REASONING_STATUS_SET, '人生回忆录章节')
  const narrative = v.narrative === null ? null : text(v.narrative, '人生回忆录章节', 30000)
  const citations = list(v.citations, '人生回忆录章节', 100).map((item) => {
    const parsed = parseLongTermCitation(item, '人生回忆录引用')
    if (!parsed.life_stage_id) return invalid('人生回忆录引用')
    return parsed as LifeMemoirCitation
  })
  const result: LifeMemoirChapter = {
    status,
    life_stage_id: uuid(v.life_stage_id, '人生回忆录章节'),
    reasoning_status: reasoningStatus,
    narrative,
    citations,
  }
  if (expectedStageId && result.life_stage_id !== expectedStageId) return invalid('人生回忆录章节')
  if (reasoningStatus === 'ANSWERED') {
    if (status !== 'CHAPTER_READY' || !narrative || citations.length === 0) return invalid('人生回忆录章节')
  } else {
    if (narrative !== null || status === 'CHAPTER_READY') return invalid('人生回忆录章节')
    if (reasoningStatus === 'NO_ANSWERABLE_EVIDENCE' && status !== 'CHAPTER_EMPTY') return invalid('人生回忆录章节')
    if (reasoningStatus !== 'NO_ANSWERABLE_EVIDENCE' && status !== 'CHAPTER_PARTIAL') return invalid('人生回忆录章节')
  }
  return result
}
export function lifeMemoirPresentation(chapter: LifeMemoirChapter): AiPresentation {
  return reasoningPresentation(chapter.reasoning_status)
}

export function lifeEventsPath(limit = 50): string {
  const bounded = Math.max(1, Math.min(100, Math.trunc(limit)))
  return '/life-events?limit=' + bounded
}
export function lifeEventPath(id: string): string {
  return '/life-events/' + encodeURIComponent(id)
}
export function lifeEventMemoriesPath(id: string, limit = 50): string {
  const bounded = Math.max(1, Math.min(100, Math.trunc(limit)))
  return lifeEventPath(id) + '/memories?limit=' + bounded
}
export function lifeEventMemoryPath(eventId: string, memoryId: string): string {
  return lifeEventPath(eventId) + '/memories/' + encodeURIComponent(memoryId)
}
export function lifeStagesPath(limit = 50): string {
  const bounded = Math.max(1, Math.min(100, Math.trunc(limit)))
  return '/life-stages?limit=' + bounded
}
export function lifeStagePath(id: string): string {
  return '/life-stages/' + encodeURIComponent(id)
}
export function lifeStageEventsPath(id: string, limit = 50): string {
  const bounded = Math.max(1, Math.min(100, Math.trunc(limit)))
  return lifeStagePath(id) + '/events?limit=' + bounded
}
export function lifeStageEventPath(stageId: string, eventId: string): string {
  return lifeStagePath(stageId) + '/events/' + encodeURIComponent(eventId)
}
export function knownDurationPath(personId: string): string {
  return '/people/' + encodeURIComponent(personId) + '/known-duration'
}
export function lifeHistoryPath(startYear: number, endYear: number, limit = 50, nextCursor?: string | null): string {
  const bounded = Math.max(1, Math.min(100, Math.trunc(limit)))
  let path = '/life-history/timeline?start_year=' + startYear + '&end_year=' + endYear + '&limit=' + bounded
  if (nextCursor) path += '&cursor=' + encodeURIComponent(nextCursor)
  return path
}
export function annualMemoirPhotosPath(year: string, limit = 24, nextCursor?: string | null): string {
  const bounded = Math.max(1, Math.min(50, Math.trunc(limit)))
  let path = '/memoirs/annual/' + encodeURIComponent(year) + '/photos?limit=' + bounded
  if (nextCursor) path += '&cursor=' + encodeURIComponent(nextCursor)
  return path
}
export function lifeMemoirStagesPath(limit = 50, nextCursor?: string | null): string {
  const bounded = Math.max(1, Math.min(100, Math.trunc(limit)))
  let path = '/memoirs/life/stages?limit=' + bounded
  if (nextCursor) path += '&cursor=' + encodeURIComponent(nextCursor)
  return path
}

export type AdvancedV2AuthoritySnapshot = Readonly<{
  generation: number
  owner: string
  authEpoch: number
  identity: string
}>

export class AdvancedV2Authority {
  private generation = 0
  capture(owner: string, authEpoch: number, identity: string): AdvancedV2AuthoritySnapshot {
    this.generation += 1
    return { generation: this.generation, owner, authEpoch, identity }
  }
  invalidate(): void {
    this.generation += 1
  }
  isCurrent(
    snapshot: AdvancedV2AuthoritySnapshot,
    owner: string | null,
    authEpoch: number,
    identity: string,
  ): boolean {
    return snapshot.generation === this.generation
      && snapshot.owner === owner
      && snapshot.authEpoch === authEpoch
      && snapshot.identity === identity
  }
}

export class AdvancedV2SingleFlight {
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
