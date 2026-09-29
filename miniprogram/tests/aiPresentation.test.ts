import assert from 'node:assert/strict'
import test from 'node:test'

import {
  explicitRecordPresentation,
  isKnownSummaryPresentationStatus,
  summaryAiPresentation,
} from '../src/services/aiPresentation'

test('Trusted Summary READY maps to AI INFERRED', () => {
  for (const status of [
    'DAILY_SUMMARY_READY',
    'MONTHLY_SUMMARY_READY',
    'ANNUAL_SUMMARY_READY',
  ]) {
    const presentation = summaryAiPresentation(status)
    assert.equal(presentation.state, 'INFERRED')
    assert.equal(presentation.label, 'AI 推断（有证据支持）')
  }
})

test('Trusted Summary incomplete and unavailable statuses stay fail closed', () => {
  assert.equal(summaryAiPresentation('SUMMARY_INCOMPLETE').state, 'UNCERTAIN')
  for (const status of [
    'NO_SUMMARIZABLE_EVIDENCE',
    'PROVIDER_FAILED',
    'MALFORMED_PROVIDER_OUTPUT',
    'INVALID_CITATION',
    'DATA_CHANGED_DURING_GENERATION',
    'FUTURE_STATUS',
  ]) {
    assert.equal(summaryAiPresentation(status).state, 'UNAVAILABLE')
  }
  assert.equal(isKnownSummaryPresentationStatus('FUTURE_STATUS'), false)
})

test('explicit stored record presentation remains independent from AI surfaces', () => {
  const presentation = explicitRecordPresentation()
  assert.equal(presentation.state, 'EXPLICIT')
  assert.equal(presentation.label, '明确记录')
})
