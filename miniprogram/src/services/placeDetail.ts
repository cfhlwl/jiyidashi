// 网络响应先经过运行时 parser 再进入 UI；TypeScript 静态类型不能替代对不可信 JSON 的校验。
// Place/Visit/cursor/identity 任一字段异常都 fail closed，且分页只有整页验证成功后才能原子合并。
export type PlaceNameSource = 'USER' | 'AUTOMATIC' | 'UNNAMED'

export type PlaceRead = {
  id: string
  name: string
  automatic_name: string | null
  automatic_name_source: string | null
  user_name: string | null
  name_source: PlaceNameSource
  name_revision: number
  name_updated_at: string | null
  latitude: number | null
  longitude: number | null
  address: string | null
  category: string | null
  first_visited_at: string | null
  last_visited_at: string | null
  visit_count: number
  is_user_named: boolean
}

export type PlaceDetailVisit = {
  id: string
  arrived_at: string
  left_at: string | null
  duration_seconds: number | null
  confidence: number
  source: string
  finalized_at: string | null
  visit_finalized: boolean
}

export type PlaceDetailPage = {
  place: PlaceRead
  visits: PlaceDetailVisit[]
  next_cursor: string | null
}

type JsonRecord = Record<string, unknown>

export class PlaceDetailProtocolError extends Error {
  constructor(message = '地点详情协议错误') {
    super(message)
    this.name = 'PlaceDetailProtocolError'
  }
}

function record(value: unknown, field: string): JsonRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new PlaceDetailProtocolError(`${field} 必须是对象`)
  }
  return value as JsonRecord
}

function nonEmptyString(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new PlaceDetailProtocolError(`${field} 必须是非空字符串`)
  }
  return value
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null) return null
  if (typeof value !== 'string') {
    throw new PlaceDetailProtocolError(`${field} 必须是字符串或 null`)
  }
  return value
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new PlaceDetailProtocolError(`${field} 必须是非负整数`)
  }
  return value
}

function nullableNonNegativeInteger(value: unknown, field: string): number | null {
  if (value === null) return null
  return nonNegativeInteger(value, field)
}

function finiteNumber(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new PlaceDetailProtocolError(`${field} 必须是有限数字`)
  }
  return value
}

function nullableFiniteNumber(value: unknown, field: string): number | null {
  if (value === null) return null
  return finiteNumber(value, field)
}

function strictBoolean(value: unknown, field: string): boolean {
  if (typeof value !== 'boolean') {
    throw new PlaceDetailProtocolError(`${field} 必须是布尔值`)
  }
  return value
}

function isoTimestamp(value: unknown, field: string): string {
  const text = nonEmptyString(value, field)
  if (!/^\d{4}-\d{2}-\d{2}T/.test(text) || Number.isNaN(Date.parse(text))) {
    throw new PlaceDetailProtocolError(`${field} 必须是 ISO 日期时间`)
  }
  return text
}

function nullableIsoTimestamp(value: unknown, field: string): string | null {
  if (value === null) return null
  return isoTimestamp(value, field)
}

function parseNameSource(value: unknown): PlaceNameSource {
  if (value === 'USER' || value === 'AUTOMATIC' || value === 'UNNAMED') return value
  throw new PlaceDetailProtocolError('place.name_source 非法')
}

export function parsePlace(value: unknown): PlaceRead {
  const data = record(value, 'place')
  return {
    id: nonEmptyString(data.id, 'place.id'),
    name: nonEmptyString(data.name, 'place.name'),
    automatic_name: nullableString(data.automatic_name, 'place.automatic_name'),
    automatic_name_source: nullableString(data.automatic_name_source, 'place.automatic_name_source'),
    user_name: nullableString(data.user_name, 'place.user_name'),
    name_source: parseNameSource(data.name_source),
    name_revision: nonNegativeInteger(data.name_revision, 'place.name_revision'),
    name_updated_at: nullableIsoTimestamp(data.name_updated_at, 'place.name_updated_at'),
    latitude: nullableFiniteNumber(data.latitude, 'place.latitude'),
    longitude: nullableFiniteNumber(data.longitude, 'place.longitude'),
    address: nullableString(data.address, 'place.address'),
    category: nullableString(data.category, 'place.category'),
    first_visited_at: nullableIsoTimestamp(data.first_visited_at, 'place.first_visited_at'),
    last_visited_at: nullableIsoTimestamp(data.last_visited_at, 'place.last_visited_at'),
    visit_count: nonNegativeInteger(data.visit_count, 'place.visit_count'),
    is_user_named: strictBoolean(data.is_user_named, 'place.is_user_named'),
  }
}

export function parsePlaceList(value: unknown): PlaceRead[] {
  if (!Array.isArray(value)) throw new PlaceDetailProtocolError('places 必须是数组')
  return value.map((item) => parsePlace(item))
}

function parseVisit(value: unknown, index: number): PlaceDetailVisit {
  const data = record(value, `visits[${index}]`)
  return {
    id: nonEmptyString(data.id, `visits[${index}].id`),
    arrived_at: isoTimestamp(data.arrived_at, `visits[${index}].arrived_at`),
    left_at: nullableIsoTimestamp(data.left_at, `visits[${index}].left_at`),
    duration_seconds: nullableNonNegativeInteger(data.duration_seconds, `visits[${index}].duration_seconds`),
    confidence: finiteNumber(data.confidence, `visits[${index}].confidence`),
    source: nonEmptyString(data.source, `visits[${index}].source`),
    finalized_at: nullableIsoTimestamp(data.finalized_at, `visits[${index}].finalized_at`),
    visit_finalized: strictBoolean(data.visit_finalized, `visits[${index}].visit_finalized`),
  }
}

function parseCursor(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !value.trim()) {
    throw new PlaceDetailProtocolError('next_cursor 必须是非空字符串或 null')
  }
  return value
}

export function parsePlaceDetail(value: unknown): PlaceDetailPage {
  const data = record(value, 'response')
  if (!Array.isArray(data.visits)) throw new PlaceDetailProtocolError('visits 必须是数组')
  // 小程序与 Flutter 使用相同可信展示边界：Place、整页 Visit 与 cursor 全部验证成功后，
  // 页面才允许一次性提交状态，避免 malformed response 产生部分可信 UI。
  return {
    place: parsePlace(data.place),
    visits: data.visits.map((item, index) => parseVisit(item, index)),
    next_cursor: parseCursor(data.next_cursor),
  }
}

export function assertPlaceDetailIdentity(page: PlaceDetailPage, expectedPlaceId: string): PlaceDetailPage {
  const normalized = expectedPlaceId.trim()
  if (!normalized || page.place.id !== normalized) {
    throw new PlaceDetailProtocolError('地点详情返回了不同的地点身份')
  }
  return page
}

export function mergePlaceDetailPages(current: PlaceDetailPage, next: PlaceDetailPage): PlaceDetailPage {
  if (current.place.id !== next.place.id) {
    throw new PlaceDetailProtocolError('分页返回了不同的地点')
  }
  return {
    place: next.place,
    visits: [...current.visits, ...next.visits],
    next_cursor: next.next_cursor,
  }
}

export function buildPlacesPath(limit = 25): string {
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
    throw new RangeError('place limit must be 1..500')
  }
  return `/location/places?limit=${limit}`
}

export function buildPlaceDetailPath(placeId: string, limit = 20, cursor?: string | null): string {
  const normalized = placeId.trim()
  if (!normalized) throw new Error('place ID must not be empty')
  if (!Number.isInteger(limit) || limit < 1 || limit > 200) {
    throw new RangeError('visit limit must be 1..200')
  }
  const normalizedCursor = cursor?.trim()
  const cursorQuery = normalizedCursor ? `&cursor=${encodeURIComponent(normalizedCursor)}` : ''
  return `/location/places/${encodeURIComponent(normalized)}?limit=${limit}${cursorQuery}`
}

export function placeDetailRoute(placeId: string): string {
  const normalized = placeId.trim()
  if (!normalized) throw new Error('place ID must not be empty')
  return `/pages/place-detail/index?placeId=${encodeURIComponent(normalized)}`
}


export type PlaceListPresentation = {
  message: string | null
  showRetry: boolean
}

export function placeListPresentation(input: {
  loading: boolean
  loaded: boolean
  authenticated: boolean
  placeCount: number
  error: string
}): PlaceListPresentation {
  if (input.loading) return { message: '正在加载地点…', showRetry: false }
  if (!input.authenticated) return { message: '登录后可查看你的地点记录', showRetry: false }
  if (input.error) return { message: input.error, showRetry: true }
  if (input.loaded && input.placeCount === 0) {
    return { message: '还没有地点记录', showRetry: false }
  }
  return { message: null, showRetry: false }
}
