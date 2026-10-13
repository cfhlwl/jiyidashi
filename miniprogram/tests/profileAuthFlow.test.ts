import assert from 'node:assert/strict'
import test from 'node:test'
import { runProfileLogout, runProfileMutation, runProfileSubmit } from '../src/pages/profile/profileAuthFlow'

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
    setLoading: () => undefined,
    setProfile: (value) => { state.profile = value === null ? null : state.profile },
    setPrivacy: () => undefined,
    clearForm: () => undefined,
    setStatus: (value) => { state.status = value },
  })
  currentGeneration = ++generation
  authenticated = true
  state.status = 'B 已登录'
  resolveLogout(await fakeLogout())
  await pending
  assert.deepEqual(state, { status: 'B 已登录', profile: null })
})

test('Logout surfaces remote revoke uncertainty after local auth invalidation', async () => {
  let viewGeneration = 0
  let authenticated = true
  let resolveLogout!: (value: { localCleared: true; serverRevoked: false; serverStatus: 'UNCONFIRMED' }) => void
  const state = { status: '' }
  const pending = runProfileLogout({
    beginViewGeneration: () => ++viewGeneration,
    isViewGenerationCurrent: (value) => value === viewGeneration,
    logout: () => {
      // Model the production auth-session listener invalidating the page view
      // synchronously when logout clears the local session.
      authenticated = false
      viewGeneration += 1
      return new Promise((resolve) => { resolveLogout = resolve })
    },
    isAuthenticated: () => authenticated,
    setLoading: () => undefined,
    setProfile: () => undefined,
    setPrivacy: () => undefined,
    clearForm: () => undefined,
    setStatus: (value) => { state.status = value },
  })

  resolveLogout({ localCleared: true, serverRevoked: false, serverStatus: 'UNCONFIRMED' })
  await pending
  assert.equal(state.status, '已退出登录；服务器注销未确认，请重新登录后检查账号状态')
})

test('Pending profile mutation logout releases busy before B login and stale A finally cannot clear B', async () => {
  let operationGeneration = 0
  let currentOperation: object | null = null
  let viewGeneration = 0
  let authenticated = true
  let resolveLogout!: (value: { localCleared: true; serverRevoked: false; serverStatus: 'UNCONFIRMED' }) => void
  let resolveLogin!: () => void
  const state = { loading: true, status: 'A 正在保存', profile: 'A' as string | null }
  const beginOperation = () => {
    const operation = { generation: ++operationGeneration }
    currentOperation = operation
    return operation
  }
  const operationIsCurrent = (operation: object) => operation === currentOperation
  const staleAOperation = beginOperation()

  const pendingLogout = runProfileLogout({
    beginViewGeneration: () => { viewGeneration = ++viewGeneration; return viewGeneration },
    isViewGenerationCurrent: (value) => value === viewGeneration,
    logout: () => new Promise((resolve) => { resolveLogout = resolve }),
    isAuthenticated: () => authenticated,
    setLoading: (value) => { state.loading = value },
    setProfile: (value) => { state.profile = value },
    setPrivacy: () => undefined,
    clearForm: () => undefined,
    setStatus: (value) => { state.status = value },
  })

  // The old mutation's auth operation is no longer current after logout.
  currentOperation = null
  authenticated = false
  assert.equal(state.loading, false)
  assert.equal(state.profile, null)

  const bLogin = runProfileSubmit({
    registerMode: false,
    email: 'b@example.com',
    password: 'password-b',
    nickname: '',
    beginOperation,
    operationIsCurrent,
    registerAccount: async () => ({ user_id: 'unused', verification_required: true, verification_delivery_pending: false }),
    loginAccount: () => new Promise((resolve) => { resolveLogin = resolve }),
    refreshProfile: async () => undefined,
    setLoading: (value) => { state.loading = value },
    setStatus: (value) => { state.status = value },
    setVerificationPendingEmail: () => undefined,
  })
  await Promise.resolve()
  assert.equal(state.loading, true)

  if (staleAOperation && operationIsCurrent(staleAOperation)) state.loading = false
  assert.equal(state.loading, true)

  resolveLogout({ localCleared: true, serverRevoked: false, serverStatus: 'UNCONFIRMED' })
  await pendingLogout
  assert.equal(state.loading, true)

  resolveLogin()
  await bLogin
  assert.equal(state.loading, false)
})

test('Real delayed profile mutation callback cannot clear B loading after logout', async () => {
  let generation = 0
  let currentOperation: object | null = null
  let viewGeneration = 0
  let authenticated = true
  let resolveMutation!: (value: string) => void
  let resolveLogout!: (value: { localCleared: true; serverRevoked: true; serverStatus: 'CONFIRMED' }) => void
  let resolveLogin!: () => void
  const state = { loading: false, status: '', profile: 'A' as string | null }
  const beginOperation = () => {
    viewGeneration += 1
    const operation = { generation: ++generation }
    currentOperation = operation
    return operation
  }
  const operationIsCurrent = (operation: object) => operation === currentOperation

  const mutation = runProfileMutation({
    beginOperation,
    operationIsCurrent,
    currentViewGeneration: () => viewGeneration,
    isViewGenerationCurrent: (value) => value === viewGeneration,
    action: () => new Promise<string>((resolve) => { resolveMutation = resolve }),
    applySuccess: (value) => { state.profile = value },
    setLoading: (value) => { state.loading = value },
    setStatus: (value) => { state.status = value },
    successStatus: '资料已更新',
    errorStatus: '资料更新失败',
  })
  await Promise.resolve()
  assert.equal(state.loading, true)

  const logout = runProfileLogout({
    beginViewGeneration: () => ++viewGeneration,
    isViewGenerationCurrent: (value) => value === viewGeneration,
    logout: () => {
      authenticated = false
      currentOperation = null
      viewGeneration += 1
      return new Promise((resolve) => { resolveLogout = resolve })
    },
    isAuthenticated: () => authenticated,
    setLoading: (value) => { state.loading = value },
    setProfile: (value) => { state.profile = value === null ? null : state.profile },
    setPrivacy: () => undefined,
    clearForm: () => undefined,
    setStatus: (value) => { state.status = value },
  })
  assert.equal(state.loading, false)
  assert.equal(state.profile, null)

  const login = runProfileSubmit({
    registerMode: false,
    email: 'b@example.com',
    password: 'password-b',
    nickname: '',
    beginOperation,
    operationIsCurrent,
    registerAccount: async () => ({ user_id: 'unused', verification_required: true, verification_delivery_pending: false }),
    loginAccount: () => new Promise((resolve) => { resolveLogin = resolve }),
    refreshProfile: async () => undefined,
    setLoading: (value) => { state.loading = value },
    setStatus: (value) => { state.status = value },
    setVerificationPendingEmail: () => undefined,
  })
  await Promise.resolve()
  assert.equal(state.loading, true)

  resolveMutation('A profile response')
  await mutation
  assert.equal(state.profile, null)
  assert.equal(state.loading, true)
  assert.equal(state.status, '')

  resolveLogout({ localCleared: true, serverRevoked: true, serverStatus: 'CONFIRMED' })
  resolveLogin()
  await Promise.all([logout, login])
  assert.equal(state.loading, false)
})
