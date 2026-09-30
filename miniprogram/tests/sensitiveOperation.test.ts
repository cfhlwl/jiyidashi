import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  dataDeleteConfirmation,
  dataExportConfirmation,
  emergencyLocationShareConfirmation,
  familyPermissionConfirmation,
  SensitiveOperationEpoch,
  SensitiveOperationSingleFlight,
  sensitiveOperationStateChangedMessage,
} from '../src/services/sensitiveOperation'

test('SEC-014 confirmation specs use explicit user-facing action copy', () => {
  assert.equal(dataExportConfirmation().confirmText, '导出这些数据')
  assert.equal(dataDeleteConfirmation().confirmText, '删除这些数据')
  assert.equal(
    familyPermissionConfirmation({
      enabled: true,
      permissionLabel: '我允许 TA 查看我的照片',
      memberLabel: '成员 2222…2222',
    }).confirmText,
    '允许查看',
  )
  assert.equal(
    familyPermissionConfirmation({
      enabled: false,
      permissionLabel: '我允许 TA 查看我的照片',
      memberLabel: '成员 2222…2222',
    }).confirmText,
    '取消授权',
  )
  assert.equal(
    emergencyLocationShareConfirmation({
      memberLabel: '成员 2222…2222',
      durationLabel: '60 分钟',
    }).confirmText,
    '开始共享位置',
  )
  assert.equal(sensitiveOperationStateChangedMessage, '状态刚刚发生变化，请重新打开后再试')
})

test('SensitiveOperationSingleFlight closes the pre-render double-tap window', () => {
  const gate = new SensitiveOperationSingleFlight()
  assert.equal(gate.begin('member:ABC'), true)
  assert.equal(gate.begin('member:abc'), false)
  assert.equal(gate.isPending('MEMBER:abc'), true)
  gate.end('member:abc')
  assert.equal(gate.begin('member:ABC'), true)
})

test('SensitiveOperationEpoch discards late success/error publication after invalidation', async () => {
  for (const mode of ['success', 'error'] as const) {
    const epoch = new SensitiveOperationEpoch()
    const captured = epoch.capture()
    let published = false
    let resolvePending!: () => void
    let rejectPending!: (error: Error) => void
    const pending = new Promise<void>((resolvePromise, rejectPromise) => {
      resolvePending = resolvePromise
      rejectPending = rejectPromise
    })
    const completion = pending.then(
      () => {
        if (epoch.isCurrent(captured)) published = true
      },
      () => {
        if (epoch.isCurrent(captured)) published = true
      },
    )

    epoch.invalidate()
    if (mode === 'success') resolvePending()
    else rejectPending(new Error('late failure'))
    await completion
    assert.equal(published, false)
  }
})

test('Family permission mutation revalidates canonical grants after confirmation', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const start = page.indexOf('const updatePermission = async')
  const end = page.indexOf('const readLocation = async')
  const body = page.slice(start, end)

  assert.match(body, /confirmSensitiveOperation/)
  assert.match(body, /getFamily\(\)/)
  assert.match(body, /getFamilyPermissions\(\)/)
  assert.match(body, /replaceVisiblePermission/)
  assert.match(body, /replaceFamilyPermissions/)
  assert.ok(body.indexOf('getFamilyPermissions()') < body.indexOf('replaceFamilyPermissions'))
  assert.match(body, /mutationSessionCurrent/)
  assert.match(body, /sensitiveMutationEpoch\.current\.isCurrent/)
})

test('member and emergency mutations enter synchronous single-flight before confirmation', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const memberStart = page.indexOf('const mutateMember = async')
  const permissionStart = page.indexOf('const updatePermission = async')
  const memberBody = page.slice(memberStart, permissionStart)
  assert.ok(
    memberBody.indexOf('sensitiveMutationFlight.current.begin') <
      memberBody.indexOf('confirmSensitiveOperation'),
  )

  const emergencyStart = page.indexOf('const createEmergencyShare = async')
  const emergencyRevoke = page.indexOf('const revokeEmergencyShare = async')
  const emergencyBody = page.slice(emergencyStart, emergencyRevoke)
  assert.ok(
    emergencyBody.indexOf('sensitiveMutationFlight.current.begin') <
      emergencyBody.indexOf('confirmSensitiveOperation'),
  )
})


test('Family refresh binds the originating auth session before publishing payloads', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const refreshStart = page.indexOf('const refresh = async')
  const refreshEnd = page.indexOf('useDidShow')
  const refreshBody = page.slice(refreshStart, refreshEnd)

  assert.match(refreshBody, /expectedSession\?: \{ owner: string \| null; epoch: number \}/)
  assert.match(refreshBody, /const refreshSession = expectedSession \|\| captureMutationSession\(\)/)
  assert.match(refreshBody, /const refreshCurrent = \(\) =>/)
  assert.match(refreshBody, /const family = await getFamily\(\)[\s\S]*?if \(!refreshCurrent\(\)\) return false/)
  assert.match(refreshBody, /const profile = await getProfile\(\)[\s\S]*?if \(!refreshCurrent\(\)\) return false/)
  assert.match(refreshBody, /const permissions = await getFamilyPermissions\(\)[\s\S]*?if \(!refreshCurrent\(\)\) return false/)

  const followup = refreshBody.indexOf('const [shares, reminders] = await Promise.all')
  const finalFreshness = refreshBody.indexOf('if (!refreshCurrent()) return false', followup)
  const publishShares = refreshBody.indexOf('setEmergencyShares(shares)', followup)
  const publishPage = refreshBody.indexOf("setPageState({\n        phase: 'family-ready'", followup)
  assert.ok(followup >= 0)
  assert.ok(finalFreshness > followup)
  assert.ok(publishShares > finalFreshness)
  assert.ok(publishPage > finalFreshness)

  const memberStart = page.indexOf('const mutateMember = async')
  const permissionStart = page.indexOf('const updatePermission = async')
  const memberBody = page.slice(memberStart, permissionStart)
  assert.match(memberBody, /const refreshed = await refresh\(true, session\)/)
  assert.match(memberBody, /if \(!refreshed \|\| !mutationSessionCurrent\(session\)\) return/)
})

test('Emergency follow-up reads validate stale session before publishing shares', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const emergencyStart = page.indexOf('const createEmergencyShare = async')
  const emergencyRead = page.indexOf('const readEmergencyLocation = async')
  const body = page.slice(emergencyStart, emergencyRead)

  assert.doesNotMatch(body, /setEmergencyShares\(await getFamilyEmergencyShares/)
  const guardedPublish = /const nextShares = await getFamilyEmergencyShares\(ownerUserId\)[\s\S]*?if \(!sensitiveMutationEpoch\.current\.isCurrent\(attempt\) \|\| !mutationSessionCurrent\(session\)\) \{[\s\S]*?return[\s\S]*?\}[\s\S]*?setEmergencyShares\(nextShares\)/g
  const matches = body.match(guardedPublish) || []
  assert.equal(matches.length, 2)
})

test('account switch during Family/Emergency refresh discards old payload before publish', async () => {
  let currentOwner = 'account-a'
  let currentEpoch = 7
  const captured = { owner: currentOwner, epoch: currentEpoch }
  const mutationEpoch = new SensitiveOperationEpoch()
  const refreshAttempt = mutationEpoch.invalidate()

  let resolvePayload!: (value: { family: string; shares: string[] }) => void
  const pending = new Promise<{ family: string; shares: string[] }>((resolvePromise) => {
    resolvePayload = resolvePromise
  })

  let familyState = 'new-session-family'
  let emergencyState = ['new-session-share']
  const sessionCurrent = () => (
    mutationEpoch.isCurrent(refreshAttempt)
    && captured.owner === currentOwner
    && captured.epoch === currentEpoch
  )

  const completion = pending.then((payload) => {
    if (!sessionCurrent()) return
    emergencyState = payload.shares
    familyState = payload.family
  })

  // The old account's follow-up GET is still pending when the user switches account.
  currentOwner = 'account-b'
  currentEpoch += 1
  resolvePayload({
    family: 'old-account-family',
    shares: ['old-account-emergency-share'],
  })
  await completion

  assert.equal(familyState, 'new-session-family')
  assert.deepEqual(emergencyState, ['new-session-share'])
})
