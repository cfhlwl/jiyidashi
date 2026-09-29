import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8')
}

const appConfig = source('src/app.config.ts')
const appScss = source('src/app.scss')
const tokens = source('src/styles/_tokens.scss')
const productUi = source('src/components/product/ProductUi.tsx')
const today = source('src/pages/index/index.tsx')
const query = source('src/pages/query/index.tsx')
const life = source('src/pages/life/index.tsx')
const family = source('src/pages/family/index.tsx')
const profile = source('src/pages/profile/index.tsx')

test('Product Experience V2 top-level IA uses five human domains and keeps capture global', () => {
  for (const [path, label] of [
    ['pages/index/index', '今天'],
    ['pages/query/index', '记忆'],
    ['pages/life/index', '人生'],
    ['pages/family/index', '家庭'],
    ['pages/profile/index', '我的'],
  ]) {
    assert.match(appConfig, new RegExp(`pagePath: '${path}', text: '${label}'`))
  }
  assert.doesNotMatch(appConfig, /pagePath: 'pages\/capture\/index', text: '记一下'/)
  assert.match(productUi, /navigateTo\(\{ url: '\/pages\/capture\/index' \}\)/)
  assert.doesNotMatch(today, /switchTab\(\{ url: '\/pages\/capture\/index' \}\)/)
  assert.match(today, /switchTab\(\{ url: '\/pages\/life\/index' \}\)/)
})

test('Mini V2 shell consumes one semantic token source and calm blue primary action', () => {
  for (const token of [
    '$jiyi-brand-primary',
    '$jiyi-background',
    '$jiyi-surface',
    '$jiyi-surface-elevated',
    '$jiyi-surface-soft',
    '$jiyi-text-primary',
    '$jiyi-text-secondary',
    '$jiyi-text-tertiary',
    '$jiyi-border',
    '$jiyi-divider',
    '$jiyi-action-primary',
    '$jiyi-action-secondary',
    '$jiyi-success',
    '$jiyi-warning',
    '$jiyi-error',
    '$jiyi-info',
    '$jiyi-ai',
    '$jiyi-family',
    '$jiyi-location',
    '$jiyi-media',
  ]) {
    assert.ok(tokens.includes(token), `missing design token: ${token}`)
  }
  assert.match(tokens, /\$jiyi-action-primary: #356a9a/)
  assert.match(appScss, /@import '\.\/styles\/tokens'/)
  assert.doesNotMatch(appScss, /#446a57/i)
})

test('flagship tab surfaces use shared editorial hierarchy and global capture where applicable', () => {
  for (const page of [today, query, life, profile]) assert.match(page, /ProductHeroHeader/)
  for (const page of [today, query, life, profile]) assert.match(page, /FloatingCaptureAction/)
  assert.match(family, /ProductHeroHeader/)
})

test('migrated product surfaces do not expose known implementation vocabulary', () => {
  assert.doesNotMatch(today, /V1 基础能力|服务端已经派生出的 Visit/)
  assert.doesNotMatch(query, /记忆 ID：|当前版本：|证据类型：|修订版 \$\{/)
  assert.doesNotMatch(life, /服务端范围：|游标按原值续传|as_of \{history\.as_of\}/)
  assert.doesNotMatch(life, />Memory \{shortId|>Stage \{shortId|>Event \{shortId|>Visit \{shortId/)
  assert.doesNotMatch(life, /\{evidence\.source_type\} · \{evidence\.occurred_at\}/)
  assert.doesNotMatch(family, /\{memory\.memory_type\} · \{memory\.source_type\}/)
})

test('AI references are human-facing reference records, not internal slots or ids', () => {
  assert.match(life, /参考记录 \{index \+ 1\}/)
  assert.doesNotMatch(life, /\{citation\.slot\} · \{citation\.kind\}/)
  assert.doesNotMatch(life, /Memory \{shortId\(citation\.memory_id\)\}/)
  assert.doesNotMatch(life, /Stage \{shortId\(citation\.life_stage_id\)\}/)
})
