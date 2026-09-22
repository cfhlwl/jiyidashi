import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  parseAnnualTrustedSummary,
  parseDailyTrustedSummary,
  parseMonthlyTrustedSummary,
  trustedSummaryCitationLabel,
  trustedSummaryStatusMessage,
  trustedSummaryTrustLabel,
  TrustedSummaryGenerationGate,
  TRUSTED_SUMMARY_STATUS,
} from '../src/services/memorySummaries'

const MEMORY_ID = '11111111-1111-4111-8111-111111111111'
const VISIT_ID = '22222222-2222-4222-8222-222222222222'

function dailyReady() {
  return {
    status: 'DAILY_SUMMARY_READY',
    day: '2026-09-22',
    timezone: 'Asia/Shanghai',
    summary: '今天完成了可信回忆整理。',
    citations: [{
      slot: 'D1',
      kind: 'MEMORY',
      memory_id: MEMORY_ID,
      visit_id: null,
      trust_state: 'CONFIRMED',
    }],
  }
}

test('daily trusted summary parser accepts strict public READY contract', () => {
  const result = parseDailyTrustedSummary(dailyReady())
  assert.equal(result.period, 'daily')
  assert.equal(result.day, '2026-09-22')
  assert.equal(result.summary, '今天完成了可信回忆整理。')
  assert.equal(result.citations[0].memory_id, MEMORY_ID)
})

test('monthly and annual parsers keep period identity and citation kind strict', () => {
  const monthly = parseMonthlyTrustedSummary({
    status: 'MONTHLY_SUMMARY_READY',
    target_month: '2026-09',
    timezone: 'Asia/Shanghai',
    summary: '本月回忆。',
    citations: [{
      slot: 'M1',
      kind: 'VISIT',
      memory_id: null,
      visit_id: VISIT_ID,
      trust_state: null,
    }],
  })
  const annual = parseAnnualTrustedSummary({
    status: 'ANNUAL_SUMMARY_READY',
    target_year: '2026',
    timezone: 'Asia/Shanghai',
    summary: '年度回忆。',
    citations: [{
      slot: 'Y1',
      kind: 'MEMORY',
      memory_id: MEMORY_ID,
      visit_id: null,
      trust_state: 'EVIDENCE_SUPPORTED',
    }],
  })

  assert.equal(monthly.target_month, '2026-09')
  assert.equal(monthly.citations[0].kind, 'VISIT')
  assert.equal(annual.target_year, '2026')
  assert.equal(annual.citations[0].trust_state, 'EVIDENCE_SUPPORTED')
})

test('runtime parser rejects internal/provider fields instead of silently accepting leaks', () => {
  assert.throws(
    () => parseDailyTrustedSummary({
      ...dailyReady(),
      provider_request_id: 'must-not-leak',
    }),
    /回忆总结数据异常/,
  )
  assert.throws(
    () => parseDailyTrustedSummary({
      ...dailyReady(),
      citations: [{
        ...dailyReady().citations[0],
        memory_source_id: '33333333-3333-4333-8333-333333333333',
      }],
    }),
    /回忆总结数据异常/,
  )
})

test('unknown status, wrong READY family and fake non-ready summary fail closed', () => {
  assert.throws(
    () => parseDailyTrustedSummary({ ...dailyReady(), status: 'FUTURE_UNKNOWN' }),
    /回忆总结数据异常/,
  )
  assert.throws(
    () => parseMonthlyTrustedSummary({
      ...dailyReady(),
      status: 'DAILY_SUMMARY_READY',
      target_month: '2026-09',
      day: undefined,
    }),
    /回忆总结数据异常/,
  )
  assert.throws(
    () => parseDailyTrustedSummary({
      ...dailyReady(),
      status: 'NO_SUMMARIZABLE_EVIDENCE',
      summary: '伪造成功总结',
      citations: [],
    }),
    /回忆总结数据异常/,
  )
})

test('malformed period, timezone and citation identity fail closed', () => {
  assert.throws(
    () => parseDailyTrustedSummary({ ...dailyReady(), day: '2026-02-30' }),
    /回忆总结数据异常/,
  )
  assert.throws(
    () => parseMonthlyTrustedSummary({
      status: 'NO_SUMMARIZABLE_EVIDENCE',
      target_month: '2026-13',
      timezone: 'Asia/Shanghai',
      summary: null,
      citations: [],
    }),
    /回忆总结数据异常/,
  )
  assert.throws(
    () => parseAnnualTrustedSummary({
      status: 'NO_SUMMARIZABLE_EVIDENCE',
      target_year: '9999',
      timezone: 'Asia/Shanghai',
      summary: null,
      citations: [],
    }),
    /回忆总结数据异常/,
  )
  assert.throws(
    () => parseDailyTrustedSummary({ ...dailyReady(), timezone: '' }),
    /回忆总结数据异常/,
  )
  assert.throws(
    () => parseDailyTrustedSummary({
      ...dailyReady(),
      citations: [{
        ...dailyReady().citations[0],
        memory_id: 'not-a-uuid',
      }],
    }),
    /回忆总结数据异常/,
  )
})

test('Memory trust citation only accepts trusted server-owned labels', () => {
  assert.throws(
    () => parseDailyTrustedSummary({
      ...dailyReady(),
      citations: [{
        ...dailyReady().citations[0],
        trust_state: 'NO_EVIDENCE',
      }],
    }),
    /回忆总结数据异常/,
  )
  assert.equal(trustedSummaryTrustLabel('CONFIRMED'), '已确认')
  assert.equal(trustedSummaryTrustLabel('EVIDENCE_SUPPORTED'), '有证据支持')
})

test('non-ready status UX remains deliberate and provider-safe', () => {
  assert.equal(
    trustedSummaryStatusMessage(TRUSTED_SUMMARY_STATUS.NO_EVIDENCE),
    '这一时间段还没有足够的可信记录',
  )
  assert.equal(
    trustedSummaryStatusMessage(TRUSTED_SUMMARY_STATUS.INCOMPLETE),
    '记录较多或暂时无法完整总结，请稍后再试',
  )
  assert.equal(
    trustedSummaryStatusMessage(TRUSTED_SUMMARY_STATUS.DATA_CHANGED),
    '生成期间记录发生变化，请重新生成',
  )
  for (const status of [
    TRUSTED_SUMMARY_STATUS.PROVIDER_FAILED,
    TRUSTED_SUMMARY_STATUS.MALFORMED_PROVIDER_OUTPUT,
    TRUSTED_SUMMARY_STATUS.INVALID_CITATION,
  ]) {
    assert.equal(
      trustedSummaryStatusMessage(status),
      'AI 总结暂时生成失败，请稍后重试',
    )
  }
})

test('summary generation gate rejects rapid duplicate requests until completion', () => {
  const gate = new TrustedSummaryGenerationGate()
  assert.equal(gate.begin(), true)
  assert.equal(gate.isPending(), true)
  assert.equal(gate.begin(), false)
  gate.end()
  assert.equal(gate.isPending(), false)
  assert.equal(gate.begin(), true)
})

test('citation labels explain grounded evidence without confidence invention', () => {
  const parsed = parseDailyTrustedSummary(dailyReady())
  assert.equal(trustedSummaryCitationLabel(parsed.citations[0]), '记忆证据')
  const visit = parseMonthlyTrustedSummary({
    status: 'MONTHLY_SUMMARY_READY',
    target_month: '2026-09',
    timezone: 'Asia/Shanghai',
    summary: '本月回忆。',
    citations: [{
      slot: 'M1',
      kind: 'VISIT',
      memory_id: null,
      visit_id: VISIT_ID,
      trust_state: null,
    }],
  })
  assert.equal(trustedSummaryCitationLabel(visit.citations[0]), '足迹证据')
})

test('summary page never generates on mount/show and all generation calls live behind explicit handler', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/summaries/index.tsx'), 'utf8')
  assert.doesNotMatch(page, /useDidShow|useEffect|setInterval|setTimeout/)
  assert.match(page, /onClick=\{generate\}/)
  assert.match(page, /const generationGate = useRef\(new TrustedSummaryGenerationGate\(\)\)/)
  assert.match(page, /if \(generationGate\.current\.isPending\(\) \|\| next === period\) return/)
  assert.match(page, /if \(!generationGate\.current\.begin\(\)\) return/)
  assert.match(page, /finally \{[\s\S]*?generationGate\.current\.end\(\)/)

  const start = page.indexOf('  const generate = async')
  const end = page.indexOf('  const copy =', start)
  assert.notEqual(start, -1)
  assert.notEqual(end, -1)
  const handler = page.slice(start, end)
  const outside = page.slice(0, start) + page.slice(end)

  for (const call of [
    'generateDailyTrustedSummary()',
    'generateMonthlyTrustedSummary()',
    'generateAnnualTrustedSummary()',
  ]) {
    assert.match(handler, new RegExp(call.replace(/[()]/g, '\\$&')))
    assert.doesNotMatch(outside, new RegExp(call.replace(/[()]/g, '\\$&')))
  }
  assert.match(page, /catch \{[\s\S]*?回忆总结生成失败，请稍后重试/)
})

test('shared API maps Daily Monthly Annual to dedicated POST routes only', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /request<unknown>\('POST', '\/memory\/summaries\/daily', \{\}\)/)
  assert.match(api, /'POST',[\s\S]*?'\/memory\/summaries\/monthly'/)
  assert.match(api, /'POST',[\s\S]*?'\/memory\/summaries\/annual'/)
  assert.doesNotMatch(api, /memory\/summaries\/daily[^\n]*GET/)
})

test('Today only navigates to summaries and app keeps summaries out of bottom tab', () => {
  const today = readFileSync(resolve(process.cwd(), 'src/pages/index/index.tsx'), 'utf8')
  const appConfig = readFileSync(resolve(process.cwd(), 'src/app.config.ts'), 'utf8')

  assert.match(today, /navigateTo\(\{ url: '\/pages\/summaries\/index' \}\)/)
  assert.doesNotMatch(
    today,
    /generateDailyTrustedSummary|generateMonthlyTrustedSummary|generateAnnualTrustedSummary/,
  )
  assert.match(appConfig, /'pages\/summaries\/index'/)

  const tabBar = appConfig.slice(appConfig.indexOf('tabBar:'))
  assert.doesNotMatch(tabBar, /pagePath: 'pages\/summaries\/index'/)
})
