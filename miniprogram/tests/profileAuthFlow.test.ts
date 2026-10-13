import assert from 'node:assert/strict'
import test from 'node:test'
import { runProfileLogout, runProfileSubmit } from '../src/pages/profile/profileAuthFlow'

function token(id: string) {
  return {
    access_token: `access-${id}`,
    refresh_token: `refresh-${id}`,
    session_id: `session-${id}`,
    token_type: 'bearer' as const,
    user_id: `user-${id}`,
    access_expires_at: '2099-01-01T00:00:00Z',
    refresh_expires_at: '2099-02-01T00:00:00Z',
    account_deletion_in_progress: false,
  }
}

test('Profile login password error clears busy state and permits a second attempt', async () => {
  let generation = 0
  let currentOperation: object | null = null
  let loginCalls = 0
  const state = { loading: false, status: '' }
  const run = () => runProfileSubmit({
    registerMode: false,
    email: 'user@example.com',
    password: 'wrong-password',
    nickname: '',
    beginOperation: () => {
      const operation = { generation: ++generation }
      currentOperation = operation
      return operation
    },
    operationIsCurrent: (operation) => operation === currentOperation,
    registerAccount: async () => ({ user_id: 'unused', verification_required: true, verification_delivery_pending: false }),
    loginAccount: async () => {
      loginCalls += 1
      throw new Error('密码错误')
    },
    refreshProfile: async () => undefined,
    setLoading: (value) => { state.loading = value },
    setStatus: (value) => { state.status = value },
    setVerificationPendingEmail: () => undefined,
  })

  await run()
  assert.equal(loginCalls, 1)
  assert.equal(state.loading, false)
  assert.equal(state.status, '密码错误')
  await run()
  assert.equal(loginCalls, 2)
  assert.equal(state.loading, false)
})

test('Profile stale login completion cannot clear the newer account busy state', async () => {
  let generation = 0
  let currentOperation: object | null = null
  let rejectOld!: (error: Error) => void
  const state = { loading: false, status: 'B 正在登录' }
  const oldRun = runProfileSubmit({
    registerMode: false,
    email: 'a@example.com',
    password: 'password-a',
    nickname: '',
    beginOperation: () => {
      const operation = { generation: ++generation }
      currentOperation = operation
      return operation
    },
    operationIsCurrent: (operation) => operation === currentOperation,
    registerAccount: async () => ({ user_id: 'unused', verification_required: true, verification_delivery_pending: false }),
    loginAccount: () => new Promise((_resolve, reject) => { rejectOld = reject }),
    refreshProfile: async () => undefined,
    setLoading: (value) => { state.loading = value },
    setStatus: (value) => { state.status = value },
    setVerificationPendingEmail: () => undefined,
  })
  await Promise.resolve()
  currentOperation = { generation: ++generation }
  state.loading = true
  state.status = 'B 正在登录'
  rejectOld(new Error('A-only failure'))
  await oldRun
  assert.deepEqual(state, { loading: true, status: 'B 正在登录' })
})

test('Profile logout result cannot overwrite a newer account', async () => {
  let generation = 0
  let currentGeneration = 0
  let authenticated = true
  let resolveLogout!: (value: Awaited<ReturnType<typeof fakeLogout>>) => void
  const state = { status: 'B 已登录', profile: 'B' as string | null }
  const fakeLogout = async () => ({ localCleared: true as const, serverRevoked: false, serverStatus: 'UNCONFIRMED' as const })
  const pending = runProfileLogout({
    beginViewGeneration: () => { currentGeneration = ++generation; return currentGeneration },
    isViewGenerationCurrent: (value) => value === currentGeneration,
    logout: () => new Promise((resolve) => { resolveLogout = resolve }),
    isAuthenticated: () => authenticated,
    setProfile: (value) => { state.profile = value === null ? null : state.profile },
    setPrivacy: () => undefined,
    clearForm: () => undefined,
    setStatus: (value) => { state.status = value },
  })
  currentGeneration = ++generation
  authenticated = true
  resolveLogout(await fakeLogout())
  await pending
  assert.deepEqual(state, { status: 'B 已登录', profile: null })
})
