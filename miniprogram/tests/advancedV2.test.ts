import assert from 'node:assert/strict'
import test from 'node:test'

import {
  AdvancedV2Authority,
  AdvancedV2SingleFlight,
  annualMemoirPhotosPath,
  annualNarrativePresentation,
  lifeHistoryPath,
  lifeMemoirPresentation,
  parseAnnualMemoir,
  parseAnnualMemoirPhotos,
  parseKnownDuration,
  parseLifeEvent,
  parseLifeEventEvidenceList,
  parseLifeHistory,
  parseLifeMemoirChapter,
  parseLifeMemoirStageIndex,
  parseLifeStage,
  parseLongTermReasoning,
  parseVerifiedMediaDownload,
  reasoningPresentation,
} from '../src/services/advancedV2'

const EVENT_ID = '11111111-1111-4111-8111-111111111111'
const STAGE_ID = '22222222-2222-4222-8222-222222222222'
const MEMORY_ID = '33333333-3333-4333-8333-333333333333'
const SOURCE_ID = '44444444-4444-4444-8444-444444444444'
const LINK_ID = '55555555-5555-4555-8555-555555555555'
const MEDIA_ID = '66666666-6666-4666-8666-666666666666'
const VISIT_ID = '77777777-7777-4777-8777-777777777777'
const PERSON_ID = '88888888-8888-4888-8888-888888888888'

const eventFixture = () => ({
  id: EVENT_ID,
  event_kind: 'WORK',
  title: '加入新团队',
  custom_label: null,
  note: '开始新的项目',
  started_at: '2025-03-01T09:00:00+08:00',
  ended_at: null,
  place_id: null,
  revision: 2,
  created_at: '2025-03-01T09:00:00+08:00',
  updated_at: '2025-03-02T09:00:00+08:00',
})

const stageFixture = () => ({
  id: STAGE_ID,
  stage_kind: 'WORK',
  title: '产品创业阶段',
  custom_label: null,
  note: null,
  started_at: '2025-01-01T00:00:00+08:00',
  ended_at: null,
  revision: 1,
  created_at: '2025-01-01T00:00:00+08:00',
  updated_at: '2025-01-01T00:00:00+08:00',
})

const historyEvent = () => ({
  kind: 'LIFE_EVENT',
  occurred_at: '2025-03-01T09:00:00+08:00',
  title: '加入新团队',
  custom_label: null,
  life_event_id: EVENT_ID,
  event_kind: 'WORK',
  event_ended_at: null,
  place_id: null,
  life_stage_id: null,
  stage_kind: null,
})

test('LifeEvent parser preserves canonical open-ended values and rejects enum drift', () => {
  const parsed = parseLifeEvent(eventFixture(), EVENT_ID)
  assert.equal(parsed.ended_at, null)
  assert.equal(parsed.event_kind, 'WORK')

  assert.throws(() => parseLifeEvent({ ...eventFixture(), event_kind: 'FUTURE_KIND' }))
  assert.throws(() => parseLifeEvent({ ...eventFixture(), started_at: '2025-03-01T09:00:00' }))
  assert.throws(() => parseLifeEvent({
    ...eventFixture(),
    event_kind: 'OTHER',
    custom_label: null,
  }))
})

test('LifeEvent evidence is strict explicit source identity', () => {
  const rows = parseLifeEventEvidenceList([{
    link_id: LINK_ID,
    memory_id: MEMORY_ID,
    memory_type: 'NOTE',
    title: '会议记录',
    content: '当时加入了团队',
    occurred_at: '2025-03-01T09:00:00+08:00',
    source_type: 'USER_TEXT',
    created_at: '2025-03-02T09:00:00+08:00',
  }])
  assert.equal(rows[0].source_type, 'USER_TEXT')
  assert.throws(() => parseLifeEventEvidenceList([{
    ...rows[0],
    source_type: 'FUTURE_SOURCE',
  }]))
})

test('LifeStage parser keeps open-ended and overlapping-compatible values untouched', () => {
  const parsed = parseLifeStage(stageFixture(), STAGE_ID)
  assert.equal(parsed.ended_at, null)
  assert.equal(parsed.started_at, stageFixture().started_at)
  assert.throws(() => parseLifeStage({ ...stageFixture(), stage_kind: 'UNKNOWN_STAGE' }))
})

test('Known Duration is deterministic and never guesses missing MET evidence', () => {
  const known = parseKnownDuration({
    status: 'KNOWN_SINCE_MET',
    person_id: PERSON_ID,
    display_name: '老张',
    as_of: '2026-09-29T00:00:00+08:00',
    at_least_since_at: '2020-01-01T00:00:00+08:00',
    elapsed_days: 2463,
    earliest_related_at: '2019-12-01T00:00:00+08:00',
    evidence: {
      person_memory_link_id: LINK_ID,
      memory_id: MEMORY_ID,
      memory_source_id: SOURCE_ID,
      relation_kind: 'MET',
      trust_state: 'EVIDENCE_SUPPORTED',
      occurred_at: '2020-01-01T00:00:00+08:00',
    },
  }, PERSON_ID)
  assert.equal(known.elapsed_days, 2463)

  const unavailable = parseKnownDuration({
    status: 'NO_TRUSTED_EVIDENCE',
    person_id: PERSON_ID,
    display_name: '老张',
    as_of: '2026-09-29T00:00:00+08:00',
    at_least_since_at: null,
    elapsed_days: null,
    earliest_related_at: null,
    evidence: null,
  }, PERSON_ID)
  assert.equal(unavailable.elapsed_days, null)

  assert.throws(() => parseKnownDuration({
    ...unavailable,
    elapsed_days: 100,
  }, PERSON_ID))
})

test('Long-term Reasoning applies SEC-013 only to real AI statuses', () => {
  const answered = parseLongTermReasoning({
    status: 'ANSWERED',
    answer: '这个阶段持续围绕产品开发。',
    citations: [{
      slot: 'stage',
      kind: 'LIFE_STAGE',
      life_stage_id: STAGE_ID,
      life_event_id: null,
      memory_id: null,
      memory_source_id: null,
      memory_trust_state: null,
    }],
    provider_error_code: null,
    ai_provenance: {
      gateway_request_id: 'gw-answered-1',
      purpose: 'LONG_TERM_REASONING',
      provider_request_id: 'provider-1',
      provider: 'test-provider',
      model: 'test-model',
    },
  })
  assert.equal(reasoningPresentation(answered.status).state, 'INFERRED')

  const incomplete = parseLongTermReasoning({
    status: 'EVIDENCE_INCOMPLETE',
    answer: null,
    citations: [],
    provider_error_code: null,
    ai_provenance: null,
  })
  assert.equal(reasoningPresentation(incomplete.status).state, 'UNCERTAIN')

  for (const status of [
    'NO_ANSWERABLE_EVIDENCE',
    'PROVIDER_FAILED',
    'MALFORMED_PROVIDER_OUTPUT',
    'INVALID_CITATION',
    'EVIDENCE_CHANGED_DURING_GENERATION',
  ] as const) {
    const result = parseLongTermReasoning({
      status,
      answer: null,
      citations: [],
      provider_error_code: status === 'PROVIDER_FAILED' ? 'AI_PROVIDER_FAILED' : null,
      ai_provenance: null,
    })
    assert.equal(reasoningPresentation(result.status).state, 'UNAVAILABLE')
  }

  assert.throws(() => parseLongTermReasoning({
    status: 'FUTURE_STATUS',
    answer: '不应展示',
    citations: [],
    provider_error_code: null,
    ai_provenance: null,
  }))
  assert.throws(() => parseLongTermReasoning({
    status: 'ANSWERED',
    answer: '无引用的生成文本',
    citations: [],
    provider_error_code: null,
    ai_provenance: {
      gateway_request_id: 'gw-invalid',
      purpose: 'LONG_TERM_REASONING',
      provider_request_id: null,
      provider: 'test-provider',
      model: 'test-model',
    },
  }))
  assert.throws(() => parseLongTermReasoning({
    status: 'PROVIDER_FAILED',
    answer: null,
    citations: [],
    provider_error_code: null,
    ai_provenance: null,
  }))
  assert.throws(() => parseLongTermReasoning({
    status: 'ANSWERED',
    answer: '有引用但 provenance malformed',
    citations: [{
      slot: 'stage',
      kind: 'LIFE_STAGE',
      life_stage_id: STAGE_ID,
      life_event_id: null,
      memory_id: null,
      memory_source_id: null,
      memory_trust_state: null,
    }],
    provider_error_code: null,
    ai_provenance: { provider: 'x' },
  }))
})

test('Life History preserves opaque cursor and server-owned range', () => {
  const page = parseLifeHistory({
    timezone: 'Asia/Shanghai',
    start_year: 2024,
    end_year: 2025,
    as_of: '2026-09-29T00:00:00+08:00',
    items: [historyEvent()],
    next_cursor: 'opaque:+/=cursor',
  }, { startYear: 2024, endYear: 2025 })

  assert.equal(page.next_cursor, 'opaque:+/=cursor')
  assert.match(lifeHistoryPath(2024, 2025, 50, page.next_cursor), /cursor=opaque%3A%2B%2F%3Dcursor/)
  assert.throws(() => parseLifeHistory({
    ...page,
    start_year: 2023,
  }, { startYear: 2024, endYear: 2025 }))
})

test('Annual Memoir labels only generated narrative while timeline/photo stay independent', () => {
  const memoir = parseAnnualMemoir({
    status: 'MEMOIR_READY',
    target_year: '2025',
    timezone: 'Asia/Shanghai',
    narrative_status: 'ANNUAL_SUMMARY_READY',
    narrative: '这一年有多条明确记录。',
    narrative_citations: [{
      slot: 'm1',
      kind: 'MEMORY',
      memory_id: MEMORY_ID,
      visit_id: null,
      trust_state: 'EVIDENCE_SUPPORTED',
    }],
    timeline_items: [historyEvent()],
    timeline_next_cursor: 'timeline-cursor',
    photo_items: [{
      memory_id: MEMORY_ID,
      media_id: MEDIA_ID,
      occurred_at: '2025-03-01T09:00:00+08:00',
      title: '团队合影',
      content_type: 'image/jpeg',
    }],
    photo_next_cursor: 'photo-cursor',
  }, '2025')

  assert.equal(annualNarrativePresentation(memoir.narrative_status).state, 'INFERRED')
  assert.equal(memoir.timeline_items[0].kind, 'LIFE_EVENT')
  assert.equal(memoir.photo_items[0].media_id, MEDIA_ID)

  const partial = parseAnnualMemoir({
    ...memoir,
    status: 'MEMOIR_PARTIAL',
    narrative_status: 'SUMMARY_INCOMPLETE',
    narrative: null,
    narrative_citations: [],
  }, '2025')
  assert.equal(annualNarrativePresentation(partial.narrative_status).state, 'UNCERTAIN')

  assert.throws(() => parseAnnualMemoir({
    ...memoir,
    narrative_status: 'PROVIDER_FAILED',
    narrative: '不应展示旧正文',
    narrative_citations: [],
  }, '2025'))
})

test('Annual photo continuation and signed preview stay canonical', () => {
  const page = parseAnnualMemoirPhotos({
    timezone: 'Asia/Shanghai',
    target_year: '2025',
    items: [{
      memory_id: MEMORY_ID,
      media_id: MEDIA_ID,
      occurred_at: '2025-03-01T09:00:00+08:00',
      title: null,
      content_type: 'image/jpeg',
    }],
    next_cursor: 'opaque-photo',
  }, '2025')
  assert.equal(page.items[0].media_id, MEDIA_ID)
  assert.match(annualMemoirPhotosPath('2025', 24, page.next_cursor), /memoirs\/annual\/2025\/photos/)

  const signed = parseVerifiedMediaDownload({
    media_id: MEDIA_ID,
    download: {
      method: 'GET',
      url: 'https://storage.example.test/signed',
      headers: { 'x-test': '1' },
      expires_at: '2026-09-29T01:00:00Z',
    },
  }, MEDIA_ID)
  assert.equal(signed.download.method, 'GET')
  assert.throws(() => parseVerifiedMediaDownload({
    ...signed,
    download: { ...signed.download, method: 'PUT' },
  }, MEDIA_ID))
})

test('Life Memoir stage index is deterministic and chapter AI state is typed', () => {
  const index = parseLifeMemoirStageIndex({
    items: [{
      life_stage_id: STAGE_ID,
      stage_kind: 'WORK',
      title: '产品创业阶段',
      custom_label: null,
      started_at: '2025-01-01T00:00:00+08:00',
      ended_at: null,
    }],
    next_cursor: 'opaque-stage',
  })
  assert.equal(index.items[0].life_stage_id, STAGE_ID)

  const ready = parseLifeMemoirChapter({
    status: 'CHAPTER_READY',
    life_stage_id: STAGE_ID,
    reasoning_status: 'ANSWERED',
    narrative: '这是基于阶段证据生成的章节。',
    citations: [{
      slot: 'stage',
      kind: 'LIFE_STAGE',
      life_stage_id: STAGE_ID,
      life_event_id: null,
      memory_id: null,
      memory_source_id: null,
      memory_trust_state: null,
    }],
  }, STAGE_ID)
  assert.equal(lifeMemoirPresentation(ready).state, 'INFERRED')

  const incomplete = parseLifeMemoirChapter({
    status: 'CHAPTER_PARTIAL',
    life_stage_id: STAGE_ID,
    reasoning_status: 'EVIDENCE_INCOMPLETE',
    narrative: null,
    citations: [],
  }, STAGE_ID)
  assert.equal(lifeMemoirPresentation(incomplete).state, 'UNCERTAIN')

  const failed = parseLifeMemoirChapter({
    status: 'CHAPTER_PARTIAL',
    life_stage_id: STAGE_ID,
    reasoning_status: 'PROVIDER_FAILED',
    narrative: null,
    citations: [],
  }, STAGE_ID)
  assert.equal(lifeMemoirPresentation(failed).state, 'UNAVAILABLE')
})

test('authority invalidates stale resource/range/session success and errors', () => {
  const authority = new AdvancedV2Authority()
  const first = authority.capture('owner-a', 1, 'history:2020:2025')
  assert.equal(authority.isCurrent(first, 'owner-a', 1, 'history:2020:2025'), true)

  const second = authority.capture('owner-a', 1, 'history:2021:2025')
  assert.equal(authority.isCurrent(first, 'owner-a', 1, 'history:2020:2025'), false)
  assert.equal(authority.isCurrent(second, 'owner-a', 1, 'history:2021:2025'), true)
  assert.equal(authority.isCurrent(second, 'owner-b', 2, 'history:2021:2025'), false)

  authority.invalidate()
  assert.equal(authority.isCurrent(second, 'owner-a', 1, 'history:2021:2025'), false)
})

test('mutating/generation single-flight rejects duplicate submit', () => {
  const gate = new AdvancedV2SingleFlight()
  assert.equal(gate.begin(), true)
  assert.equal(gate.begin(), false)
  assert.equal(gate.isPending(), true)
  gate.end()
  assert.equal(gate.begin(), true)
})
