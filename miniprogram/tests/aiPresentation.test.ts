import assert from 'node:assert/strict'
import test from 'node:test'
import {
  AI_PRESENTATION_STATE,
  explicitRecordPresentation,
  isCanonicalQueryTrustShape,
  isKnownSummaryPresentationStatus,
  queryAiPresentation,
  summaryAiPresentation,
} from '../src/services/aiPresentation'

function evidenceQuery() {
  return {
    can_answer: true,
    answer: '护照在书房。',
    certainty: 'evidence',
    evidence: [{ source_type: 'USER_TEXT' }],
    memory_ids: ['11111111-1111-4111-8111-111111111111'],
  }
}

test('query evidence-backed answer maps to INFERRED', () => {
  const presentation = queryAiPresentation(evidenceQuery())
  assert.equal(presentation.state, AI_PRESENTATION_STATE.INFERRED)
  assert.equal(presentation.label, 'AI 推断（有证据支持）')
  assert.equal(isCanonicalQueryTrustShape(evidenceQuery()), true)
})

test('canonical no-evidence maps to UNAVAILABLE', () => {
  const input = {
    can_answer: false,
    answer: null,
    certainty: 'unknown',
    evidence: [],
    memory_ids: [],
  }
  assert.equal(queryAiPresentation(input).state, AI_PRESENTATION_STATE.UNAVAILABLE)
  assert.equal(isCanonicalQueryTrustShape(input), true)
})

test('contradictory and unknown query shapes fail canonical trust parsing', () => {
  assert.equal(isCanonicalQueryTrustShape({
    ...evidenceQuery(),
    evidence: [],
  }), false)
  assert.equal(isCanonicalQueryTrustShape({
    ...evidenceQuery(),
    certainty: 'confirmed',
  }), false)
  assert.equal(isCanonicalQueryTrustShape({
    ...evidenceQuery(),
    certainty: 'future-value',
  }), false)
})

test('summary statuses use the same four-state semantics', () => {
  for (const status of [
    'DAILY_SUMMARY_READY',
    'MONTHLY_SUMMARY_READY',
    'ANNUAL_SUMMARY_READY',
  ]) {
    assert.equal(summaryAiPresentation(status).state, AI_PRESENTATION_STATE.INFERRED)
  }
  assert.equal(
    summaryAiPresentation('SUMMARY_INCOMPLETE').state,
    AI_PRESENTATION_STATE.UNCERTAIN,
  )
  for (const status of [
    'NO_SUMMARIZABLE_EVIDENCE',
    'PROVIDER_FAILED',
    'MALFORMED_PROVIDER_OUTPUT',
    'INVALID_CITATION',
    'DATA_CHANGED_DURING_GENERATION',
  ]) {
    assert.equal(summaryAiPresentation(status).state, AI_PRESENTATION_STATE.UNAVAILABLE)
    assert.equal(isKnownSummaryPresentationStatus(status), true)
  }
  assert.equal(summaryAiPresentation('FUTURE_STATUS').state, AI_PRESENTATION_STATE.UNAVAILABLE)
  assert.equal(isKnownSummaryPresentationStatus('FUTURE_STATUS'), false)
})

test('explicit record remains EXPLICIT and is never promoted to AI inference', () => {
  const presentation = explicitRecordPresentation()
  assert.equal(presentation.state, AI_PRESENTATION_STATE.EXPLICIT)
  assert.equal(presentation.label, '明确记录')
})
