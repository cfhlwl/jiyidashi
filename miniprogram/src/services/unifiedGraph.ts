import { isUuid } from './memoryFeedback'

export const GRAPH_NODE_KINDS = ['PERSON', 'PLACE', 'OBJECT', 'EVENT'] as const
export type GraphNodeKind = typeof GRAPH_NODE_KINDS[number]

export const GRAPH_EDGE_KINDS = [
  'PERSON_RELATIONSHIP',
  'PERSON_EVENT',
  'OBJECT_PLACE',
  'EVENT_PLACE',
] as const
export type GraphEdgeKind = typeof GRAPH_EDGE_KINDS[number]

export type GraphRelationshipKind =
  | 'FAMILY'
  | 'FRIEND'
  | 'COLLEAGUE'
  | 'CLASSMATE'
  | 'OTHER'

export type GraphPersonEventRelationKind = 'RELATED' | 'MET'

export type GraphNodeRef = {
  kind: GraphNodeKind
  id: string
  label: string
  occurred_at: string | null
}

export type GraphEdgeMetadata = {
  relationship_kind: GraphRelationshipKind | null
  custom_label: string | null
  relation_kind: GraphPersonEventRelationKind | null
  recorded_at: string | null
}

export type GraphEdgeProjection = {
  edge_kind: GraphEdgeKind
  source: GraphNodeRef
  target: GraphNodeRef
  authority_ref: string
  metadata: GraphEdgeMetadata
}

export type GraphNeighborhood = {
  center: GraphNodeRef
  nodes: GraphNodeRef[]
  edges: GraphEdgeProjection[]
  truncated: boolean
}

export type UnifiedGraphAuthoritySnapshot = Readonly<{
  generation: number
  owner: string
  sessionEpoch: number
  kind: GraphNodeKind
  entityId: string
}>

const NODE_KIND_SET = new Set<GraphNodeKind>(GRAPH_NODE_KINDS)
const EDGE_KIND_SET = new Set<GraphEdgeKind>(GRAPH_EDGE_KINDS)
const RELATIONSHIP_KIND_SET = new Set<GraphRelationshipKind>([
  'FAMILY',
  'FRIEND',
  'COLLEAGUE',
  'CLASSMATE',
  'OTHER',
])
const PERSON_EVENT_RELATION_SET = new Set<GraphPersonEventRelationKind>([
  'RELATED',
  'MET',
])

const LABEL_MAX = 500
const CUSTOM_LABEL_MAX = 120

function invalidGraphResponse(): never {
  throw new Error('一跳关系数据异常，请稍后重试')
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return invalidGraphResponse()
  }
  return value as Record<string, unknown>
}

function parseNodeKind(value: unknown): GraphNodeKind {
  if (typeof value !== 'string' || !NODE_KIND_SET.has(value as GraphNodeKind)) {
    return invalidGraphResponse()
  }
  return value as GraphNodeKind
}

function parseEdgeKind(value: unknown): GraphEdgeKind {
  if (typeof value !== 'string' || !EDGE_KIND_SET.has(value as GraphEdgeKind)) {
    return invalidGraphResponse()
  }
  return value as GraphEdgeKind
}

function nonEmptyBoundedString(value: unknown, maxLength: number): string {
  if (typeof value !== 'string' || !value.trim() || value.length > maxLength) {
    return invalidGraphResponse()
  }
  return value
}

function nullableBoundedString(value: unknown, maxLength: number): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || value.length > maxLength) {
    return invalidGraphResponse()
  }
  return value
}

function awareIsoDateTime(value: unknown): string {
  if (
    typeof value !== 'string'
    || !value.includes('T')
    || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    || !Number.isFinite(Date.parse(value))
  ) {
    return invalidGraphResponse()
  }
  return value
}

function nullableAwareIsoDateTime(value: unknown): string | null {
  if (value === null) return null
  return awareIsoDateTime(value)
}

export function typedNodeKey(kind: GraphNodeKind, id: string): string {
  if (!NODE_KIND_SET.has(kind) || !isUuid(id)) throw new Error('图谱节点身份无效')
  return kind + ':' + id.toLowerCase()
}

export function parseGraphNodeRef(value: unknown): GraphNodeRef {
  const raw = record(value)
  const kind = parseNodeKind(raw.kind)
  if (!isUuid(raw.id)) return invalidGraphResponse()
  const occurredAt = nullableAwareIsoDateTime(raw.occurred_at)
  if (kind === 'EVENT' && occurredAt === null) return invalidGraphResponse()

  return {
    kind,
    id: raw.id,
    label: nonEmptyBoundedString(raw.label, LABEL_MAX),
    occurred_at: occurredAt,
  }
}

function nullableRelationshipKind(value: unknown): GraphRelationshipKind | null {
  if (value === null) return null
  if (
    typeof value !== 'string'
    || !RELATIONSHIP_KIND_SET.has(value as GraphRelationshipKind)
  ) {
    return invalidGraphResponse()
  }
  return value as GraphRelationshipKind
}

function nullablePersonEventRelation(
  value: unknown,
): GraphPersonEventRelationKind | null {
  if (value === null) return null
  if (
    typeof value !== 'string'
    || !PERSON_EVENT_RELATION_SET.has(value as GraphPersonEventRelationKind)
  ) {
    return invalidGraphResponse()
  }
  return value as GraphPersonEventRelationKind
}

function parseEdgeMetadata(
  value: unknown,
  edgeKind: GraphEdgeKind,
): GraphEdgeMetadata {
  const raw = record(value)
  const relationshipKind = nullableRelationshipKind(raw.relationship_kind)
  const customLabel = nullableBoundedString(raw.custom_label, CUSTOM_LABEL_MAX)
  const relationKind = nullablePersonEventRelation(raw.relation_kind)
  const recordedAt = nullableAwareIsoDateTime(raw.recorded_at)

  if (edgeKind === 'PERSON_RELATIONSHIP') {
    if (relationshipKind === null || relationKind !== null || recordedAt !== null) {
      return invalidGraphResponse()
    }
    if (relationshipKind === 'OTHER') {
      if (customLabel === null || !customLabel.trim()) return invalidGraphResponse()
    } else if (customLabel !== null) {
      return invalidGraphResponse()
    }
  } else if (edgeKind === 'PERSON_EVENT') {
    if (
      relationKind === null
      || relationshipKind !== null
      || customLabel !== null
      || recordedAt !== null
    ) {
      return invalidGraphResponse()
    }
  } else if (edgeKind === 'OBJECT_PLACE') {
    if (
      recordedAt === null
      || relationshipKind !== null
      || customLabel !== null
      || relationKind !== null
    ) {
      return invalidGraphResponse()
    }
  } else if (
    relationshipKind !== null
    || customLabel !== null
    || relationKind !== null
    || recordedAt !== null
  ) {
    return invalidGraphResponse()
  }

  return {
    relationship_kind: relationshipKind,
    custom_label: customLabel,
    relation_kind: relationKind,
    recorded_at: recordedAt,
  }
}

function sameNode(left: GraphNodeRef, right: GraphNodeRef): boolean {
  return (
    typedNodeKey(left.kind, left.id) === typedNodeKey(right.kind, right.id)
    && left.label === right.label
    && left.occurred_at === right.occurred_at
  )
}

function assertEdgeEndpointKinds(
  edgeKind: GraphEdgeKind,
  source: GraphNodeRef,
  target: GraphNodeRef,
): void {
  const pair = [source.kind, target.kind]

  if (edgeKind === 'PERSON_RELATIONSHIP') {
    if (pair[0] !== 'PERSON' || pair[1] !== 'PERSON') return invalidGraphResponse()
    return
  }

  const kinds = new Set(pair)
  if (
    edgeKind === 'PERSON_EVENT'
    && kinds.size === 2
    && kinds.has('PERSON')
    && kinds.has('EVENT')
  ) return

  if (
    edgeKind === 'OBJECT_PLACE'
    && kinds.size === 2
    && kinds.has('OBJECT')
    && kinds.has('PLACE')
  ) return

  if (
    edgeKind === 'EVENT_PLACE'
    && kinds.size === 2
    && kinds.has('EVENT')
    && kinds.has('PLACE')
  ) return

  return invalidGraphResponse()
}

export function parseGraphEdgeProjection(value: unknown): GraphEdgeProjection {
  const raw = record(value)
  const edgeKind = parseEdgeKind(raw.edge_kind)
  const source = parseGraphNodeRef(raw.source)
  const target = parseGraphNodeRef(raw.target)
  assertEdgeEndpointKinds(edgeKind, source, target)
  if (!isUuid(raw.authority_ref)) return invalidGraphResponse()

  return {
    edge_kind: edgeKind,
    source,
    target,
    authority_ref: raw.authority_ref,
    metadata: parseEdgeMetadata(raw.metadata, edgeKind),
  }
}

export function parseGraphNeighborhood(
  value: unknown,
  expectedKind: GraphNodeKind,
  expectedId: string,
  limit = 50,
): GraphNeighborhood {
  if (!NODE_KIND_SET.has(expectedKind) || !isUuid(expectedId)) {
    throw new Error('一跳关系参数无效')
  }
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('一跳关系数量必须在 1 到 100 之间')
  }

  const raw = record(value)
  if (!Array.isArray(raw.nodes) || !Array.isArray(raw.edges)) {
    return invalidGraphResponse()
  }
  if (typeof raw.truncated !== 'boolean' || raw.edges.length > limit) {
    return invalidGraphResponse()
  }

  const center = parseGraphNodeRef(raw.center)
  if (
    center.kind !== expectedKind
    || center.id.toLowerCase() !== expectedId.toLowerCase()
  ) {
    return invalidGraphResponse()
  }

  // Validate complete node and edge collections before returning any UI authority.
  const nodes = raw.nodes.map((item) => parseGraphNodeRef(item))
  const nodeMap = new Map<string, GraphNodeRef>()
  const centerKey = typedNodeKey(center.kind, center.id)
  for (const node of nodes) {
    const key = typedNodeKey(node.kind, node.id)
    if (key === centerKey || nodeMap.has(key)) return invalidGraphResponse()
    nodeMap.set(key, node)
  }

  const edges = raw.edges.map((item) => parseGraphEdgeProjection(item))
  const edgeAuthorities = new Set<string>()
  for (const edge of edges) {
    const sourceKey = typedNodeKey(edge.source.kind, edge.source.id)
    const targetKey = typedNodeKey(edge.target.kind, edge.target.id)
    const sourceIsCenter = sourceKey === centerKey
    const targetIsCenter = targetKey === centerKey

    if (sourceIsCenter === targetIsCenter) return invalidGraphResponse()

    const centerEndpoint = sourceIsCenter ? edge.source : edge.target
    const neighborEndpoint = sourceIsCenter ? edge.target : edge.source
    if (!sameNode(centerEndpoint, center)) return invalidGraphResponse()

    const canonicalNeighbor = nodeMap.get(
      typedNodeKey(neighborEndpoint.kind, neighborEndpoint.id),
    )
    if (!canonicalNeighbor || !sameNode(neighborEndpoint, canonicalNeighbor)) {
      return invalidGraphResponse()
    }

    const authorityKey = edge.edge_kind + ':' + edge.authority_ref.toLowerCase()
    if (edgeAuthorities.has(authorityKey)) return invalidGraphResponse()
    edgeAuthorities.add(authorityKey)
  }

  return {
    center,
    nodes,
    edges,
    truncated: raw.truncated,
  }
}

export function graphNeighborhoodPath(
  kind: GraphNodeKind,
  entityId: string,
  limit = 50,
): string {
  if (!NODE_KIND_SET.has(kind) || !isUuid(entityId)) {
    throw new Error('一跳关系参数无效')
  }
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('一跳关系数量必须在 1 到 100 之间')
  }
  return (
    '/graph/neighborhood/'
    + encodeURIComponent(kind)
    + '/'
    + encodeURIComponent(entityId)
    + '?limit='
    + limit
  )
}

export function graphNeighborhoodRoute(kind: GraphNodeKind, entityId: string): string {
  if (!NODE_KIND_SET.has(kind) || !isUuid(entityId)) {
    throw new Error('一跳关系参数无效')
  }
  return (
    '/pages/graph-neighborhood/index?kind='
    + encodeURIComponent(kind)
    + '&id='
    + encodeURIComponent(entityId)
  )
}

export function parseGraphRouteIdentity(
  kind: unknown,
  entityId: unknown,
): { kind: GraphNodeKind; entityId: string } {
  if (
    typeof kind !== 'string'
    || !NODE_KIND_SET.has(kind as GraphNodeKind)
    || typeof entityId !== 'string'
    || !isUuid(entityId)
  ) {
    throw new Error('一跳关系参数无效')
  }
  return { kind: kind as GraphNodeKind, entityId }
}

export function graphNodeKindLabel(kind: GraphNodeKind): string {
  const labels: Record<GraphNodeKind, string> = {
    PERSON: '人物',
    PLACE: '地点',
    OBJECT: '物品',
    EVENT: '事件',
  }
  return labels[kind]
}

export function graphRelationshipKindLabel(
  kind: GraphRelationshipKind,
  customLabel: string | null,
): string {
  const labels: Record<Exclude<GraphRelationshipKind, 'OTHER'>, string> = {
    FAMILY: '家人',
    FRIEND: '朋友',
    COLLEAGUE: '同事',
    CLASSMATE: '同学',
  }
  return kind === 'OTHER' ? customLabel || '其他' : labels[kind]
}

export function graphEdgeLabel(edge: GraphEdgeProjection): string {
  if (edge.edge_kind === 'PERSON_RELATIONSHIP') {
    return (
      '人物关系 · '
      + graphRelationshipKindLabel(
        edge.metadata.relationship_kind as GraphRelationshipKind,
        edge.metadata.custom_label,
      )
    )
  }
  if (edge.edge_kind === 'PERSON_EVENT') {
    return edge.metadata.relation_kind === 'MET' ? '见过·互动过' : '相关记忆'
  }
  if (edge.edge_kind === 'OBJECT_PLACE') return '当前所在地点'
  return '发生地点'
}

export function graphNodeForEdge(
  edge: GraphEdgeProjection,
  center: GraphNodeRef,
): GraphNodeRef {
  const centerKey = typedNodeKey(center.kind, center.id)
  return typedNodeKey(edge.source.kind, edge.source.id) === centerKey
    ? edge.target
    : edge.source
}

export function graphErrorMessage(code: string | null): string | null {
  if (code === 'GRAPH_NODE_NOT_FOUND') {
    return '这个节点当前不可用，请返回后重试'
  }
  return null
}

export function formatGraphTimestamp(value: string): string {
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return (
    parsed.getFullYear()
    + '-'
    + pad(parsed.getMonth() + 1)
    + '-'
    + pad(parsed.getDate())
    + ' '
    + pad(parsed.getHours())
    + ':'
    + pad(parsed.getMinutes())
  )
}

export class UnifiedGraphUiAuthority {
  private generation = 0

  invalidate(): void {
    this.generation += 1
  }

  capture(
    owner: string | null,
    sessionEpoch: number,
    kind: GraphNodeKind,
    entityId: string,
  ): UnifiedGraphAuthoritySnapshot {
    if (!owner || !isUuid(owner)) throw new Error('请先登录')
    if (!Number.isSafeInteger(sessionEpoch) || sessionEpoch < 0) {
      throw new Error('登录状态异常，请重新登录')
    }
    if (!NODE_KIND_SET.has(kind) || !isUuid(entityId)) {
      throw new Error('一跳关系参数无效')
    }
    return {
      generation: this.generation,
      owner,
      sessionEpoch,
      kind,
      entityId,
    }
  }

  isCurrent(
    snapshot: UnifiedGraphAuthoritySnapshot,
    owner: string | null,
    sessionEpoch: number,
    kind: GraphNodeKind,
    entityId: string,
  ): boolean {
    return (
      snapshot.generation === this.generation
      && snapshot.owner === owner
      && snapshot.sessionEpoch === sessionEpoch
      && snapshot.kind === kind
      && snapshot.entityId.toLowerCase() === entityId.toLowerCase()
    )
  }
}
