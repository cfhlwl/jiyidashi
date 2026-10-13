import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { beginProfileAsyncOperation, isProfileAsyncOperationCurrent } from '../src/pages/profile/authFence'

const source = readFileSync('src/pages/profile/index.tsx', 'utf8')

test('Profile async publication is fenced by view generation and validated auth session', () => {
  assert.match(source, /const profileViewGeneration = useRef\(0\)/)
  assert.match(source, /const snapshot = captureAuthSession\(\)/)
  assert.match(source, /isAuthSessionCurrent\(snapshot\)/)
  assert.match(source, /viewGeneration !== profileViewGeneration\.current/)
  assert.match(source, /profileViewGeneration\.current \+= 1/)
  assert.match(source, /subscribeAuthSession\(/)
  assert.match(source, /authView\.current\.epoch === epoch/)
})

test('Profile does not use the removed legacy owner key as an authority', () => {
  assert.doesNotMatch(source, /jiyi_authenticated_user_id/)
  assert.match(source, /getProfile\(\)/)
  assert.match(source, /getPrivacyStatus\(\)/)
})

test('Profile component operation fence blocks stale success, error, and finally state commits', () => {
  const generation = { current: 0 }
  const accountA = { owner: 'user-a', epoch: 1, sessionId: 'session-a' }
  const accountB = { owner: 'user-b', epoch: 2, sessionId: 'session-b' }
  const operationA = beginProfileAsyncOperation(generation, accountA)
  const state = { status: 'B is active', loading: true }

  generation.current += 1

  assert.equal(isProfileAsyncOperationCurrent(operationA, generation.current, accountB), false)
  const commit = (fn: () => void) => {
    if (isProfileAsyncOperationCurrent(operationA, generation.current, accountB)) fn()
  }
  commit(() => { state.status = 'A error' })
  commit(() => { state.loading = false })
  assert.deepEqual(state, { status: 'B is active', loading: true })
})
