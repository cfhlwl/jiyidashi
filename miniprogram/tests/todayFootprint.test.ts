import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'
import test from 'node:test'
import {
  parseTodayFootprintResponse,
  TodayFootprintRequestEpoch,
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


const todayPageSource = readFileSync(resolve(process.cwd(), 'src/pages/index/index.tsx'), 'utf8')

test('Elder Today Footprint uses existing self endpoint and no parallel authority', () => {
  assert.match(todayPageSource, /getTodayFootprint\(\)/)
  assert.match(todayPageSource, /subscribeElderMode\(setElderMode\)/)
  assert.match(todayPageSource, /elderMode \? '今天去了哪里' : '今天'/)
  assert.doesNotMatch(todayPageSource, /family\/members.*today\/footprint/)
  assert.doesNotMatch(todayPageSource, /getLocation|chooseMedia|getRecorderManager/)
})

test('Today Footprint preserves server visit order for Elder presentation', () => {
  const parsed = parseTodayFootprintResponse(response([
    visit({ id: 'first', place_name: '先到的地方', arrived_at_local: '2026-09-20T09:10:00+08:00' }),
    visit({ id: 'second', place_name: '后到的地方', arrived_at_local: '2026-09-20T08:10:00+08:00' }),
  ]))
  assert.deepEqual(parsed.visits.map((item) => item.id), ['first', 'second'])
})

test('empty/open Elder semantics never claim no outing or current location', () => {
  assert.match(todayPageSource, /今天还没有形成足迹/)
  assert.doesNotMatch(todayPageSource, /今天没有出门|一直在家|没有去任何地方/)
  assert.doesNotMatch(todayPageSource, /你现在就在|当前位置是/)
  const row = toTodayFootprintRow(visit({
    left_at: null,
    left_at_local: null,
    visit_finalized: false,
  }))
  assert.equal(row.timeRange, '23:50 起')
})

test('pending Today Footprint invalidation ignores late result and fresh request can publish', async () => {
  const epoch = new TodayFootprintRequestEpoch()
  let published: string | null = null
  let resolveOld!: (value: string) => void
  const oldResponse = new Promise<string>((resolve) => { resolveOld = resolve })
  const oldGeneration = epoch.capture()

  const pending = oldResponse.then((value) => {
    if (epoch.isCurrent(oldGeneration)) published = value
  })

  epoch.invalidate()
  resolveOld('old-A')
  await pending
  assert.equal(published, null)

  const freshGeneration = epoch.capture()
  const fresh = await Promise.resolve('fresh-B')
  if (epoch.isCurrent(freshGeneration)) published = fresh
  assert.equal(published, 'fresh-B')
})

test('production page invalidates on auth change, hide and unmount', () => {
  assert.match(todayPageSource, /subscribeAuthSession\(/)
  assert.match(todayPageSource, /useDidHide\(\(\) => \{[\s\S]*?footprintEpoch\.current\.invalidate\(\)[\s\S]*?setLoading\(false\)/)
  assert.match(todayPageSource, /useEffect\(\(\) => \(\) => \{[\s\S]*?footprintEpoch\.current\.invalidate\(\)/)
  assert.doesNotMatch(todayPageSource, /listPlaces\([^)]*\)[\s\S]*setFootprint/)
})
