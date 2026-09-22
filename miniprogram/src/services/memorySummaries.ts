export type TrustedSummaryPeriod = 'daily' | 'monthly' | 'annual'

export const TRUSTED_SUMMARY_STATUS = {
  DAILY_READY: 'DAILY_SUMMARY_READY',
  MONTHLY_READY: 'MONTHLY_SUMMARY_READY',
  ANNUAL_READY: 'ANNUAL_SUMMARY_READY',
  NO_EVIDENCE: 'NO_SUMMARIZABLE_EVIDENCE',
  INCOMPLETE: 'SUMMARY_INCOMPLETE',
  PROVIDER_FAILED: 'PROVIDER_FAILED',
  MALFORMED_PROVIDER_OUTPUT: 'MALFORMED_PROVIDER_OUTPUT',
  INVALID_CITATION: 'INVALID_CITATION',
  DATA_CHANGED: 'DATA_CHANGED_DURING_GENERATION',
} as const

export type TrustedSummaryStatus =
  (typeof TRUSTED_SUMMARY_STATUS)[keyof typeof TRUSTED_SUMMARY_STATUS]

export type TrustedSummaryCitationKind = 'MEMORY' | 'VISIT'
export type TrustedSummaryTrustState = 'CONFIRMED' | 'EVIDENCE_SUPPORTED'

export type TrustedSummaryCitation = {
  slot: string
  kind: TrustedSummaryCitationKind
  memory_id: string | null
  visit_id: string | null
  trust_state: TrustedSummaryTrustState | null
}

type TrustedSummaryBase = {
  status: TrustedSummaryStatus
  timezone: string
  summary: string | null
  citations: TrustedSummaryCitation[]
}

export type DailyTrustedSummary = TrustedSummaryBase & {
  period: 'daily'
  day: string
}

export type MonthlyTrustedSummary = TrustedSummaryBase & {
  period: 'monthly'
  target_month: string
}

export type AnnualTrustedSummary = TrustedSummaryBase & {
  period: 'annual'
  target_year: string
}

export type TrustedSummaryResult =
  | DailyTrustedSummary
  | MonthlyTrustedSummary
  | AnnualTrustedSummary

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const NON_READY_STATUSES = new Set<string>([
  TRUSTED_SUMMARY_STATUS.NO_EVIDENCE,
  TRUSTED_SUMMARY_STATUS.INCOMPLETE,
  TRUSTED_SUMMARY_STATUS.PROVIDER_FAILED,
  TRUSTED_SUMMARY_STATUS.MALFORMED_PROVIDER_OUTPUT,
  TRUSTED_SUMMARY_STATUS.INVALID_CITATION,
  TRUSTED_SUMMARY_STATUS.DATA_CHANGED,
])

function invalidSummary(): never {
  throw new Error('回忆总结数据异常')
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return invalidSummary()
  return value as Record<string, unknown>
}

function exactKeys(raw: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(raw).sort()
  const wanted = [...expected].sort()
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    invalidSummary()
  }
}

function nonEmptyString(value: unknown, maxLength: number): string {
  if (typeof value !== 'string') return invalidSummary()
  const normalized = value.trim()
  if (!normalized || normalized.length > maxLength) return invalidSummary()
  return normalized
}

function uuidOrNull(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !UUID_RE.test(value)) return invalidSummary()
  return value
}

function isLeapYear(year: number): boolean {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
}

function daysInMonth(year: number, month: number): number {
  if (month === 2) return isLeapYear(year) ? 29 : 28
  return [4, 6, 9, 11].includes(month) ? 30 : 31
}

function strictDay(value: unknown): string {
  if (typeof value !== 'string') return invalidSummary()
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return invalidSummary()
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (
    year < 1
    || month < 1
    || month > 12
    || day < 1
    || day > daysInMonth(year, month)
  ) {
    return invalidSummary()
  }
  return value
}

function strictMonth(value: unknown): string {
  if (typeof value !== 'string') return invalidSummary()
  const match = /^(\d{4})-(\d{2})$/.exec(value)
  if (!match) return invalidSummary()
  const year = Number(match[1])
  const month = Number(match[2])
  if (year < 1 || month < 1 || month > 12) return invalidSummary()
  return value
}

function strictYear(value: unknown): string {
  if (typeof value !== 'string' || !/^\d{4}$/.test(value)) return invalidSummary()
  const year = Number(value)
  if (year < 1 || year >= 9999) return invalidSummary()
  return value
}

function timezone(value: unknown): string {
  return nonEmptyString(value, 64)
}

function expectedReadyStatus(period: TrustedSummaryPeriod): TrustedSummaryStatus {
  if (period === 'daily') return TRUSTED_SUMMARY_STATUS.DAILY_READY
  if (period === 'monthly') return TRUSTED_SUMMARY_STATUS.MONTHLY_READY
  return TRUSTED_SUMMARY_STATUS.ANNUAL_READY
}

function parseStatus(value: unknown, period: TrustedSummaryPeriod): TrustedSummaryStatus {
  if (value === expectedReadyStatus(period)) return value as TrustedSummaryStatus
  if (typeof value === 'string' && NON_READY_STATUSES.has(value)) {
    return value as TrustedSummaryStatus
  }
  return invalidSummary()
}

function parseCitation(
  value: unknown,
  slotPrefix: 'D' | 'M' | 'Y',
): TrustedSummaryCitation {
  const raw = asRecord(value)
  exactKeys(raw, ['slot', 'kind', 'memory_id', 'visit_id', 'trust_state'])

  const slot = nonEmptyString(raw.slot, 32)
  if (!new RegExp(`^${slotPrefix}[1-9]\\d*$`).test(slot)) return invalidSummary()

  if (raw.kind !== 'MEMORY' && raw.kind !== 'VISIT') return invalidSummary()
  const memoryId = uuidOrNull(raw.memory_id)
  const visitId = uuidOrNull(raw.visit_id)

  if (raw.kind === 'MEMORY') {
    if (memoryId === null || visitId !== null) return invalidSummary()
    if (raw.trust_state !== 'CONFIRMED' && raw.trust_state !== 'EVIDENCE_SUPPORTED') {
      return invalidSummary()
    }
    return {
      slot,
      kind: 'MEMORY',
      memory_id: memoryId,
      visit_id: null,
      trust_state: raw.trust_state,
    }
  }

  if (memoryId !== null || visitId === null || raw.trust_state !== null) {
    return invalidSummary()
  }
  return {
    slot,
    kind: 'VISIT',
    memory_id: null,
    visit_id: visitId,
    trust_state: null,
  }
}

function parseBody(
  value: unknown,
  period: TrustedSummaryPeriod,
  periodKey: 'day' | 'target_month' | 'target_year',
  slotPrefix: 'D' | 'M' | 'Y',
): TrustedSummaryBase & Record<string, unknown> {
  const raw = asRecord(value)
  exactKeys(raw, ['status', periodKey, 'timezone', 'summary', 'citations'])

  const status = parseStatus(raw.status, period)
  const ready = status === expectedReadyStatus(period)
  if (!Array.isArray(raw.citations)) return invalidSummary()
  const citations = raw.citations.map((item) => parseCitation(item, slotPrefix))
  if (new Set(citations.map((item) => item.slot)).size !== citations.length) {
    return invalidSummary()
  }

  let summary: string | null
  if (ready) {
    summary = nonEmptyString(raw.summary, 8000)
    if (citations.length === 0) return invalidSummary()
  } else {
    if (raw.summary !== null || citations.length !== 0) return invalidSummary()
    summary = null
  }

  return {
    status,
    timezone: timezone(raw.timezone),
    summary,
    citations,
    [periodKey]: raw[periodKey],
  }
}

export function parseDailyTrustedSummary(value: unknown): DailyTrustedSummary {
  const parsed = parseBody(value, 'daily', 'day', 'D')
  return {
    period: 'daily',
    status: parsed.status,
    day: strictDay(parsed.day),
    timezone: parsed.timezone,
    summary: parsed.summary,
    citations: parsed.citations,
  }
}

export function parseMonthlyTrustedSummary(value: unknown): MonthlyTrustedSummary {
  const parsed = parseBody(value, 'monthly', 'target_month', 'M')
  return {
    period: 'monthly',
    status: parsed.status,
    target_month: strictMonth(parsed.target_month),
    timezone: parsed.timezone,
    summary: parsed.summary,
    citations: parsed.citations,
  }
}

export function parseAnnualTrustedSummary(value: unknown): AnnualTrustedSummary {
  const parsed = parseBody(value, 'annual', 'target_year', 'Y')
  return {
    period: 'annual',
    status: parsed.status,
    target_year: strictYear(parsed.target_year),
    timezone: parsed.timezone,
    summary: parsed.summary,
    citations: parsed.citations,
  }
}

export function isReadySummary(result: TrustedSummaryResult): boolean {
  return result.status === expectedReadyStatus(result.period)
}

export class TrustedSummaryGenerationGate {
  private pending = false

  begin(): boolean {
    if (this.pending) return false
    this.pending = true
    return true
  }

  end(): void {
    this.pending = false
  }

  isPending(): boolean {
    return this.pending
  }
}

export function trustedSummaryStatusMessage(status: TrustedSummaryStatus): string {
  switch (status) {
    case TRUSTED_SUMMARY_STATUS.NO_EVIDENCE:
      return '这一时间段还没有足够的可信记录'
    case TRUSTED_SUMMARY_STATUS.INCOMPLETE:
      return '记录较多或暂时无法完整总结，请稍后再试'
    case TRUSTED_SUMMARY_STATUS.DATA_CHANGED:
      return '生成期间记录发生变化，请重新生成'
    case TRUSTED_SUMMARY_STATUS.PROVIDER_FAILED:
    case TRUSTED_SUMMARY_STATUS.MALFORMED_PROVIDER_OUTPUT:
    case TRUSTED_SUMMARY_STATUS.INVALID_CITATION:
      return 'AI 总结暂时生成失败，请稍后重试'
    default:
      return ''
  }
}

export function trustedSummaryTrustLabel(
  state: TrustedSummaryTrustState | null,
): string {
  if (state === 'CONFIRMED') return '已确认'
  if (state === 'EVIDENCE_SUPPORTED') return '有证据支持'
  return ''
}

export function trustedSummaryCitationLabel(
  citation: TrustedSummaryCitation,
): string {
  return citation.kind === 'MEMORY' ? '记忆证据' : '足迹证据'
}

export function trustedSummaryPeriodIdentity(result: TrustedSummaryResult): string {
  if (result.period === 'daily') return result.day
  if (result.period === 'monthly') return result.target_month
  return result.target_year
}
