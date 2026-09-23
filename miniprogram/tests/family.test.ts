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
  parseFamilyCurrentLocation,
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
