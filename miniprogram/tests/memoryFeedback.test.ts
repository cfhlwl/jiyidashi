import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  buildApiHeaders,
  buildCorrectionFeedback,
  createMemoryFeedbackOperation,
  executeMemoryFeedbackOperation,
  feedbackErrorMessage,
  isDisplayableEvidence,
  isRevisionConflictCode,
  MemoryFeedbackSingleFlightGate,
  MemoryReviewEpoch,
  parseMemoryFeedbackRead,
  parseMemoryRead,
  provenanceLabel,
  trustPresentation,
  type MemoryFeedbackPayload,
  type MemoryRead,
  type SafeRequestOptions,
} from '../src/services/memoryFeedback'

const MEMORY_ID = '11111111-1111-4111-8111-111111111111'
const USER_ID = '22222222-2222-4222-8222-222222222222'
const FEEDBACK_ID = '33333333-3333-4333-8333-333333333333'

function memoryBody(overrides: Record<string, unknown> = {}): unknown {
  return {
    id: MEMORY_ID,
    user_id: USER_ID,
    memory_type: 'NOTE',
    title: '原始标题',
    content: '原始正文',
    occurred_at: '2026-09-22T12:00:00Z',
    source_type: 'USER_TEXT',
    confidence: 1,
    place_id: null,
    latitude: null,
    longitude: null,
    is_confirmed: true,
    metadata_json: {},
    edit_revision: 3,
    edited_at: '2026-09-22T12:01:00Z',
    created_at: '2026-09-22T11:00:00Z',
    ...overrides,
  }
}

function parsedMemory(): MemoryRead {
  return parseMemoryRead(memoryBody(), MEMORY_ID)
}

test('MemoryRead parser captures edit_revision and fails closed on identity/revision/timestamp/content', () => {
  const parsed = parsedMemory()
  assert.equal(parsed.edit_revision, 3)
  assert.equal(parsed.content, '原始正文')
  assert.throws(() => parseMemoryRead(memoryBody({ id: USER_ID }), MEMORY_ID), /记忆数据异常/)
  assert.throws(() => parseMemoryRead(memoryBody({ edit_revision: -1 }), MEMORY_ID), /记忆数据异常/)
  assert.throws(() => parseMemoryRead(memoryBody({ edit_revision: 1.5 }), MEMORY_ID), /记忆数据异常/)
  assert.throws(() => parseMemoryRead(memoryBody({ created_at: '2026-09-22T11:00:00' }), MEMORY_ID), /记忆数据异常/)
  assert.throws(() => parseMemoryRead(memoryBody({ content: '   ' }), MEMORY_ID), /记忆数据异常/)
})

test('MemoryFeedbackRead parser is revision/action/identity bound', () => {
  const parsed = parseMemoryFeedbackRead({
    id: FEEDBACK_ID,
    user_id: USER_ID,
    memory_id: MEMORY_ID,
    memory_revision: 3,
    result_revision: 4,
    action: 'CORRECT',
    created_at: '2026-09-22T12:05:00Z',
  }, {
    memoryId: MEMORY_ID,
    action: 'CORRECT',
    memoryRevision: 3,
  })
  assert.equal(parsed.result_revision, 4)
  assert.throws(() => parseMemoryFeedbackRead({
    id: FEEDBACK_ID,
    user_id: USER_ID,
    memory_id: MEMORY_ID,
    memory_revision: 4,
    result_revision: null,
    action: 'CONFIRM',
    created_at: '2026-09-22T12:05:00Z',
  }, {
    memoryId: MEMORY_ID,
    action: 'CONFIRM',
    memoryRevision: 3,
  }), /记忆反馈数据异常/)
})

test('safe request headers allow Idempotency-Key but ignore arbitrary Authorization override', () => {
  const key = '44444444-4444-4444-8444-444444444444'
  const malicious = {
    idempotencyKey: key,
    Authorization: 'Bearer attacker',
    'Content-Type': 'text/plain',
  } as unknown as SafeRequestOptions

  const headers = buildApiHeaders('server-token', malicious)
  assert.equal(headers.Authorization, 'Bearer server-token')
  assert.equal(headers['Content-Type'], 'application/json')
  assert.equal(headers['Idempotency-Key'], key)
  assert.deepEqual(Object.keys(headers).sort(), ['Authorization', 'Content-Type', 'Idempotency-Key'])
})

test('same logical feedback retry reuses UUID and payload; a new action gets a new UUID', async () => {
  const payload: MemoryFeedbackPayload = { action: 'CONFIRM', expected_revision: 3 }
  const operation = createMemoryFeedbackOperation(MEMORY_ID, payload, () => 0.25)
  const calls: Array<{ key: string; payload: MemoryFeedbackPayload }> = []

  const sender = async (_memoryId: string, sentPayload: MemoryFeedbackPayload, key: string) => {
    calls.push({ key, payload: sentPayload })
    return 'ok'
  }

  await executeMemoryFeedbackOperation(operation, sender)
  await executeMemoryFeedbackOperation(operation, sender)

  assert.equal(calls.length, 2)
  assert.equal(calls[0].key, operation.idempotencyKey)
  assert.equal(calls[1].key, operation.idempotencyKey)
  assert.deepEqual(calls[0].payload, calls[1].payload)

  const nextOperation = createMemoryFeedbackOperation(
    MEMORY_ID,
    { action: 'DELETE', expected_revision: 3 },
    () => 0.75,
  )
  assert.notEqual(nextOperation.idempotencyKey, operation.idempotencyKey)
})

test('feedback single-flight gate rejects duplicate submit until active operation finishes', () => {
  const gate = new MemoryFeedbackSingleFlightGate()
  assert.equal(gate.begin(), true)
  assert.equal(gate.isPending(), true)
  assert.equal(gate.begin(), false)
  gate.end()
  assert.equal(gate.isPending(), false)
  assert.equal(gate.begin(), true)
})

test('review epoch invalidates stale Memory success and error after a new query starts', () => {
  const epoch = new MemoryReviewEpoch()
  const first = epoch.capture()
  assert.equal(epoch.isCurrent(first), true)

  epoch.invalidate()
  assert.equal(epoch.isCurrent(first), false)

  const second = epoch.capture()
  assert.equal(epoch.isCurrent(second), true)
})

test('CORRECT payload includes only explicitly changed fields and rejects empty/no-op content', () => {
  const memory = parsedMemory()
  assert.deepEqual(
    buildCorrectionFeedback(memory, '新标题', '原始正文'),
    { action: 'CORRECT', expected_revision: 3, title: '新标题' },
  )
  assert.deepEqual(
    buildCorrectionFeedback(memory, '原始标题', '新正文'),
    { action: 'CORRECT', expected_revision: 3, content: '新正文' },
  )
  assert.throws(() => buildCorrectionFeedback(memory, '原始标题', '   '), /记忆内容不能为空/)
  assert.throws(() => buildCorrectionFeedback(memory, '原始标题', '原始正文'), /内容没有变化/)
})

test('trust presentation maps only current public certainty values and fails future values neutral', () => {
  assert.deepEqual(
    trustPresentation({ can_answer: true, certainty: 'confirmed' }),
    {
      label: '有证据支持',
      detail: '这个答案来自当前公开证据链，可继续查看下面的来源。',
      tone: 'supported',
    },
  )
  assert.equal(trustPresentation({ can_answer: true, certainty: 'evidence' }).label, '有证据支持')
  assert.equal(trustPresentation({ can_answer: false, certainty: 'unknown' }).label, '没有足够证据')
  const future = trustPresentation({ can_answer: true, certainty: 'future-new-state' })
  assert.equal(future.tone, 'neutral')
  assert.doesNotMatch(future.label, /可信|已确认/)
})

test('AI inference is not displayable Evidence and provenance labels stay explicit', () => {
  assert.equal(isDisplayableEvidence('USER_TEXT'), true)
  assert.equal(isDisplayableEvidence('AI_INFERENCE'), false)
  assert.equal(provenanceLabel('ORIGINAL_SOURCE'), '原始来源')
  assert.equal(provenanceLabel('USER_EDIT'), '用户修正')
  assert.equal(provenanceLabel('FUTURE_VALUE'), null)
})

test('feedback error mapping uses exact current server codes and unknown detail stays hidden', () => {
  assert.equal(feedbackErrorMessage('MEMORY_NOT_FOUND'), '这条记忆已不存在，请重新查询')
  assert.equal(feedbackErrorMessage('MEMORY_FEEDBACK_REVISION_CONFLICT'), '记录已发生变化，请重新确认')
  assert.equal(
    feedbackErrorMessage('OBJECT_LOCATION_FEEDBACK_REQUIRES_STRUCTURED_FLOW'),
    '这类位置记忆需要在对应的位置功能中修改',
  )
  assert.equal(
    feedbackErrorMessage('IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST'),
    '本次操作状态不一致，请重新发起',
  )
  assert.equal(feedbackErrorMessage('SERVER_INTERNAL_SQL_DETAIL'), null)
  assert.equal(isRevisionConflictCode('MEMORY_FEEDBACK_REVISION_CONFLICT'), true)
  assert.equal(isRevisionConflictCode('MEMORY_NOT_FOUND'), false)
})

test('API transport exposes only typed safe request options and feedback parser path', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /options: SafeRequestOptions = \{\}/)
  assert.match(api, /header: buildApiHeaders\(token, options\)/)
  assert.match(api, /\{ idempotencyKey \}/)
  assert.match(api, /parseMemoryRead\(raw, memoryId\)/)
  assert.match(api, /parseMemoryFeedbackRead\(raw, \{/)
  assert.doesNotMatch(api, /options:\s*\{[^}]*Authorization/)
})

test('Query page uses revision-aware feedback instead of direct delete shortcut', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/query/index.tsx'), 'utf8')
  assert.doesNotMatch(page, /\bdeleteMemory\b/)
  assert.match(page, /await getMemory\(memoryId\)/)
  assert.match(page, /action: 'CONFIRM'/)
  assert.match(page, /action: 'DELETE'/)
  assert.match(page, /buildCorrectionFeedback\(base, correctionTitle, correctionContent\)/)
  assert.match(page, /await executeMemoryFeedbackOperation\(operation, submitMemoryFeedback\)/)
  assert.match(page, /记录已发生变化，请重新查看当前内容后再次选择操作/)
  assert.match(page, /operation\.payload\.action === 'CORRECT'/)
  assert.match(page, /setResult\(null\)/)
  assert.match(page, /result\.evidence\.filter\(\(evidence\) => isDisplayableEvidence\(evidence\.source_type\)\)/)
  assert.doesNotMatch(page, /可信状态：\{result\.certainty\}/)
  assert.match(page, /已记录：这条记忆正确/)
  assert.match(page, /const capturedReviewEpoch = reviewEpoch\.current\.capture\(\)/)
  assert.match(page, /if \(!reviewEpoch\.current\.isCurrent\(capturedReviewEpoch\)\) return null/)
  assert.match(page, /if \(queryBusyRef\.current \|\| feedbackGate\.current\.isPending\(\)\) return/)
  assert.match(page, /if \(queryBusyRef\.current\) return false/)
  assert.match(page, /reviewEpoch\.current\.invalidate\(\)[\s\S]*?setFeedbackBusy\(true\)/)
  assert.doesNotMatch(page, /已提升为可信记忆|已确认成为事实|AI 以后一定会相信/)
})
