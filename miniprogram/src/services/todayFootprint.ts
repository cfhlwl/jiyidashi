export type TodayFootprintVisit = {
  id: string
  place_id: string
  place_name: string
  arrived_at: string
  left_at: string | null
  arrived_at_local: string
  left_at_local: string | null
  confidence: number
  visit_source: string
  visit_finalized: boolean
}

export type TodayFootprintResponse = {
  timezone: string
  day: string
  visits: TodayFootprintVisit[]
}

export type TodayFootprintRow = {
  id: string
  placeName: string
  timeRange: string
  stateLabel: string
  source: string
}

type JsonRecord = Record<string, unknown>

const ISO_DATE_TIME =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/

function invalidResponse(): never {
  // [人工注释][S2-012] malformed 200 与 HTTP 失败一样必须 fail-closed；
  // 页面 refresh() 会捕获该异常、清空 footprint，并展示错误 + 重试入口。
  throw new Error('今日足迹数据异常')
}

function asRecord(value: unknown): JsonRecord {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return invalidResponse()
  }
  return value as JsonRecord
}

function nonEmptyString(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return invalidResponse()
  return value
}

function validDateOnly(value: unknown): string {
  const text = nonEmptyString(value)
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text)
  if (!match) return invalidResponse()

  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const date = new Date(Date.UTC(year, month - 1, day))
  if (
    !Number.isFinite(date.getTime()) ||
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return invalidResponse()
  }
  return text
}

function validIsoDateTime(value: unknown): string {
  if (typeof value !== 'string' || !ISO_DATE_TIME.test(value)) {
    return invalidResponse()
  }
  // [人工注释][S2-012] Date.parse() 会把 2026-02-30 等不存在日期自动归一化；
  // 先复用 YYYY-MM-DD 的真实日历校验，再验证完整 ISO datetime。
  validDateOnly(value.slice(0, 10))
  if (!Number.isFinite(Date.parse(value))) return invalidResponse()
  return value
}

function nullableIsoDateTime(value: unknown): string | null {
  if (value === null) return null
  return validIsoDateTime(value)
}

function finiteNumber(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return invalidResponse()
  }
  return value
}

function strictBoolean(value: unknown): boolean {
  if (typeof value !== 'boolean') return invalidResponse()
  return value
}

function parseVisit(value: unknown): TodayFootprintVisit {
  const raw = asRecord(value)
  return {
    id: nonEmptyString(raw.id),
    place_id: nonEmptyString(raw.place_id),
    place_name: nonEmptyString(raw.place_name),
    arrived_at: validIsoDateTime(raw.arrived_at),
    left_at: nullableIsoDateTime(raw.left_at),
    arrived_at_local: validIsoDateTime(raw.arrived_at_local),
    left_at_local: nullableIsoDateTime(raw.left_at_local),
    confidence: finiteNumber(raw.confidence),
    visit_source: nonEmptyString(raw.visit_source),
    visit_finalized: strictBoolean(raw.visit_finalized),
  }
}

export function parseTodayFootprintResponse(value: unknown): TodayFootprintResponse {
  const raw = asRecord(value)
  const visits = raw.visits
  if (!Array.isArray(visits)) return invalidResponse()

  return {
    timezone: nonEmptyString(raw.timezone),
    day: validDateOnly(raw.day),
    visits: visits.map(parseVisit),
  }
}

function wallClock(serverLocalIso: string): string {
  // [人工注释][S2-012] local timestamp 已由服务端按账号 IANA timezone 计算；
  // parser 已先验证 ISO datetime；这里只提取 HH:mm，禁止设备时区二次改写。
  const match = /T(\d{2}):(\d{2})/.exec(serverLocalIso)
  if (!match) throw new Error('TODAY_FOOTPRINT_LOCAL_TIME_INVALID')
  return `${match[1]}:${match[2]}`
}

export function toTodayFootprintRow(visit: TodayFootprintVisit): TodayFootprintRow {
  const start = wallClock(visit.arrived_at_local)
  const end = visit.left_at_local ? wallClock(visit.left_at_local) : null
  return {
    id: visit.id,
    placeName: visit.place_name,
    timeRange: end ? `${start} - ${end}` : `${start} 起`,
    stateLabel: visit.visit_finalized ? '已形成足迹' : '进行中',
    source: visit.visit_source,
  }
}
