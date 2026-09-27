import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  GRAPH_EDGE_KINDS,
  GRAPH_NODE_KINDS,
  graphEdgeLabel,
  graphErrorMessage,
  graphNeighborhoodPath,
  graphNeighborhoodRoute,
  graphNodeForEdge,
  parseGraphNeighborhood,
  parseGraphNodeRef,
  typedNodeKey,
  UnifiedGraphUiAuthority,
  type GraphNodeKind,
} from '../src/services/unifiedGraph'

const OWNER = '11111111-1111-4111-8111-111111111111'
const PERSON = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const PERSON_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const PLACE = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
const OBJECT = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const EVENT = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
const AUTHORITY_A = 'f1111111-1111-4111-8111-111111111111'
const AUTHORITY_B = 'f2222222-2222-4222-8222-222222222222'

function node(
  kind: GraphNodeKind,
  id: string,
  label: string,
  occurredAt: string | null = null,
): unknown {
  return {
    kind,
    id,
    label,
    occurred_at: occurredAt,
  }
}

function personRelationshipEdge(overrides: Record<string, unknown> = {}): unknown {
  return {
    edge_kind: 'PERSON_RELATIONSHIP',
    source: node('PERSON', PERSON, '王阿姨'),
    target: node('PERSON', PERSON_B, '李老师'),
    authority_ref: AUTHORITY_A,
    metadata: {
      relationship_kind: 'FRIEND',
      custom_label: null,
      relation_kind: null,
      recorded_at: null,
    },
    ...overrides,
  }
}

function personEventEdge(overrides: Record<string, unknown> = {}): unknown {
  return {
    edge_kind: 'PERSON_EVENT',
    source: node('PERSON', PERSON, '王阿姨'),
    target: node('EVENT', EVENT, '一起喝茶', '2026-09-25T10:00:00+08:00'),
    authority_ref: AUTHORITY_B,
    metadata: {
      relationship_kind: null,
      custom_label: null,
      relation_kind: 'RELATED',
      recorded_at: null,
    },
    ...overrides,
  }
}

function neighborhood(overrides: Record<string, unknown> = {}): unknown {
  return {
    center: node('PERSON', PERSON, '王阿姨'),
    nodes: [
      node('PERSON', PERSON_B, '李老师'),
      node('EVENT', EVENT, '一起喝茶', '2026-09-25T10:00:00+08:00'),
    ],
    edges: [
      personRelationshipEdge(),
      personEventEdge(),
    ],
    truncated: false,
    ...overrides,
  }
}

test('exact four node kinds and exact four edge kinds are locked', () => {
  assert.deepEqual(GRAPH_NODE_KINDS, ['PERSON', 'PLACE', 'OBJECT', 'EVENT'])
  assert.deepEqual(GRAPH_EDGE_KINDS, [
    'PERSON_RELATIONSHIP',
    'PERSON_EVENT',
    'OBJECT_PLACE',
    'EVENT_PLACE',
  ])
})

test('typed identity is kind + id, so the same UUID across kinds remains distinct', () => {
  assert.notEqual(typedNodeKey('PERSON', PERSON), typedNodeKey('EVENT', PERSON))
  assert.equal(typedNodeKey('PERSON', PERSON), 'PERSON:' + PERSON)
})

test('node parser validates UUID, bounded label and aware EVENT timestamp', () => {
  assert.deepEqual(parseGraphNodeRef(node('PERSON', PERSON, '王阿姨')), {
    kind: 'PERSON',
    id: PERSON,
    label: '王阿姨',
    occurred_at: null,
  })
  assert.throws(() => parseGraphNodeRef(node('PERSON', 'bad', '王阿姨')), /数据异常/)
  assert.throws(() => parseGraphNodeRef(node('PLACE', PLACE, ' ')), /数据异常/)
  assert.throws(() => parseGraphNodeRef(node('EVENT', EVENT, '聚会', null)), /数据异常/)
  assert.throws(
    () => parseGraphNodeRef(node('EVENT', EVENT, '聚会', '2026-09-25T10:00:00')),
    /数据异常/,
  )
})

test('neighborhood binds center to exact requested typed identity', () => {
  assert.equal(parseGraphNeighborhood(neighborhood(), 'PERSON', PERSON).center.id, PERSON)
  assert.throws(() => parseGraphNeighborhood(neighborhood(), 'PLACE', PERSON), /数据异常/)
  assert.throws(() => parseGraphNeighborhood(neighborhood(), 'PERSON', PERSON_B), /数据异常/)
})

test('same bare UUID may exist as a different typed neighbor', () => {
  const response = {
    center: node('PERSON', PERSON, '王阿姨'),
    nodes: [node('EVENT', PERSON, '同 UUID 事件', '2026-09-25T10:00:00Z')],
    edges: [{
      edge_kind: 'PERSON_EVENT',
      source: node('PERSON', PERSON, '王阿姨'),
      target: node('EVENT', PERSON, '同 UUID 事件', '2026-09-25T10:00:00Z'),
      authority_ref: AUTHORITY_A,
      metadata: {
        relationship_kind: null,
        custom_label: null,
        relation_kind: 'MET',
        recorded_at: null,
      },
    }],
    truncated: false,
  }
  const parsed = parseGraphNeighborhood(response, 'PERSON', PERSON)
  assert.equal(parsed.nodes[0].id, PERSON)
  assert.equal(parsed.nodes[0].kind, 'EVENT')
})

test('whole neighborhood fails closed on malformed collections and duplicate typed nodes', () => {
  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [
      node('PERSON', PERSON_B, '李老师'),
      node('EVENT', 'bad', '坏事件', '2026-09-25T10:00:00Z'),
    ],
  }), 'PERSON', PERSON), /数据异常/)

  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [
      node('PERSON', PERSON_B, '李老师'),
      node('PERSON', PERSON_B, '李老师'),
    ],
    edges: [],
  }), 'PERSON', PERSON), /数据异常/)
})

test('center typed identity cannot be duplicated in nodes', () => {
  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [node('PERSON', PERSON, '王阿姨')],
    edges: [],
  }), 'PERSON', PERSON), /数据异常/)
})

test('every edge touches center exactly once', () => {
  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [node('PERSON', PERSON_B, '李老师')],
    edges: [{
      ...(personRelationshipEdge() as object),
      source: node('PERSON', PERSON_B, '李老师'),
      target: node('PERSON', '99999999-9999-4999-8999-999999999999', '其他'),
    }],
  }), 'PERSON', PERSON), /数据异常/)

  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [],
    edges: [{
      ...personRelationshipEdge() as object,
      target: node('PERSON', PERSON, '王阿姨'),
    }],
  }), 'PERSON', PERSON), /数据异常/)
})

test('edge neighbor must exist in nodes with matching canonical fields', () => {
  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [node('PERSON', PERSON_B, '另一个标签')],
    edges: [personRelationshipEdge()],
  }), 'PERSON', PERSON), /数据异常/)

  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [],
    edges: [personRelationshipEdge()],
  }), 'PERSON', PERSON), /数据异常/)
})

test('PERSON_RELATIONSHIP metadata is exact including OTHER custom_label', () => {
  const other = parseGraphNeighborhood({
    center: node('PERSON', PERSON, '王阿姨'),
    nodes: [node('PERSON', PERSON_B, '李老师')],
    edges: [personRelationshipEdge({
      metadata: {
        relationship_kind: 'OTHER',
        custom_label: '牌友',
        relation_kind: null,
        recorded_at: null,
      },
    })],
    truncated: false,
  }, 'PERSON', PERSON)
  assert.equal(other.edges[0].metadata.custom_label, '牌友')
  assert.equal(graphEdgeLabel(other.edges[0]), '人物关系 · 牌友')

  for (const metadata of [
    {
      relationship_kind: 'OTHER',
      custom_label: null,
      relation_kind: null,
      recorded_at: null,
    },
    {
      relationship_kind: 'FRIEND',
      custom_label: '不应存在',
      relation_kind: null,
      recorded_at: null,
    },
  ]) {
    assert.throws(() => parseGraphNeighborhood(neighborhood({
      nodes: [node('PERSON', PERSON_B, '李老师')],
      edges: [personRelationshipEdge({ metadata })],
    }), 'PERSON', PERSON), /数据异常/)
  }
})

test('PERSON_EVENT metadata accepts RELATED/MET only and no mixed metadata', () => {
  const met = parseGraphNeighborhood({
    center: node('PERSON', PERSON, '王阿姨'),
    nodes: [node('EVENT', EVENT, '聚会', '2026-09-25T10:00:00Z')],
    edges: [personEventEdge({
      target: node('EVENT', EVENT, '聚会', '2026-09-25T10:00:00Z'),
      metadata: {
        relationship_kind: null,
        custom_label: null,
        relation_kind: 'MET',
        recorded_at: null,
      },
    })],
    truncated: false,
  }, 'PERSON', PERSON)
  assert.equal(graphEdgeLabel(met.edges[0]), '见过·互动过')

  assert.throws(() => parseGraphNeighborhood(neighborhood({
    edges: [personEventEdge({
      metadata: {
        relationship_kind: 'FRIEND',
        custom_label: null,
        relation_kind: 'RELATED',
        recorded_at: null,
      },
    })],
  }), 'PERSON', PERSON), /数据异常/)
})

test('OBJECT_PLACE requires recorded_at and EVENT_PLACE requires empty metadata', () => {
  const objectPlace = {
    center: node('OBJECT', OBJECT, '钥匙'),
    nodes: [node('PLACE', PLACE, '家')],
    edges: [{
      edge_kind: 'OBJECT_PLACE',
      source: node('OBJECT', OBJECT, '钥匙'),
      target: node('PLACE', PLACE, '家'),
      authority_ref: AUTHORITY_A,
      metadata: {
        relationship_kind: null,
        custom_label: null,
        relation_kind: null,
        recorded_at: '2026-09-26T09:00:00+08:00',
      },
    }],
    truncated: false,
  }
  assert.equal(
    parseGraphNeighborhood(objectPlace, 'OBJECT', OBJECT).edges[0].metadata.recorded_at,
    '2026-09-26T09:00:00+08:00',
  )

  assert.throws(() => parseGraphNeighborhood({
    ...objectPlace,
    edges: [{
      ...(objectPlace.edges[0] as object),
      metadata: {
        relationship_kind: null,
        custom_label: null,
        relation_kind: null,
        recorded_at: null,
      },
    }],
  }, 'OBJECT', OBJECT), /数据异常/)

  const eventPlace = {
    center: node('EVENT', EVENT, '聚会', '2026-09-25T10:00:00Z'),
    nodes: [node('PLACE', PLACE, '餐厅')],
    edges: [{
      edge_kind: 'EVENT_PLACE',
      source: node('EVENT', EVENT, '聚会', '2026-09-25T10:00:00Z'),
      target: node('PLACE', PLACE, '餐厅'),
      authority_ref: EVENT,
      metadata: {
        relationship_kind: null,
        custom_label: null,
        relation_kind: null,
        recorded_at: null,
      },
    }],
    truncated: false,
  }
  assert.equal(parseGraphNeighborhood(eventPlace, 'EVENT', EVENT).edges.length, 1)
  assert.throws(() => parseGraphNeighborhood({
    ...eventPlace,
    edges: [{
      ...(eventPlace.edges[0] as object),
      metadata: {
        relationship_kind: null,
        custom_label: null,
        relation_kind: 'RELATED',
        recorded_at: null,
      },
    }],
  }, 'EVENT', EVENT), /数据异常/)
})

test('authority_ref is UUID and duplicate typed edge authority is rejected', () => {
  assert.throws(() => parseGraphNeighborhood(neighborhood({
    edges: [personRelationshipEdge({ authority_ref: 'bad' })],
  }), 'PERSON', PERSON), /数据异常/)

  assert.throws(() => parseGraphNeighborhood(neighborhood({
    nodes: [node('PERSON', PERSON_B, '李老师')],
    edges: [
      personRelationshipEdge(),
      personRelationshipEdge(),
    ],
  }), 'PERSON', PERSON), /数据异常/)
})

test('edge count cannot exceed requested limit and server edge order is preserved', () => {
  const parsed = parseGraphNeighborhood(neighborhood(), 'PERSON', PERSON, 50)
  assert.deepEqual(parsed.edges.map((edge) => edge.edge_kind), [
    'PERSON_RELATIONSHIP',
    'PERSON_EVENT',
  ])

  assert.throws(() => parseGraphNeighborhood(neighborhood(), 'PERSON', PERSON, 1), /数据异常/)
})

test('truncated boolean is preserved exactly', () => {
  assert.equal(parseGraphNeighborhood(neighborhood({ truncated: true }), 'PERSON', PERSON).truncated, true)
  assert.throws(() => parseGraphNeighborhood(neighborhood({ truncated: 'true' }), 'PERSON', PERSON), /数据异常/)
})

test('path and route encode exact typed identity with fixed bounded limit', () => {
  assert.equal(
    graphNeighborhoodPath('PERSON', PERSON, 50),
    '/graph/neighborhood/PERSON/' + PERSON + '?limit=50',
  )
  assert.equal(
    graphNeighborhoodRoute('PLACE', PLACE),
    '/pages/graph-neighborhood/index?kind=PLACE&id=' + PLACE,
  )
  assert.throws(() => graphNeighborhoodPath('PERSON', PERSON, 101), /1 到 100/)
})

test('GRAPH_NODE_NOT_FOUND uses bounded non-oracle copy', () => {
  assert.equal(
    graphErrorMessage('GRAPH_NODE_NOT_FOUND'),
    '这个节点当前不可用，请返回后重试',
  )
  assert.equal(graphErrorMessage('SECRET_DATABASE_DETAIL'), null)
})

test('neighbor resolution uses typed center identity', () => {
  const parsed = parseGraphNeighborhood(neighborhood(), 'PERSON', PERSON)
  assert.equal(graphNodeForEdge(parsed.edges[0], parsed.center).id, PERSON_B)
  assert.equal(graphNodeForEdge(parsed.edges[1], parsed.center).kind, 'EVENT')
})

test('request authority includes kind + id so same bare UUID across kinds is stale', () => {
  const authority = new UnifiedGraphUiAuthority()
  const snapshot = authority.capture(OWNER, 4, 'PERSON', PERSON)
  assert.equal(authority.isCurrent(snapshot, OWNER, 4, 'PERSON', PERSON), true)
  assert.equal(authority.isCurrent(snapshot, OWNER, 4, 'EVENT', PERSON), false)
  assert.equal(authority.isCurrent(snapshot, OWNER, 4, 'PERSON', PERSON_B), false)
  assert.equal(authority.isCurrent(snapshot, OWNER, 5, 'PERSON', PERSON), false)
  authority.invalidate()
  assert.equal(authority.isCurrent(snapshot, OWNER, 4, 'PERSON', PERSON), false)
})

test('graph page is one-hop read-only and has no sort/rank/traversal/prefetch', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/graph-neighborhood/index.tsx'), 'utf8')
  const service = readFileSync(resolve(process.cwd(), 'src/services/unifiedGraph.ts'), 'utf8')
  const source = [page, service].join('\n')
  assert.match(page, /getGraphNeighborhood\(identity\.kind, identity\.entityId, 50\)/)
  assert.match(page, /Taro\.redirectTo\(\{ url: graphNeighborhoodRoute\(kind, entityId\) \}\)/)
  assert.doesNotMatch(source, /\.sort\(|rank|score|centrality|shortest|friends.of.friends|prefetch|recursive|multi-hop/i)
  assert.doesNotMatch(source, /POST|PATCH|DELETE/)
})

test('graph page gates old success/error by owner, epoch and typed route identity', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/graph-neighborhood/index.tsx'), 'utf8')
  assert.match(page, /UnifiedGraphUiAuthority/)
  assert.match(page, /currentAuthenticatedUserId\(\)/)
  assert.match(page, /currentAuthSessionEpoch\(\)/)
  assert.match(page, /subscribeAuthSession/)
  assert.match(page, /routeIdentity\(\)\.kind/)
  assert.match(page, /routeIdentity\(\)\.entityId/)
  assert.match(page, /authority\.current\.invalidate\(\)/)
})

test('graph UI preserves edge order and never renders authority_ref or hidden fields', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/graph-neighborhood/index.tsx'), 'utf8')
  assert.match(page, /neighborhood\.edges\.map/)
  assert.doesNotMatch(page, /authority_ref\}/)
  assert.doesNotMatch(page, /confidence|embedding|latitude|longitude|Family|memory_content|metadata_json/)
})

test('truncated warning is visible and no automatic pagination exists', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/graph-neighborhood/index.tsx'), 'utf8')
  assert.match(page, /仅显示部分直接关系/)
  assert.doesNotMatch(page, /loadMore|next_cursor|pagination|limit=100/)
})

test('Graph API adapter is GET-only and strict parser-bound', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  const start = api.indexOf('export async function getGraphNeighborhood')
  const end = api.indexOf('function createPeopleRequestSessionGuard')
  const block = api.slice(start, end)
  assert.match(block, /request<unknown>\([\s\S]*?'GET',[\s\S]*?graphNeighborhoodPath/)
  assert.match(block, /parseGraphNeighborhood\(raw, kind, entityId, limit\)/)
  assert.doesNotMatch(block, /'POST'|'PATCH'|'DELETE'/)
})

test('Person and Place detail expose exact typed one-hop entry routes', () => {
  const person = readFileSync(resolve(process.cwd(), 'src/pages/person-detail/index.tsx'), 'utf8')
  const place = readFileSync(resolve(process.cwd(), 'src/pages/place-detail/index.tsx'), 'utf8')
  assert.match(person, /graphNeighborhoodRoute\('PERSON', detail\.id\)/)
  assert.match(place, /graphNeighborhoodRoute\('PLACE', detail\.place\.id\)/)
  assert.match(person, /查看一跳关系/)
  assert.match(place, /查看一跳关系/)
})

test('generic graph page is registered without changing the five-tab shell', () => {
  const app = readFileSync(resolve(process.cwd(), 'src/app.config.ts'), 'utf8')
  assert.match(app, /'pages\/graph-neighborhood\/index'/)
  assert.equal((app.match(/pagePath:/g) || []).length, 5)
})

test('Mini CI retains prior V2 triggers and adds canonical V2-004 graph surfaces', () => {
  const workflow = readFileSync(resolve(process.cwd(), '../.github/workflows/miniprogram-ci.yml'), 'utf8')
  for (const path of [
    'backend/app/api/people.py',
    'backend/app/person_memory_schemas.py',
    'backend/app/services/person_memory_service.py',
    'backend/app/person_relationship_schemas.py',
    'backend/app/services/person_relationship_service.py',
    'backend/app/api/graph.py',
    'backend/app/graph_schemas.py',
    'backend/app/services/graph_projection_service.py',
  ]) {
    assert.equal(workflow.includes(path), true)
  }
})
