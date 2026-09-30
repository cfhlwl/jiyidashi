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
