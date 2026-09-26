import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ElderFindQueryEpoch,
  ElderFindSingleFlight,
  elderFindState,
} from '../src/services/elderFindThings'
import { isDisplayableEvidence } from '../src/services/memoryFeedback'

const queryPage = readFileSync(resolve(process.cwd(), 'src/pages/query/index.tsx'), 'utf8')
const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')

test('elder find things is presentation over existing queryMemory seam', () => {
  assert.match(queryPage, /elderMode \? '我想找东西' : '问记忆'/)
  assert.match(queryPage, /queryMemory\(submitted\)/)
  assert.match(queryPage, /elderMode \? '帮我找'/)
  assert.doesNotMatch(queryPage, /\/elder\/(?:find|query)/)
  assert.doesNotMatch(queryPage, /rememberObjectLocation\(|markObjectLocationStale\(/)
  assert.doesNotMatch(queryPage, /getRecorderManager|chooseMedia|getLocation/)
})

test('elder no-answer presentation is explicit no-guess state', () => {
  assert.match(queryPage, /我还不知道它在哪里。/)
  assert.match(queryPage, /没有找到足够可靠的记录/)
  assert.doesNotMatch(queryPage, /可能在|应该在|大概在/)
  assert.equal(elderFindState({ loading: false, canAnswer: false, failed: false }), 'NOT_ENOUGH_EVIDENCE')
})

test('query response parser is runtime strict and can_answer true requires answer', () => {
  assert.match(api, /function parseMemoryQueryResult\(raw: unknown\)/)
  assert.match(api, /typeof canAnswer !== 'boolean'/)
  assert.match(api, /!Array\.isArray\(evidence\)/)
  assert.match(api, /canAnswer && \(!answer \|\| !answer\.trim\(\)\)/)
  assert.match(api, /request<unknown>\('POST', '\/memory\/query'/)
})

test('AI inference remains excluded from displayable evidence', () => {
  assert.equal(isDisplayableEvidence('AI_INFERENCE'), false)
  assert.equal(isDisplayableEvidence('USER_TEXT'), true)
})

test('elder query gate is synchronous single-flight', () => {
  const gate = new ElderFindSingleFlight()
  assert.equal(gate.tryBegin(), true)
  assert.equal(gate.tryBegin(), false)
  gate.end()
  assert.equal(gate.tryBegin(), true)
})

test('stale query generation blocks late A after B generation starts', async () => {
  const epoch = new ElderFindQueryEpoch()
  const published: string[] = []
  let resolveA!: (value: string) => void
  const a = new Promise<string>((resolve) => { resolveA = resolve })
  const generationA = epoch.capture()
  const pendingA = a.then((value) => {
    if (epoch.isCurrent(generationA)) published.push(value)
  })
  const generationB = epoch.capture()
  if (epoch.isCurrent(generationB)) published.push('B')
  resolveA('A')
  await pendingA
  assert.deepEqual(published, ['B'])
})

test('auth or page invalidation blocks late query publication', async () => {
  const epoch = new ElderFindQueryEpoch()
  let published = false
  const generation = epoch.capture()
  epoch.invalidate()
  await Promise.resolve()
  if (epoch.isCurrent(generation)) published = true
  assert.equal(published, false)
})

test('query page binds response to owner auth epoch and exact submitted question', () => {
  assert.match(queryPage, /capturedOwner = authOwnerRef\.current/)
  assert.match(queryPage, /capturedAuthEpoch = authEpochRef\.current/)
  assert.match(queryPage, /capturedQueryEpoch = queryEpoch\.current\.capture\(\)/)
  assert.match(queryPage, /setSubmittedQuestion\(submitted\)/)
  assert.match(queryPage, /useDidHide\(\(\) =>/)
  assert.match(queryPage, /subscribeAuthSession\(/)
})


test('page hide invalidates pending query and clears loading gate for next query', () => {
  assert.match(
    queryPage,
    /useDidHide\(\(\) => \{[\s\S]*?queryEpoch\.current\.invalidate\(\)[\s\S]*?queryBusyRef\.current = false[\s\S]*?elderQueryGate\.current\.end\(\)[\s\S]*?setLoading\(false\)/,
  )
})
