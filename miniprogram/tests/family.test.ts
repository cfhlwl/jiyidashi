import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  assertCurrentFamilyMember,
  FAMILY_PERMISSION,
  familyErrorMessage,
  familyMemberActions,
  FamilyPermissionMutationGate,
  FamilySensitiveReadEpoch,
  INTERACTIVE_FAMILY_PERMISSIONS,
  familyArrivalStatusLabel,
  parseFamilyArrivalReminders,
  parseFamilyAudit,
  parseFamilyCurrentLocation,
  parseFamilyEmergencyShares,
  parseFamilyInvite,
  parseFamilyMemories,
  parseFamilyPermissions,
  parseFamilyPhotoDownload,
  parseFamilyPhotos,
  parseFamilyResponse,
  parseFamilyTodayFootprint,
  permissionLabel,
  replaceVisiblePermission,
} from '../src/services/family'

const OWNER_ID = '11111111-1111-4111-8111-111111111111'
const MEMBER_ID = '22222222-2222-4222-8222-222222222222'
const OTHER_ID = '33333333-3333-4333-8333-333333333333'

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function familyBody(currentRole: 'OWNER' | 'MEMBER' = 'OWNER'): unknown {
  return {
    family_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    current_user_role: currentRole,
    members: [
      { user_id: OWNER_ID, role: 'OWNER', created_at: '2026-09-22T10:00:00Z' },
      { user_id: MEMBER_ID, role: 'MEMBER', created_at: '2026-09-22T10:01:00Z' },
    ],
  }
}

test('FamilyResponse runtime parser accepts valid authority and resolves current member', () => {
  const family = parseFamilyResponse(familyBody())
  assert.equal(family.current_user_role, 'OWNER')
  assert.equal(family.members.length, 2)
  assert.equal(assertCurrentFamilyMember(family, OWNER_ID).role, 'OWNER')
})

test('FamilyResponse malformed family id, user id, role or member list fails closed', () => {
  assert.throws(() => parseFamilyResponse({ ...(familyBody() as object), family_id: 'not-a-uuid' }), /家庭数据异常/)
  assert.throws(() => parseFamilyResponse({ ...(familyBody() as object), members: [{ user_id: 'bad', role: 'OWNER', created_at: '2026-09-22T10:00:00Z' }] }), /家庭数据异常/)
  assert.throws(() => parseFamilyResponse({ ...(familyBody() as object), current_user_role: 'ADMIN' }), /家庭数据异常/)
  assert.throws(() => parseFamilyResponse({ ...(familyBody() as object), members: {} }), /家庭数据异常/)
  assert.throws(() => parseFamilyResponse({ ...(familyBody() as object), members: [
    { user_id: OWNER_ID, role: 'OWNER', created_at: '2026-09-22T10:00:00Z' },
    { user_id: OTHER_ID, role: 'OWNER', created_at: '2026-09-22T10:00:00Z' },
  ] }), /家庭数据异常/)
})

test('invite parser accepts opaque token without parsing its contents', () => {
  const invite = parseFamilyInvite({
    invite_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    token: 'opaque.token/value+with=characters',
    expires_at: '2026-09-23T10:00:00Z',
  })
  assert.equal(invite.token, 'opaque.token/value+with=characters')
})

test('permission parser validates shape while preserving future permission codes', () => {
  const grants = parseFamilyPermissions([{
    grantee_user_id: MEMBER_ID,
    permissions: [
      FAMILY_PERMISSION.VIEW_CURRENT_LOCATION,
      FAMILY_PERMISSION.VIEW_FOOTPRINT,
      'VIEW_FUTURE_SAFE_CAPABILITY',
    ],
  }])
  assert.deepEqual(grants[0].permissions, [
    FAMILY_PERMISSION.VIEW_CURRENT_LOCATION,
    FAMILY_PERMISSION.VIEW_FOOTPRINT,
    'VIEW_FUTURE_SAFE_CAPABILITY',
  ])
  assert.throws(() => parseFamilyPermissions([{ grantee_user_id: MEMBER_ID, permissions: [123] }]), /家庭数据异常/)
})

test('current-location parser verifies owner and returns only display whitelist fields', () => {
  const parsed = parseFamilyCurrentLocation({
    resource_owner_user_id: MEMBER_ID,
    latitude: 31.2304,
    longitude: 121.4737,
    accuracy: 8,
    recorded_at: '2026-09-22T10:00:00Z',
    fresh_until: '2026-09-22T10:15:00Z',
    speed: 99,
    client_uuid: 'must-not-leak',
  }, MEMBER_ID)
  assert.deepEqual(Object.keys(parsed).sort(), [
    'accuracy', 'fresh_until', 'latitude', 'longitude', 'recorded_at',
  ])
  assert.equal((parsed as Record<string, unknown>).speed, undefined)
  assert.throws(() => parseFamilyCurrentLocation({
    resource_owner_user_id: OWNER_ID,
    latitude: 31,
    longitude: 121,
    accuracy: null,
    recorded_at: '2026-09-22T10:00:00Z',
    fresh_until: '2026-09-22T10:15:00Z',
  }, MEMBER_ID), /家庭数据异常/)
})

test('Family Memory parser is bounded, fail-closed and returns only safe projection fields', () => {
  const raw = {
    memory_id: OWNER_ID,
    memory_type: 'NOTE',
    title: '家人的记忆',
    content: '只展示允许的记忆正文',
    occurred_at: '2026-09-23T10:00:00Z',
    source_type: 'USER_TEXT',
    is_confirmed: true,
    edit_revision: 2,
    created_at: '2026-09-23T09:00:00Z',
    metadata_json: { private: true },
    latitude: 31.2,
    longitude: 121.4,
    memory_source_id: OTHER_ID,
  }
  const parsed = parseFamilyMemories([raw])
  assert.deepEqual(Object.keys(parsed[0]).sort(), [
    'content',
    'created_at',
    'edit_revision',
    'is_confirmed',
    'memory_id',
    'memory_type',
    'occurred_at',
    'source_type',
    'title',
  ])
  assert.equal((parsed[0] as Record<string, unknown>).metadata_json, undefined)
  assert.equal((parsed[0] as Record<string, unknown>).latitude, undefined)
  assert.deepEqual(parseFamilyMemories([]), [])
  assert.throws(() => parseFamilyMemories([{ ...raw, memory_id: 'bad' }]), /家庭数据异常/)
  assert.throws(() => parseFamilyMemories([{ ...raw, is_confirmed: 'true' }]), /家庭数据异常/)
  assert.throws(() => parseFamilyMemories([{ ...raw, edit_revision: -1 }]), /家庭数据异常/)
  assert.throws(() => parseFamilyMemories([raw, raw]), /家庭数据异常/)
  assert.throws(() => parseFamilyMemories(Array.from({ length: 51 }, (_, index) => ({
    ...raw,
    memory_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  }))), /家庭数据异常/)
})

test('family photo parser keeps only safe metadata and enforces bounded image contract', () => {
  const parsed = parseFamilyPhotos([{
    media_id: OTHER_ID,
    content_type: 'image/jpeg',
    size_bytes: 2048,
    created_at: '2026-09-23T10:00:00Z',
    completed_at: '2026-09-23T10:00:01Z',
    object_key: 'must-not-leak',
    original_filename: 'private.jpg',
    storage_etag: 'private',
    exif: { gps: 'private' },
  }])

  assert.deepEqual(Object.keys(parsed[0]).sort(), [
    'completed_at', 'content_type', 'created_at', 'media_id', 'size_bytes',
  ])
  assert.equal((parsed[0] as Record<string, unknown>).object_key, undefined)
  assert.throws(() => parseFamilyPhotos([{
    media_id: OTHER_ID,
    content_type: 'audio/mpeg',
    size_bytes: 2048,
    created_at: '2026-09-23T10:00:00Z',
    completed_at: '2026-09-23T10:00:01Z',
  }]), /家庭数据异常/)
  assert.throws(() => parseFamilyPhotos(Array.from({ length: 51 }, (_, index) => ({
    media_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
    content_type: 'image/jpeg',
    size_bytes: 1,
    created_at: '2026-09-23T10:00:00Z',
    completed_at: '2026-09-23T10:00:01Z',
  }))), /家庭数据异常/)
})

test('family photo signed transfer is media-bound GET-only HTTPS-only and whitelisted', () => {
  const parsed = parseFamilyPhotoDownload({
    media_id: OTHER_ID,
    download: {
      method: 'GET',
      url: 'https://private-storage.test/photo?temporary=1',
      headers: { 'X-Capability': 'short-lived' },
      expires_at: '2026-09-23T10:05:00Z',
      object_key: 'must-not-leak',
    },
  }, OTHER_ID)
  assert.equal(parsed.media_id, OTHER_ID)
  assert.deepEqual(Object.keys(parsed.download).sort(), ['expires_at', 'headers', 'method', 'url'])
  assert.throws(() => parseFamilyPhotoDownload({
    media_id: OTHER_ID,
    download: {
      method: 'PUT',
      url: 'https://private-storage.test/photo',
      headers: {},
      expires_at: '2026-09-23T10:05:00Z',
    },
  }, OTHER_ID), /家庭数据异常/)
})

test('family Today Footprint reuses strict Today parser', () => {
  const parsed = parseFamilyTodayFootprint({
    timezone: 'Asia/Shanghai',
    day: '2026-09-22',
    visits: [],
  })
  assert.equal(parsed.day, '2026-09-22')
  assert.throws(() => parseFamilyTodayFootprint({
    timezone: 'Asia/Shanghai',
    day: '2026-09-22',
    visits: [{
      id: OWNER_ID,
      place_id: MEMBER_ID,
      place_name: '家',
      arrived_at: '2026-09-22T01:00:00Z',
      left_at: null,
      arrived_at_local: '2026-09-22T09:00:00+08:00',
      left_at_local: null,
      confidence: 0.9,
      visit_source: 'LOCATION_CLUSTER',
      visit_finalized: 'false',
    }],
  }), /今日足迹数据异常/)
})

test('OWNER and MEMBER presentation keeps self actions and cross-member actions distinct', () => {
  const ownerFamily = parseFamilyResponse(familyBody('OWNER'))
  const ownerSelf = familyMemberActions(OWNER_ID, 'OWNER', ownerFamily.members[0])
  const ownerOther = familyMemberActions(OWNER_ID, 'OWNER', ownerFamily.members[1])
  assert.equal(ownerSelf.showSensitiveReads, false)
  assert.equal(ownerSelf.showOwnerRemove, false)
  assert.equal(ownerOther.showOwnerRemove, true)
  assert.equal(ownerOther.showSensitiveReads, true)

  const memberFamily = parseFamilyResponse(familyBody('MEMBER'))
  assertCurrentFamilyMember(memberFamily, MEMBER_ID)
  const memberSelf = familyMemberActions(MEMBER_ID, 'MEMBER', memberFamily.members[1])
  assert.equal(memberSelf.showMemberLeave, true)
  assert.equal(memberSelf.showSensitiveReads, false)
})

test('permission labels expose all four independent outbound authorities', () => {
  assert.match(permissionLabel(FAMILY_PERMISSION.VIEW_CURRENT_LOCATION), /我允许 TA 查看我的当前位置/)
  assert.match(permissionLabel(FAMILY_PERMISSION.VIEW_FOOTPRINT), /我允许 TA 查看我的今日足迹/)
  assert.match(permissionLabel(FAMILY_PERMISSION.VIEW_MEMORY), /我允许 TA 查看我的个人记忆/)
  assert.match(permissionLabel(FAMILY_PERMISSION.VIEW_PHOTOS), /我允许 TA 查看我的照片/)
  assert.deepEqual(INTERACTIVE_FAMILY_PERMISSIONS, [
    FAMILY_PERMISSION.VIEW_CURRENT_LOCATION,
    FAMILY_PERMISSION.VIEW_FOOTPRINT,
    FAMILY_PERMISSION.VIEW_MEMORY,
    FAMILY_PERMISSION.VIEW_PHOTOS,
  ])
})

test('visible permission toggle preserves the other visible and unknown future codes', () => {
  const current = [
    FAMILY_PERMISSION.VIEW_CURRENT_LOCATION,
    FAMILY_PERMISSION.VIEW_FOOTPRINT,
    'VIEW_FUTURE_SAFE_CAPABILITY',
  ]
  assert.deepEqual(
    replaceVisiblePermission(current, FAMILY_PERMISSION.VIEW_CURRENT_LOCATION, false),
    [FAMILY_PERMISSION.VIEW_FOOTPRINT, 'VIEW_FUTURE_SAFE_CAPABILITY'],
  )
  assert.deepEqual(
    replaceVisiblePermission(current, FAMILY_PERMISSION.VIEW_FOOTPRINT, false),
    [FAMILY_PERMISSION.VIEW_CURRENT_LOCATION, 'VIEW_FUTURE_SAFE_CAPABILITY'],
  )
  assert.deepEqual(
    replaceVisiblePermission(
      [...current, FAMILY_PERMISSION.VIEW_MEMORY],
      FAMILY_PERMISSION.VIEW_MEMORY,
      false,
    ),
    [
      FAMILY_PERMISSION.VIEW_CURRENT_LOCATION,
      FAMILY_PERMISSION.VIEW_FOOTPRINT,
      'VIEW_FUTURE_SAFE_CAPABILITY',
    ],
  )
})

test('per-member permission mutation gate rejects rapid concurrent replacement', () => {
  const gate = new FamilyPermissionMutationGate()
  assert.equal(gate.begin(MEMBER_ID), true)
  assert.equal(gate.begin(MEMBER_ID), false)
  assert.equal(gate.begin(OTHER_ID), true)
  gate.end(MEMBER_ID)
  assert.equal(gate.begin(MEMBER_ID), true)
})

test('sensitive-read errors keep unauthorized, unavailable and empty Memory states distinct', () => {
  assert.equal(familyErrorMessage('FAMILY_READ_NOT_AUTHORIZED', 'current-location'), '对方未授权查看当前位置')
  assert.equal(familyErrorMessage('CURRENT_LOCATION_UNAVAILABLE', 'current-location'), '当前位置暂不可用')
  assert.equal(familyErrorMessage('FAMILY_READ_NOT_AUTHORIZED', 'footprint'), '对方未授权查看今日足迹')
  assert.equal(familyErrorMessage('FAMILY_READ_NOT_AUTHORIZED', 'memory'), '对方未授权查看个人记忆')
  assert.equal(familyErrorMessage('FAMILY_READ_NOT_AUTHORIZED', 'photos'), '对方未授权查看照片')
  assert.equal(familyErrorMessage('FAMILY_READ_NOT_AUTHORIZED', 'photo-download'), '对方未授权查看照片')
  assert.equal(familyErrorMessage('FAMILY_PHOTO_UNAVAILABLE', 'photo-download'), '这张照片已不可用')
  // 200 [] is not an error code; the page renders its dedicated empty copy.
  assert.equal(familyErrorMessage(null, 'memory'), null)
})

test('location stale success cannot repopulate sensitive state after refresh invalidation', async () => {
  const epoch = new FamilySensitiveReadEpoch()
  const request = deferred<{ latitude: number }>()
  let sensitiveState: Record<string, unknown> = {}

  const captured = epoch.capture()
  const completion = request.promise.then((data) => {
    if (!epoch.isCurrent(captured)) return
    sensitiveState = { location: data }
  })

  epoch.invalidate()
  sensitiveState = {}
  request.resolve({ latitude: 31.2304 })
  await completion

  assert.deepEqual(sensitiveState, {})
})

test('footprint stale success cannot repopulate sensitive state after refresh invalidation', async () => {
  const epoch = new FamilySensitiveReadEpoch()
  const request = deferred<{ day: string }>()
  let sensitiveState: Record<string, unknown> = {}

  const captured = epoch.capture()
  const completion = request.promise.then((data) => {
    if (!epoch.isCurrent(captured)) return
    sensitiveState = { footprint: data }
  })

  epoch.invalidate()
  sensitiveState = {}
  request.resolve({ day: '2026-09-22' })
  await completion

  assert.deepEqual(sensitiveState, {})
})

test('Family Memory stale success cannot repopulate sensitive state after refresh invalidation', async () => {
  const epoch = new FamilySensitiveReadEpoch()
  const request = deferred<Array<{ memory_id: string }>>()
  let sensitiveState: Record<string, unknown> = {}

  const captured = epoch.capture()
  const completion = request.promise.then((data) => {
    if (!epoch.isCurrent(captured)) return
    sensitiveState = { memory: data }
  })

  epoch.invalidate()
  sensitiveState = {}
  request.resolve([{ memory_id: OWNER_ID }])
  await completion

  assert.deepEqual(sensitiveState, {})
})

test('stale location, footprint and Memory errors cannot repopulate sensitive state after refresh invalidation', async () => {
  for (const key of ['location', 'footprint', 'memory'] as const) {
    const epoch = new FamilySensitiveReadEpoch()
    const request = deferred<never>()
    let sensitiveState: Record<string, unknown> = {}

    const captured = epoch.capture()
    const completion = request.promise.catch((error) => {
      if (!epoch.isCurrent(captured)) return
      sensitiveState = { [key]: { state: 'error', message: String(error) } }
    })

    epoch.invalidate()
    sensitiveState = {}
    request.reject(new Error('stale failure'))
    await completion

    assert.deepEqual(sensitiveState, {})
  }
})

test('photo list and signing stale completion cannot repopulate state after invalidation', async () => {
  for (const key of ['photos', 'photoPreview'] as const) {
    const epoch = new FamilySensitiveReadEpoch()
    const request = deferred<{ value: string }>()
    let sensitiveState: Record<string, unknown> = {}

    const captured = epoch.capture()
    const completion = request.promise.then((data) => {
      if (!epoch.isCurrent(captured)) return
      sensitiveState = { [key]: data }
    })

    epoch.invalidate()
    sensitiveState = {}
    request.resolve({ value: 'stale-sensitive-result' })
    await completion
    assert.deepEqual(sensitiveState, {})
  }
})

test('photo list and signing stale errors are discarded after invalidation', async () => {
  for (const key of ['photos', 'photoPreview'] as const) {
    const epoch = new FamilySensitiveReadEpoch()
    const request = deferred<never>()
    let sensitiveState: Record<string, unknown> = {}

    const captured = epoch.capture()
    const completion = request.promise.catch((error) => {
      if (!epoch.isCurrent(captured)) return
      sensitiveState = { [key]: String(error) }
    })

    epoch.invalidate()
    sensitiveState = {}
    request.reject(new Error('stale photo failure'))
    await completion
    assert.deepEqual(sensitiveState, {})
  }
})

test('unknown Family server codes are not promoted into user-facing copy', () => {
  assert.equal(familyErrorMessage('FAMILY_FUTURE_INTERNAL_DETAIL', 'load'), null)
})

test('page contract has explicit states and does not auto-fetch family sensitive reads', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  for (const phase of ['signed-out', 'loading', 'no-family', 'family-ready', 'error']) {
    assert.match(page, new RegExp(`'${phase}'`))
  }
  assert.match(
    page,
    /if \(apiErrorCode\(error\) === 'FAMILY_NOT_FOUND'\)[\s\S]*?setPageState\(\{ phase: 'no-family' \}\)/,
  )
  assert.match(
    page,
    /await createFamily\(\)[\s\S]*?await refresh\(true\)[\s\S]*?setStatus\('家庭已创建'\)/,
  )
  assert.match(
    page,
    /await acceptFamilyInvite\(token\)[\s\S]*?setJoinToken\(''\)[\s\S]*?await refresh\(true\)[\s\S]*?setStatus\('已加入家庭'\)/,
  )
  assert.match(
    page,
    /const confirm = await Taro\.showModal\([\s\S]*?if \(!confirm\.confirm\) return[\s\S]*?await removeFamilyMember\(targetUserId\)[\s\S]*?await refresh\(true\)/,
  )
  assert.match(page, /onClick=\{\(\) => mutateMember\(member\.user_id, 'remove'\)\}/)
  assert.match(page, /onClick=\{\(\) => mutateMember\(member\.user_id, 'leave'\)\}/)

  const refreshStart = page.indexOf('const refresh = async')
  const refreshEnd = page.indexOf('const create = async')
  assert.notEqual(refreshStart, -1)
  assert.notEqual(refreshEnd, -1)
  const refreshBody = page.slice(refreshStart, refreshEnd)
  assert.doesNotMatch(
    refreshBody,
    /getFamilyCurrentLocation|getFamilyTodayFootprint|getFamilyMemories|getFamilyPhotos|getFamilyPhotoDownload/,
  )
  assert.match(refreshBody, /sensitiveReadEpoch\.current\.invalidate\(\)/)
  assert.match(refreshBody, /setMemberReads\(\{\}\)/)
  assert.match(
    page,
    /const readEpoch = sensitiveReadEpoch\.current\.capture\(\)[\s\S]*?getFamilyCurrentLocation[\s\S]*?isCurrent\(readEpoch\)[\s\S]*?catch \(error\)[\s\S]*?isCurrent\(readEpoch\)/,
  )
  assert.match(
    page,
    /const readEpoch = sensitiveReadEpoch\.current\.capture\(\)[\s\S]*?getFamilyTodayFootprint[\s\S]*?isCurrent\(readEpoch\)[\s\S]*?catch \(error\)[\s\S]*?isCurrent\(readEpoch\)/,
  )
  assert.match(
    page,
    /const readEpoch = sensitiveReadEpoch\.current\.capture\(\)[\s\S]*?getFamilyMemories[\s\S]*?isCurrent\(readEpoch\)[\s\S]*?catch \(error\)[\s\S]*?isCurrent\(readEpoch\)/,
  )
  assert.match(page, /查看个人记忆/)
  assert.match(page, /对方当前没有可显示的记忆/)
  assert.match(
    page,
    /const readPhotos = async[\s\S]*?getFamilyPhotos\(resourceOwnerUserId\)[\s\S]*?isCurrent\(readEpoch\)[\s\S]*?catch \(error\)[\s\S]*?isCurrent\(readEpoch\)/,
  )
  assert.match(
    page,
    /const signed = await getFamilyPhotoDownload\(resourceOwnerUserId, mediaId\)[\s\S]*?Taro\.downloadFile\([\s\S]*?signed\.download\.url[\s\S]*?isCurrent\(readEpoch\)/,
  )
  assert.match(page, /查看照片/)
  assert.doesNotMatch(page, /照片 <Text className='muted'>暂未开放<\/Text>/)
  assert.match(
    page,
    /sensitiveReadEpoch\.current\.invalidate\(\)[\s\S]*?setMemberReads\(\{\}\)[\s\S]*?setPermissionBusy/,
  )
  assert.match(page, /return familyErrorMessage\(apiErrorCode\(error\), context\) \|\| fallback/)
})

test('Family permission, Memory and Photo APIs use the shared authenticated transport', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /method: 'GET' \| 'POST' \| 'PUT' \| 'PATCH' \| 'DELETE'/)
  assert.match(
    api,
    /request<unknown>\(\s*'PUT',\s*`\/family\/permissions\/\$\{encodeURIComponent\(granteeUserId\)\}`/,
  )
  assert.match(
    api,
    /`\/family\/members\/\$\{encodeURIComponent\(resourceOwnerUserId\)\}\/memories\?limit=50`/,
  )
  assert.match(
    api,
    /'GET',\s*`\/family\/members\/\$\{encodeURIComponent\(resourceOwnerUserId\)\}\/photos`/,
  )
  assert.match(
    api,
    /'POST',\s*`\/family\/members\/\$\{encodeURIComponent\(resourceOwnerUserId\)\}\/photos\/\$\{encodeURIComponent\(mediaId\)\}\/download`/,
  )
})


test('family audit parser accepts only bounded known enum projection and stable order', () => {
  const rows = parseFamilyAudit([
    {
      event_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      actor_user_id: MEMBER_ID,
      resource_owner_user_id: OWNER_ID,
      authority_type: 'EXACT_GRANT',
      permission_code: 'VIEW_PHOTOS',
      resource_type: 'PHOTO',
      action: 'DOWNLOAD_PHOTO',
      result: 'ALLOWED',
      created_at: '2026-09-25T14:20:00Z',
      latitude: 39.9,
      signed_url: 'https://must-not-surface.invalid/private',
    },
    {
      event_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      actor_user_id: MEMBER_ID,
      resource_owner_user_id: OWNER_ID,
      authority_type: 'EXACT_GRANT',
      permission_code: 'VIEW_CURRENT_LOCATION',
      resource_type: 'CURRENT_LOCATION',
      action: 'READ_CURRENT_LOCATION',
      result: 'UNAVAILABLE',
      created_at: '2026-09-25T14:05:00Z',
    },
  ])
  assert.equal(rows.length, 2)
  assert.deepEqual(Object.keys(rows[0]).sort(), [
    'action',
    'actor_user_id',
    'authority_type',
    'created_at',
    'event_id',
    'permission_code',
    'resource_owner_user_id',
    'resource_type',
    'result',
  ])
  assert.equal('latitude' in rows[0], false)
  assert.equal('signed_url' in rows[0], false)
})

test('family audit parser rejects unknown enums, duplicate ids, malformed UUIDs and unstable order', () => {
  const base = {
    event_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    actor_user_id: MEMBER_ID,
    resource_owner_user_id: OWNER_ID,
    authority_type: 'EXACT_GRANT',
    permission_code: 'VIEW_MEMORY',
    resource_type: 'MEMORY',
    action: 'READ_MEMORY',
    result: 'ALLOWED',
    created_at: '2026-09-25T14:20:00Z',
  }
  for (const patch of [
    { permission_code: 'VIEW_FUTURE' },
    { resource_type: 'SECRET' },
    { action: 'EXPORT_ALL' },
    { result: 'SUCCESS' },
    { actor_user_id: 'bad' },
  ]) {
    assert.throws(() => parseFamilyAudit([{ ...base, ...patch }]), /家庭数据异常/)
  }
  assert.throws(() => parseFamilyAudit([base, base]), /家庭数据异常/)
  assert.throws(() => parseFamilyAudit([
    { ...base, event_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', created_at: '2026-09-25T14:00:00Z' },
    { ...base, event_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', created_at: '2026-09-25T14:30:00Z' },
  ]), /家庭数据异常/)
  assert.throws(() => parseFamilyAudit(Array.from({ length: 51 }, (_, index) => ({
    ...base,
    event_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  }))), /家庭数据异常/)
})

test('Family page exposes OWNER-only explicit audit read and never fetches audit during refresh', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const refreshStart = page.indexOf('const refresh = async')
  const refreshEnd = page.indexOf('const create = async')
  const refreshBody = page.slice(refreshStart, refreshEnd)
  assert.doesNotMatch(refreshBody, /getFamilyAudit/)
  assert.match(page, /family\.current_user_role === 'OWNER'[\s\S]*?隐私访问记录/)
  assert.match(page, /const readAudit = async[\s\S]*?getFamilyAudit\(\)/)
  assert.match(page, /暂无访问记录/)
  assert.match(page, /成员 \{shortMemberId\(event\.actor_user_id\)\}[\s\S]*?数据所有者 \{shortMemberId\(event\.resource_owner_user_id\)\}/)
  assert.doesNotMatch(page, /event\.latitude|event\.longitude|event\.content|event\.url|event\.object_key/)
})

test('Family audit API uses authenticated transport and bounded server query', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /request<unknown>\('GET', '\/family\/audit\?limit=50'\)/)
})


test('Family audit stale success cannot repopulate audit state after refresh invalidation', async () => {
  const epoch = new FamilySensitiveReadEpoch()
  const request = deferred<Array<{ event_id: string }>>()
  let auditState: Record<string, unknown> = {}

  const captured = epoch.capture()
  const completion = request.promise.then((data) => {
    if (!epoch.isCurrent(captured)) return
    auditState = { audit: { state: 'ready', data } }
  })

  epoch.invalidate()
  auditState = {}
  request.resolve([{ event_id: OWNER_ID }])
  await completion

  assert.deepEqual(auditState, {})
})

test('Family audit stale error cannot repopulate audit error after refresh invalidation', async () => {
  const epoch = new FamilySensitiveReadEpoch()
  const request = deferred<never>()
  let auditState: Record<string, unknown> = {}

  const captured = epoch.capture()
  const completion = request.promise.catch((error) => {
    if (!epoch.isCurrent(captured)) return
    auditState = { audit: { state: 'error', message: String(error) } }
  })

  epoch.invalidate()
  auditState = {}
  request.reject(new Error('stale audit failure'))
  await completion

  assert.deepEqual(auditState, {})
})

test('Family audit page read reuses sensitive read epoch for success and error gating', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const readAuditStart = page.indexOf('const readAudit = async')
  const renderAuditStart = page.indexOf('const renderAudit =')
  const readAuditBody = page.slice(readAuditStart, renderAuditStart)

  assert.match(readAuditBody, /const readEpoch = sensitiveReadEpoch\.current\.capture\(\)/)
  assert.match(
    readAuditBody,
    /const data = await getFamilyAudit\(\)[\s\S]*?if \(!sensitiveReadEpoch\.current\.isCurrent\(readEpoch\)\) return[\s\S]*?setAuditRead\(\{ state: 'ready', data \}\)/,
  )
  assert.match(
    readAuditBody,
    /catch \(error\)[\s\S]*?if \(!sensitiveReadEpoch\.current\.isCurrent\(readEpoch\)\) return[\s\S]*?setAuditRead\(\{/,
  )
})


test('emergency share parser enforces direction duration uniqueness and metadata-only projection', () => {
  const rows = parseFamilyEmergencyShares([{
    share_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    resource_owner_user_id: OWNER_ID,
    grantee_user_id: MEMBER_ID,
    expires_at: '2026-09-25T11:30:00Z',
    created_at: '2026-09-25T11:00:00Z',
    direction: 'INCOMING',
    latitude: 39.9,
    longitude: 116.4,
  }], MEMBER_ID)
  assert.equal(rows.length, 1)
  assert.deepEqual(Object.keys(rows[0]).sort(), [
    'created_at',
    'direction',
    'expires_at',
    'grantee_user_id',
    'resource_owner_user_id',
    'share_id',
  ])
  assert.equal((rows[0] as Record<string, unknown>).latitude, undefined)

  assert.throws(() => parseFamilyEmergencyShares([{
    ...rows[0],
    direction: 'BROADCAST',
  }]), /家庭数据异常/)
  assert.throws(() => parseFamilyEmergencyShares([{
    ...rows[0],
    expires_at: '2026-09-25T11:31:00Z',
  }]), /家庭数据异常/)
  assert.throws(() => parseFamilyEmergencyShares([rows[0], rows[0]]), /家庭数据异常/)
  assert.throws(() => parseFamilyEmergencyShares([{
    ...rows[0],
    grantee_user_id: OWNER_ID,
  }]), /家庭数据异常/)
})

test('audit parser distinguishes exact grant from emergency authority truthfully', () => {
  const emergency = parseFamilyAudit([{
    event_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    actor_user_id: MEMBER_ID,
    resource_owner_user_id: OWNER_ID,
    authority_type: 'EMERGENCY_SHARE',
    permission_code: null,
    resource_type: 'CURRENT_LOCATION',
    action: 'READ_EMERGENCY_LOCATION',
    result: 'ALLOWED',
    created_at: '2026-09-25T11:05:00Z',
  }])
  assert.equal(emergency[0].authority_type, 'EMERGENCY_SHARE')
  assert.equal(emergency[0].permission_code, null)

  assert.throws(() => parseFamilyAudit([{
    ...emergency[0],
    permission_code: 'VIEW_CURRENT_LOCATION',
  }]), /家庭数据异常/)
  assert.throws(() => parseFamilyAudit([{
    ...emergency[0],
    authority_type: 'EXACT_GRANT',
    permission_code: null,
  }]), /家庭数据异常/)
})

test('emergency location stale success and error are discarded after invalidation', async () => {
  for (const mode of ['success', 'error'] as const) {
    const epoch = new FamilySensitiveReadEpoch()
    const request = deferred<{ latitude: number }>()
    let state: Record<string, unknown> = {}
    const captured = epoch.capture()
    const completion = mode === 'success'
      ? request.promise.then((data) => {
        if (!epoch.isCurrent(captured)) return
        state = { emergency: { state: 'ready', data } }
      })
      : request.promise.catch((error) => {
        if (!epoch.isCurrent(captured)) return
        state = { emergency: { state: 'error', message: String(error) } }
      })

    epoch.invalidate()
    state = {}
    if (mode === 'success') request.resolve({ latitude: 39.9 })
    else request.reject(new Error('stale emergency failure'))
    await completion
    assert.deepEqual(state, {})
  }
})

test('Family page emergency flow is explicit and never auto-fetches coordinates', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const refreshStart = page.indexOf('const refresh = async')
  const refreshEnd = page.indexOf('const create = async')
  const refreshBody = page.slice(refreshStart, refreshEnd)

  assert.match(refreshBody, /getFamilyEmergencyShares\(profile\.id\)/)
  assert.doesNotMatch(refreshBody, /getFamilyEmergencyLocation\(/)
  assert.match(page, /紧急共享我的位置/)
  assert.match(page, /showActionSheet[\s\S]*?30 分钟[\s\S]*?60 分钟[\s\S]*?180 分钟/)
  assert.match(page, /确认紧急共享位置/)
  assert.match(page, /仅共享：当前位置信息/)
  assert.match(page, /共享后可随时停止/)
  assert.match(page, /查看紧急位置/)
  assert.match(
    page,
    /const readEmergencyLocation = async[\s\S]*?capture\(\)[\s\S]*?getFamilyEmergencyLocation[\s\S]*?isCurrent\(readEpoch\)[\s\S]*?catch \(error\)[\s\S]*?isCurrent\(readEpoch\)/,
  )
  assert.match(
    page,
    /revokeFamilyEmergencyShare[\s\S]*?sensitiveReadEpoch\.current\.invalidate\(\)[\s\S]*?setEmergencyReads\(\{\}\)/,
  )
})

test('emergency share APIs use authenticated transport and fixed server duration inputs', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /request<unknown>\('GET', '\/family\/emergency-location-shares'\)/)
  assert.match(api, /parseFamilyEmergencyShares\(raw, currentUserId\)/)
  assert.match(api, /durationMinutes: 30 \| 60 \| 180/)
  assert.match(api, /duration_minutes: durationMinutes/)
  assert.match(api, /emergency-location-shares\/\$\{encodeURIComponent\(shareId\)\}\/location/)
})


test('emergency share parser rejects direction that does not match current user', () => {
  const raw = {
    share_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    resource_owner_user_id: OWNER_ID,
    grantee_user_id: MEMBER_ID,
    expires_at: '2026-09-25T11:30:00Z',
    created_at: '2026-09-25T11:00:00Z',
  }
  assert.throws(() => parseFamilyEmergencyShares([
    { ...raw, direction: 'OUTGOING' },
  ], MEMBER_ID), /家庭数据异常/)
  assert.throws(() => parseFamilyEmergencyShares([
    { ...raw, direction: 'INCOMING' },
  ], OWNER_ID), /家庭数据异常/)
})

test('emergency sharing uses safe stable error copy', () => {
  assert.equal(
    familyErrorMessage('EMERGENCY_SHARE_NOT_AVAILABLE', 'emergency-location'),
    '紧急位置共享已不可用',
  )
  assert.equal(
    familyErrorMessage('EMERGENCY_SHARE_TARGET_INVALID', 'emergency-share'),
    '只能选择当前家庭中的其他成员',
  )
  assert.equal(
    familyErrorMessage('EMERGENCY_SHARE_DURATION_UNSUPPORTED', 'emergency-share'),
    '请选择 30、60 或 180 分钟',
  )
})


test('arrival reminder parser enforces participant direction, terminal fields and safe projection', () => {
  const base = {
    reminder_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    resource_owner_user_id: OWNER_ID,
    grantee_user_id: MEMBER_ID,
    destination_place_id: OTHER_ID,
    destination_display_name: '家',
    status: 'ACTIVE',
    created_at: '2026-09-25T10:00:00Z',
    expires_at: '2026-09-25T12:00:00Z',
    arrived_at: null,
    direction: 'INCOMING',
    latitude: 39.9,
    longitude: 116.4,
    visit_id: 'must-not-leak',
  }
  const rows = parseFamilyArrivalReminders([base], MEMBER_ID)
  assert.equal(rows.length, 1)
  assert.deepEqual(Object.keys(rows[0]).sort(), [
    'arrived_at',
    'created_at',
    'destination_display_name',
    'destination_place_id',
    'direction',
    'expires_at',
    'grantee_user_id',
    'reminder_id',
    'resource_owner_user_id',
    'status',
  ])
  assert.equal((rows[0] as Record<string, unknown>).latitude, undefined)
  assert.equal((rows[0] as Record<string, unknown>).visit_id, undefined)

  assert.throws(() => parseFamilyArrivalReminders([
    { ...base, direction: 'OUTGOING' },
  ], MEMBER_ID), /家庭数据异常/)
  assert.throws(() => parseFamilyArrivalReminders([
    { ...base, status: 'ARRIVED', arrived_at: null },
  ], MEMBER_ID), /家庭数据异常/)
  assert.throws(() => parseFamilyArrivalReminders([
    { ...base, status: 'ACTIVE', arrived_at: '2026-09-25T11:00:00Z' },
  ], MEMBER_ID), /家庭数据异常/)
  assert.throws(() => parseFamilyArrivalReminders([
    { ...base, status: 'TRACKING' },
  ], MEMBER_ID), /家庭数据异常/)
  assert.throws(() => parseFamilyArrivalReminders([
    { ...base, expires_at: '2026-09-25T12:01:00Z' },
  ], MEMBER_ID), /家庭数据异常/)
  assert.throws(() => parseFamilyArrivalReminders([base, base], MEMBER_ID), /家庭数据异常/)
  assert.throws(() => parseFamilyArrivalReminders([{
    ...base,
    destination_display_name: '家'.repeat(201),
  }], MEMBER_ID), /家庭数据异常/)
})

test('arrival reminder parser rejects arrival at or after exact expiry boundary', () => {
  const base = {
    reminder_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    resource_owner_user_id: OWNER_ID,
    grantee_user_id: MEMBER_ID,
    destination_place_id: OTHER_ID,
    destination_display_name: '家',
    status: 'ARRIVED',
    created_at: '2026-09-25T10:00:00Z',
    expires_at: '2026-09-25T12:00:00Z',
    direction: 'INCOMING',
  }

  assert.throws(() => parseFamilyArrivalReminders([{
    ...base,
    arrived_at: '2026-09-25T12:00:00Z',
  }], MEMBER_ID), /家庭数据异常/)

  assert.throws(() => parseFamilyArrivalReminders([{
    ...base,
    arrived_at: '2026-09-25T13:00:00Z',
  }], MEMBER_ID), /家庭数据异常/)
})

test('arrival reminder ARRIVED parser requires a safe arrival timestamp', () => {
  const rows = parseFamilyArrivalReminders([{
    reminder_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    resource_owner_user_id: OWNER_ID,
    grantee_user_id: MEMBER_ID,
    destination_place_id: OTHER_ID,
    destination_display_name: '家',
    status: 'ARRIVED',
    created_at: '2026-09-25T10:00:00Z',
    expires_at: '2026-09-25T16:00:00Z',
    arrived_at: '2026-09-25T11:30:00Z',
    direction: 'INCOMING',
  }], MEMBER_ID)
  assert.equal(rows[0].status, 'ARRIVED')
  assert.equal(rows[0].arrived_at, '2026-09-25T11:30:00Z')
  assert.equal(familyArrivalStatusLabel('ACTIVE'), '等待到达')
  assert.equal(familyArrivalStatusLabel('ARRIVED'), '已到达')
  assert.equal(familyArrivalStatusLabel('CANCELLED'), '已取消')
  assert.equal(familyArrivalStatusLabel('EXPIRED'), '已过期')
})

test('Family page arrival reminder flow uses only own Places and coarse state', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/pages/family/index.tsx'), 'utf8')
  const refreshStart = page.indexOf('const refresh = async')
  const refreshEnd = page.indexOf('const create = async')
  const refreshBody = page.slice(refreshStart, refreshEnd)

  assert.match(refreshBody, /getFamilyArrivalReminders\(profile\.id\)/)
  assert.doesNotMatch(refreshBody, /listPlaces\(/)
  assert.match(
    page,
    /const createArrivalReminder = async[\s\S]*?listPlaces\(50\)[\s\S]*?2 小时[\s\S]*?6 小时[\s\S]*?12 小时/,
  )
  assert.match(page, /确认设置到家提醒/)
  assert.match(page, /仅共享：等待到达 \/ 已到达 \/ 已取消 \/ 已过期状态/)
  assert.match(page, /不会持续共享位置、路线或预计到达时间/)
  assert.match(page, /设置到家提醒/)
  assert.match(page, /收到的到家提醒/)
  assert.doesNotMatch(
    page,
    /arrivalReminders[\s\S]{0,300}getFamilyEmergencyLocation/,
  )
})

test('arrival reminder APIs expose no coordinate endpoint', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /request<unknown>\('GET', '\/family\/arrival-reminders'\)/)
  assert.match(api, /validityMinutes: 120 \| 360 \| 720/)
  assert.match(api, /destination_place_id: destinationPlaceId/)
  assert.match(api, /arrival-reminders\/\$\{encodeURIComponent\(reminderId\)\}\/cancel/)
  assert.doesNotMatch(api, /arrival-reminders\/.*location/)
})

test('arrival reminder error copy is bounded and non-tracking', () => {
  assert.equal(
    familyErrorMessage('ARRIVAL_REMINDER_NOT_AVAILABLE', 'arrival-reminder'),
    '到家提醒已不可用',
  )
  assert.equal(
    familyErrorMessage('ARRIVAL_REMINDER_DESTINATION_INVALID', 'arrival-reminder'),
    '只能选择你自己的已有地点',
  )
  assert.equal(
    familyErrorMessage('ARRIVAL_REMINDER_VALIDITY_UNSUPPORTED', 'arrival-reminder'),
    '请选择 2、6 或 12 小时',
  )
})
