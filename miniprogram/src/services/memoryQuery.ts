import {
  parseTodayFootprintResponse,
  type TodayFootprintResponse,
} from './todayFootprint'

export type Evidence = {
  kind: string
  id: string
  source_type: string
  memory_source_id: string
  occurred_at: string
  excerpt: string
  confidence: number
  provenance?: 'ORIGINAL_SOURCE' | 'USER_EDIT'
  // Media identity is server-issued via MediaEvidenceLink only.
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
  day_footprint?: TodayFootprintResponse & { empty: boolean }
}

export function parseMemoryQueryResult(raw: unknown): MemoryQueryResult {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    throw new Error('服务端查询响应格式不正确')
  }
  const value = raw as Record<string, unknown>
  const answer = value.answer
  const canAnswer = value.can_answer
  const certainty = value.certainty
  const reason = value.reason
  const intent = value.intent
  const evidence = value.evidence
  const memoryIds = value.memory_ids
  const dayFootprintRaw = value.day_footprint

  if (
    !(answer === null || typeof answer === 'string')
    || typeof canAnswer !== 'boolean'
    || typeof certainty !== 'string'
    || !(reason === undefined || reason === null || typeof reason === 'string')
    || typeof intent !== 'string'
    || !Array.isArray(evidence)
    || !Array.isArray(memoryIds)
  ) {
    throw new Error('服务端查询响应格式不正确')
  }

  const parsedEvidence: Evidence[] = evidence.map((item) => {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) {
      throw new Error('服务端查询响应格式不正确')
    }
    const row = item as Record<string, unknown>
    if (
      typeof row.kind !== 'string'
      || typeof row.id !== 'string'
      || typeof row.source_type !== 'string'
      || typeof row.memory_source_id !== 'string'
      || typeof row.occurred_at !== 'string'
      || typeof row.excerpt !== 'string'
      || typeof row.confidence !== 'number'
      || !Number.isFinite(row.confidence)
      || !(row.provenance === undefined || row.provenance === 'ORIGINAL_SOURCE' || row.provenance === 'USER_EDIT')
      || !(row.media_id === undefined || row.media_id === null || typeof row.media_id === 'string')
    ) {
      throw new Error('服务端查询响应格式不正确')
    }
    return {
      kind: row.kind,
      id: row.id,
      source_type: row.source_type,
      memory_source_id: row.memory_source_id,
      occurred_at: row.occurred_at,
      excerpt: row.excerpt,
      confidence: row.confidence,
      ...(row.provenance ? { provenance: row.provenance as 'ORIGINAL_SOURCE' | 'USER_EDIT' } : {}),
      ...(row.media_id !== undefined ? { media_id: row.media_id as string | null } : {}),
    }
  })

  const parsedMemoryIds = memoryIds.map((item) => {
    if (typeof item !== 'string' || !item.trim()) {
      throw new Error('服务端查询响应格式不正确')
    }
    return item
  })

  let parsedDayFootprint: (TodayFootprintResponse & { empty: boolean }) | undefined
  if (dayFootprintRaw !== undefined && dayFootprintRaw !== null) {
    if (
      typeof dayFootprintRaw !== 'object'
      || Array.isArray(dayFootprintRaw)
    ) {
      throw new Error('服务端查询响应格式不正确')
    }
    const parsedFootprint = parseTodayFootprintResponse(dayFootprintRaw)
    const empty = (dayFootprintRaw as Record<string, unknown>).empty
    if (
      typeof empty !== 'boolean'
      || empty !== (parsedFootprint.visits.length === 0)
    ) {
      throw new Error('服务端查询响应格式不正确')
    }
    parsedDayFootprint = {
      ...parsedFootprint,
      empty,
    }
  }

  const parsed: MemoryQueryResult = {
    answer,
    can_answer: canAnswer,
    certainty,
    ...(reason !== undefined ? { reason: reason as string | null } : {}),
    intent,
    evidence: parsedEvidence,
    memory_ids: parsedMemoryIds,
    ...(parsedDayFootprint ? { day_footprint: parsedDayFootprint } : {}),
  }

  const hasStructuredFootprint = Boolean(
    parsedDayFootprint && parsedDayFootprint.visits.length > 0,
  )
  const canonicalEvidenceAnswer = (
    canAnswer === true
    && typeof answer === 'string'
    && answer.trim().length > 0
    && (certainty === 'confirmed' || certainty === 'evidence')
    && parsedEvidence.length > 0
    && parsedMemoryIds.length > 0
  )
  const canonicalStructuredAnswer = (
    canAnswer === true
    && typeof answer === 'string'
    && answer.trim().length > 0
    && (certainty === 'confirmed' || certainty === 'evidence')
    && hasStructuredFootprint
  )
  const structuredNoEvidenceExplanation = (
    Boolean(parsedDayFootprint)
    || reason === 'INVALID_DATE'
    || reason === 'FUTURE_DATE'
  )
  const canonicalNoEvidence = (
    canAnswer === false
    && (
      answer === null
      || (
        structuredNoEvidenceExplanation
        && typeof answer === 'string'
        && answer.trim().length > 0
      )
    )
    && certainty === 'unknown'
    && parsedEvidence.length === 0
    && parsedMemoryIds.length === 0
    && (!parsedDayFootprint || parsedDayFootprint.visits.length === 0)
  )
  if (!canonicalEvidenceAnswer && !canonicalStructuredAnswer && !canonicalNoEvidence) {
    throw new Error('服务端查询响应格式不正确')
  }
  return parsed
}
