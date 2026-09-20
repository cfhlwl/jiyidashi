import assert from 'node:assert/strict'
import test from 'node:test'
import {
  parseTodayFootprintResponse,
  toTodayFootprintRow,
  type TodayFootprintVisit,
} from '../src/services/todayFootprint'

function visit(overrides: Partial<TodayFootprintVisit> = {}): TodayFootprintVisit {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    place_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    place_name: '家',
    arrived_at: '2026-09-19T15:50:00Z',
    left_at: '2026-09-19T16:20:00Z',
    arrived_at_local: '2026-09-19T23:50:00+08:00',
    left_at_local: '2026-09-20T00:20:00+08:00',
    confidence: 0.9,
    visit_source: 'LOCATION_CLUSTER',
    visit_finalized: true,
    ...overrides,
  }
}

function response(visits: unknown = [visit()]): unknown {
  return {
    timezone: 'Asia/Shanghai',
    day: '2026-09-20',
    visits,
  }
}

test('Today Footprint keeps server-local cross-midnight wall clock unchanged', () => {
  const parsed = parseTodayFootprintResponse(response())
  const row = toTodayFootprintRow(parsed.visits[0])
  assert.equal(row.placeName, '家')
  assert.equal(row.timeRange, '23:50 - 00:20')
  assert.equal(row.stateLabel, '已形成足迹')
  assert.equal(row.source, 'LOCATION_CLUSTER')
})

test('Today Footprint renders open visit as in progress', () => {
  const parsed = parseTodayFootprintResponse(response([
    visit({
      left_at: null,
      left_at_local: null,
      visit_finalized: false,
    }),
  ]))
  const row = toTodayFootprintRow(parsed.visits[0])
  assert.equal(row.timeRange, '23:50 起')
  assert.equal(row.stateLabel, '进行中')
})

// [人工注释][S2-012] runtime parser 必须在 React render 前拒绝错误状态类型；
// 字符串 "false" 不能利用 JS truthy 语义被展示成“已形成足迹”。
test('malformed visit_finalized string fails closed', () => {
  assert.throws(
    () => parseTodayFootprintResponse(response([
      {
        ...visit(),
        visit_finalized: 'false',
      },
    ])),
    /今日足迹数据异常/,
  )
})

test('missing or non-array visits fails closed', () => {
  assert.throws(
    () => parseTodayFootprintResponse({
      timezone: 'Asia/Shanghai',
      day: '2026-09-20',
    }),
    /今日足迹数据异常/,
  )
  assert.throws(
    () => parseTodayFootprintResponse({
      timezone: 'Asia/Shanghai',
      day: '2026-09-20',
      visits: {},
    }),
    /今日足迹数据异常/,
  )
})

test('invalid arrived_at_local fails closed before formatting', () => {
  assert.throws(
    () => parseTodayFootprintResponse(response([
      {
        ...visit(),
        arrived_at_local: 'not-a-date',
      },
    ])),
    /今日足迹数据异常/,
  )
})

test('parser validates day and finite confidence', () => {
  assert.throws(
    () => parseTodayFootprintResponse({
      timezone: 'Asia/Shanghai',
      day: '2026-02-30',
      visits: [],
    }),
    /今日足迹数据异常/,
  )
  assert.throws(
    () => parseTodayFootprintResponse(response([
      {
        ...visit(),
        confidence: Number.NaN,
      },
    ])),
    /今日足迹数据异常/,
  )
test('ISO datetime rejects impossible calendar dates and accepts leap day', () => {
  assert.throws(
    () => parseTodayFootprintResponse(response([
      {
        ...visit(),
        arrived_at_local: '2026-02-30T12:00:00Z',
      },
    ])),
    /今日足迹数据异常/,
  )
  assert.throws(
    () => parseTodayFootprintResponse(response([
      {
        ...visit(),
        arrived_at_local: '2026-04-31T12:00:00+08:00',
      },
    ])),
    /今日足迹数据异常/,
  )

  const parsed = parseTodayFootprintResponse(response([
    {
      ...visit(),
      arrived_at: '2028-02-29T04:00:00Z',
      arrived_at_local: '2028-02-29T12:00:00+08:00',
    },
  ]))
  assert.equal(parsed.visits[0].arrived_at_local, '2028-02-29T12:00:00+08:00')
})

})
