import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

import { parseMemoryQueryResult } from '../src/services/memoryQuery'

function structuredFootprint(overrides: Record<string, unknown> = {}): unknown {
  return {
    answer: '2026-09-25 的可靠足迹：\n18:16–19:05  万达广场',
    can_answer: true,
    certainty: 'confirmed',
    reason: null,
    intent: 'DATE_FOOTPRINT_QUERY',
    evidence: [],
    memory_ids: [],
    day_footprint: {
      timezone: 'Asia/Shanghai',
      day: '2026-09-25',
      empty: false,
      visits: [
        {
          id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
          place_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          place_name: '万达广场',
          arrived_at: '2026-09-25T10:16:00Z',
          left_at: '2026-09-25T11:05:00Z',
          arrived_at_local: '2026-09-25T18:16:00+08:00',
          left_at_local: '2026-09-25T19:05:00+08:00',
          confidence: 0.95,
          visit_source: 'LOCATION_CLUSTER',
          visit_finalized: true,
        },
      ],
    },
    ...overrides,
  }
}

test('Mini query parser accepts structured day footprint without memory evidence', () => {
  const parsed = parseMemoryQueryResult(structuredFootprint())
  assert.equal(parsed.intent, 'DATE_FOOTPRINT_QUERY')
  assert.equal(parsed.evidence.length, 0)
  assert.equal(parsed.memory_ids.length, 0)
  assert.equal(parsed.day_footprint?.day, '2026-09-25')
  assert.equal(parsed.day_footprint?.visits[0]?.place_name, '万达广场')
})

test('Mini generic no-evidence cannot smuggle a non-null answer', () => {
  assert.throws(
    () => parseMemoryQueryResult({
      answer: '不应展示',
      can_answer: false,
      certainty: 'unknown',
      reason: 'NO_EVIDENCE',
      intent: 'MEMORY_SEARCH',
      evidence: [],
      memory_ids: [],
    }),
    /服务端查询响应格式不正确/,
  )
})

test('Mini query parser rejects day footprint empty/visit mismatch', () => {
  const raw = structuredFootprint() as Record<string, unknown>
  const footprint = raw.day_footprint as Record<string, unknown>
  assert.throws(
    () => parseMemoryQueryResult({
      ...raw,
      day_footprint: {
        ...footprint,
        empty: true,
      },
    }),
    /服务端查询响应格式不正确/,
  )
})

test('Mini historical query UI hides developer enums and binds stale results to owner/auth epoch', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/query/index.tsx'), 'utf8')

  assert.match(page, /DATE_FOOTPRINT_QUERY:\s*'按日期看足迹'/)
  assert.match(page, /queryIntentLabel\(result\.intent\)/)
  assert.doesNotMatch(page, /查询类型：\{result\.intent\}/)
  assert.match(page, /label: '有记录支持'/)
  assert.match(page, /这个答案来自已形成的地点访问记录。/)

  assert.match(page, /const capturedQueryEpoch = queryEpoch\.current\.capture\(\)/)
  assert.match(page, /const capturedOwner = authOwnerRef\.current/)
  assert.match(page, /const capturedAuthEpoch = authEpochRef\.current/)
  assert.match(page, /!queryEpoch\.current\.isCurrent\(capturedQueryEpoch\)/)
  assert.match(page, /authOwnerRef\.current !== capturedOwner/)
  assert.match(page, /authEpochRef\.current !== capturedAuthEpoch/)
})
