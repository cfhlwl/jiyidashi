import assert from 'node:assert/strict'
import test from 'node:test'
import {
  assertPlaceDetailIdentity,
  buildPlaceDetailPath,
  buildPlacesPath,
  mergePlaceDetailPages,
  parsePlaceDetail,
  parsePlaceList,
  placeDetailRoute,
  placeListPresentation,
} from '../src/services/placeDetail'

function place(overrides: Record<string, unknown> = {}) {
  return {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    name: '家',
    automatic_name: '住宅',
    automatic_name_source: 'POI',
    user_name: '家',
    name_source: 'USER',
    name_revision: 3,
    name_updated_at: '2026-09-20T02:00:00Z',
    latitude: 39.9,
    longitude: 116.4,
    address: '测试地址',
    category: '住宅',
    first_visited_at: '2026-09-18T01:00:00Z',
    last_visited_at: '2026-09-20T01:00:00Z',
    visit_count: 2,
    is_user_named: true,
    ...overrides,
  }
}

function visit(overrides: Record<string, unknown> = {}) {
  return {
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    arrived_at: '2026-09-20T01:00:00Z',
    left_at: '2026-09-20T02:00:00Z',
    duration_seconds: 3600,
    confidence: 0.95,
    source: 'LOCATION_CLUSTER',
    finalized_at: '2026-09-20T02:05:00Z',
    visit_finalized: true,
    ...overrides,
  }
}

function page(overrides: Record<string, unknown> = {}) {
  return { place: place(), visits: [visit()], next_cursor: null, ...overrides }
}

test('place parser preserves authoritative USER display name over automatic candidate', () => {
  const parsed = parsePlaceList([place()])
  assert.equal(parsed.length, 1)
  assert.equal(parsed[0].name, '家')
  assert.equal(parsed[0].name_source, 'USER')
  assert.equal(parsed[0].user_name, '家')
  assert.equal(parsed[0].automatic_name, '住宅')
})

test('place detail rejects string finalized flag instead of rendering a mutable visit', () => {
  assert.throws(
    () => parsePlaceDetail(page({ visits: [visit({ visit_finalized: 'true' })] })),
    /visit_finalized/,
  )
})

test('place detail rejects malformed cursor before any pagination merge', () => {
  const current = parsePlaceDetail(page({ next_cursor: 'cursor-1' }))
  const snapshot = JSON.stringify(current)
  assert.throws(
    () => parsePlaceDetail(page({
      visits: [visit({ id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', visit_finalized: false })],
      next_cursor: 123,
    })),
    /next_cursor/,
  )
  assert.equal(JSON.stringify(current), snapshot)
  assert.equal(current.visits.length, 1)
})

test('empty retained Visit page is a valid explicit empty state', () => {
  const parsed = parsePlaceDetail(page({ visits: [] }))
  assert.equal(parsed.visits.length, 0)
})

test('initial detail identity mismatch fails closed', () => {
  const parsed = parsePlaceDetail(page({ place: place({ id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' }) }))
  assert.throws(
    () => assertPlaceDetailIdentity(parsed, 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
    /地点身份/,
  )
})

test('pagination merge is atomic and rejects a different place identity', () => {
  const current = parsePlaceDetail(page({ next_cursor: 'cursor-1' }))
  const next = parsePlaceDetail(page({
    visits: [visit({ id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', visit_finalized: false, finalized_at: null })],
    next_cursor: null,
  }))
  const merged = mergePlaceDetailPages(current, next)
  assert.equal(current.visits.length, 1)
  assert.equal(merged.visits.length, 2)
  assert.equal(merged.next_cursor, null)

  const wrongPlace = parsePlaceDetail(page({ place: place({ id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' }) }))
  assert.throws(() => mergePlaceDetailPages(current, wrongPlace), /不同的地点/)
})

test('place detail path keeps owner implicit and forwards the opaque cursor', () => {
  const path = buildPlaceDetailPath(' aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa ', 20, 'opaque+/=')
  assert.match(path, /^\/location\/places\/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\?limit=20&cursor=/)
  assert.match(path, /opaque%2B%2F%3D/)
  assert.equal(path.includes('user_id='), false)
  assert.equal(buildPlacesPath(25), '/location/places?limit=25')
})

test('place detail navigation carries only opaque place id', () => {
  const route = placeDetailRoute('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
  assert.equal(route, '/pages/place-detail/index?placeId=aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
  assert.equal(route.includes('user_id='), false)
})


test('successful empty Place list shows empty state without retry', () => {
  const state = placeListPresentation({
    loading: false,
    loaded: true,
    authenticated: true,
    placeCount: 0,
    error: '',
  })
  assert.deepEqual(state, {
    message: '还没有地点记录',
    showRetry: false,
  })
})

test('failed Place list request shows error with retry', () => {
  const state = placeListPresentation({
    loading: false,
    loaded: true,
    authenticated: true,
    placeCount: 0,
    error: '地点加载失败',
  })
  assert.deepEqual(state, {
    message: '地点加载失败',
    showRetry: true,
  })
})
