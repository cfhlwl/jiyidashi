export const AI_PRESENTATION_STATE = {
  EXPLICIT: 'EXPLICIT',
  INFERRED: 'INFERRED',
  UNCERTAIN: 'UNCERTAIN',
  UNAVAILABLE: 'UNAVAILABLE',
} as const

export type AiPresentationState =
  (typeof AI_PRESENTATION_STATE)[keyof typeof AI_PRESENTATION_STATE]

export type AiPresentation = {
  state: AiPresentationState
  label: string
  detail: string
  tone: 'explicit' | 'inferred' | 'uncertain' | 'unavailable'
}

const PRESENTATION: Record<AiPresentationState, AiPresentation> = {
  EXPLICIT: {
    state: 'EXPLICIT',
    label: '明确记录',
    detail: '这是明确保存的原始记录，不是 AI 生成的结论。',
    tone: 'explicit',
  },
  INFERRED: {
    state: 'INFERRED',
    label: 'AI 推断（有证据支持）',
    detail: '这是 AI 根据下方证据生成的回答，不等同于原始事实记录。',
    tone: 'inferred',
  },
  UNCERTAIN: {
    state: 'UNCERTAIN',
    label: 'AI 推断（证据不足）',
    detail: '当前证据不足以形成完整结论。',
    tone: 'uncertain',
  },
  UNAVAILABLE: {
    state: 'UNAVAILABLE',
    label: '暂不可用',
    detail: '当前没有可安全展示的 AI 结论。',
    tone: 'unavailable',
  },
}

export function presentationForState(state: AiPresentationState): AiPresentation {
  return PRESENTATION[state]
}

export function explicitRecordPresentation(): AiPresentation {
  return PRESENTATION.EXPLICIT
}

export function queryAiPresentation(input: {
  can_answer: boolean
  answer: string | null
  certainty: string
  evidence: readonly unknown[]
  memory_ids: readonly string[]
}): AiPresentation {
  if (
    input.can_answer === true
    && typeof input.answer === 'string'
    && input.answer.trim().length > 0
    && input.certainty === 'evidence'
    && input.evidence.length > 0
    && input.memory_ids.length > 0
  ) {
    return PRESENTATION.INFERRED
  }
  if (
    input.can_answer === false
    && input.answer === null
    && input.certainty === 'unknown'
    && input.evidence.length === 0
    && input.memory_ids.length === 0
  ) {
    return PRESENTATION.UNAVAILABLE
  }
  return PRESENTATION.UNAVAILABLE
}

export function isCanonicalQueryTrustShape(input: {
  can_answer: boolean
  answer: string | null
  certainty: string
  evidence: readonly unknown[]
  memory_ids: readonly string[]
}): boolean {
  const state = queryAiPresentation(input).state
  if (state === 'INFERRED') return true
  return (
    state === 'UNAVAILABLE'
    && input.can_answer === false
    && input.answer === null
    && input.certainty === 'unknown'
    && input.evidence.length === 0
    && input.memory_ids.length === 0
  )
}

const READY_SUMMARY = new Set([
  'DAILY_SUMMARY_READY',
  'MONTHLY_SUMMARY_READY',
  'ANNUAL_SUMMARY_READY',
])
const UNAVAILABLE_SUMMARY = new Set([
  'NO_SUMMARIZABLE_EVIDENCE',
  'PROVIDER_FAILED',
  'MALFORMED_PROVIDER_OUTPUT',
  'INVALID_CITATION',
  'DATA_CHANGED_DURING_GENERATION',
])

export function summaryAiPresentation(status: string): AiPresentation {
  if (READY_SUMMARY.has(status)) return PRESENTATION.INFERRED
  if (status === 'SUMMARY_INCOMPLETE') return PRESENTATION.UNCERTAIN
  if (UNAVAILABLE_SUMMARY.has(status)) return PRESENTATION.UNAVAILABLE
  return PRESENTATION.UNAVAILABLE
}

export function isKnownSummaryPresentationStatus(status: string): boolean {
  return READY_SUMMARY.has(status)
    || status === 'SUMMARY_INCOMPLETE'
    || UNAVAILABLE_SUMMARY.has(status)
}
