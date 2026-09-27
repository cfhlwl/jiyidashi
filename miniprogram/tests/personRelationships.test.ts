import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  buildPersonRelationshipCreatePayload,
  buildPersonRelationshipPatchPayload,
  buildPersonRelationshipPath,
  buildPersonRelationshipsPath,
  candidatePeopleForRelationship,
  parsePersonRelationshipList,
  parsePersonRelationshipRead,
  PersonRelationshipUiAuthority,
  personRelationshipErrorMessage,
  rebasePersonRelationshipDraft,
  relationshipKindLabel,
  type PersonRelationshipProjection,
} from '../src/services/personRelationships'
import { parsePersonList } from '../src/services/people'

const OWNER = '11111111-1111-4111-8111-111111111111'
const PERSON_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const PERSON_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const PERSON_C = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
const EDGE_A = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'

function projection(overrides: Record<string, unknown> = {}): unknown {
  return {
    relationship_id: EDGE_A,
    relationship_kind: 'FRIEND',
    custom_label: null,
    note: '大学同学',
    revision: 3,
    other_person: {
      id: PERSON_B,
      display_name: '小王',
    },
    created_at: '2026-09-20T01:00:00Z',
    updated_at: '2026-09-21T01:00:00Z',
    ...overrides,
  }
}

function personRow(id: string, name: string): unknown {
  return {
    id,
    display_name: name,
    relationship_label: null,
    note: null,
    aliases: [],
    revision: 0,
    created_at: '2026-09-20T01:00:00Z',
    updated_at: '2026-09-20T01:00:00Z',
  }
}

test('projection parser accepts exact DTO and strips extra server fields', () => {
  const row = parsePersonRelationshipList([
    projection({ hidden_score: 9, user_id: OWNER }),
  ], PERSON_A, 100)[0]
  assert.deepEqual(Object.keys(row).sort(), [
    'created_at',
    'custom_label',
    'note',
    'other_person',
    'relationship_id',
    'relationship_kind',
    'revision',
    'updated_at',
  ])
  assert.equal(Object.prototype.hasOwnProperty.call(row, 'hidden_score'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(row, 'user_id'), false)
})

test('projection collection is strict and collection-level fail-closed', () => {
  assert.throws(() => parsePersonRelationshipList([
    projection(),
    projection({
      relationship_id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
      relationship_kind: 'UNKNOWN',
    }),
    projection({
      relationship_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      other_person: { id: PERSON_C, display_name: '小李' },
    }),
  ], PERSON_A, 100), /人物关系数据异常/)

  assert.throws(() => parsePersonRelationshipList([
    projection({ other_person: { id: PERSON_A, display_name: '自己' } }),
  ], PERSON_A), /人物关系数据异常/)
  assert.throws(() => parsePersonRelationshipList([
    projection({ revision: -1 }),
  ], PERSON_A), /人物关系数据异常/)
  assert.throws(() => parsePersonRelationshipList([
    projection({ created_at: '2026-09-20' }),
  ], PERSON_A), /人物关系数据异常/)
})

test('exact five relationship kinds and labels are locked', () => {
  assert.deepEqual(
    ['FAMILY', 'FRIEND', 'COLLEAGUE', 'CLASSMATE', 'OTHER'].map((kind) =>
      relationshipKindLabel(kind as any)),
    ['家人', '朋友', '同事', '同学', '其他'],
  )
  assert.throws(() => parsePersonRelationshipList([
    projection({ relationship_kind: 'PARTNER' }),
  ], PERSON_A), /人物关系数据异常/)
})

test('OTHER requires trimmed custom_label while non-OTHER never submits one', () => {
  assert.deepEqual(
    buildPersonRelationshipCreatePayload(PERSON_A, PERSON_B, {
      relationshipKind: 'OTHER',
      customLabel: '  羽毛球搭子  ',
      note: '',
    }),
    {
      person_a_id: PERSON_A,
      person_b_id: PERSON_B,
      relationship_kind: 'OTHER',
      custom_label: '羽毛球搭子',
    },
  )
  assert.throws(() => buildPersonRelationshipCreatePayload(PERSON_A, PERSON_B, {
    relationshipKind: 'OTHER',
    customLabel: ' ',
    note: '',
  }), /必须填写/)
  assert.deepEqual(
    buildPersonRelationshipCreatePayload(PERSON_A, PERSON_B, {
      relationshipKind: 'FRIEND',
      customLabel: '旧的 OTHER 标签',
      note: '',
    }),
    {
      person_a_id: PERSON_A,
      person_b_id: PERSON_B,
      relationship_kind: 'FRIEND',
    },
  )
})

test('create payload preserves endpoint direction, rejects self, and never sends user_id', () => {
  const payload = buildPersonRelationshipCreatePayload(PERSON_B, PERSON_A, {
    relationshipKind: 'CLASSMATE',
    customLabel: '',
    note: '  高中同学  ',
  })
  assert.deepEqual(payload, {
    person_a_id: PERSON_B,
    person_b_id: PERSON_A,
    relationship_kind: 'CLASSMATE',
    note: '高中同学',
  })
  assert.equal(Object.prototype.hasOwnProperty.call(payload, 'user_id'), false)
  assert.throws(() => buildPersonRelationshipCreatePayload(PERSON_A, PERSON_A, {
    relationshipKind: 'FRIEND',
    customLabel: '',
    note: '',
  }), /不能把人物与自己/)
})

test('canonical create response accepts reversed unordered endpoints', () => {
  const read = parsePersonRelationshipRead({
    id: EDGE_A,
    person_a_id: PERSON_A,
    person_b_id: PERSON_B,
    relationship_kind: 'FRIEND',
    custom_label: null,
    note: null,
    revision: 0,
    created_at: '2026-09-20T01:00:00Z',
    updated_at: '2026-09-20T01:00:00Z',
  }, EDGE_A, PERSON_B, PERSON_A)
  assert.equal(read.id, EDGE_A)
})

test('PATCH carries expected_revision, never endpoints, and note null clears', () => {
  const base = parsePersonRelationshipList([projection()], PERSON_A)[0]
  assert.deepEqual(buildPersonRelationshipPatchPayload(base, {
    relationshipKind: 'FRIEND',
    customLabel: '',
    note: '',
  }), {
    expected_revision: 3,
    note: null,
  })

  const patch = buildPersonRelationshipPatchPayload(base, {
    relationshipKind: 'COLLEAGUE',
    customLabel: 'stale',
    note: '大学同学',
  })
  assert.deepEqual(patch, {
    expected_revision: 3,
    relationship_kind: 'COLLEAGUE',
  })
  assert.equal(Object.prototype.hasOwnProperty.call(patch || {}, 'person_a_id'), false)
  assert.equal(Object.prototype.hasOwnProperty.call(patch || {}, 'person_b_id'), false)
})

test('OTHER -> non-OTHER omits stale label and non-OTHER -> OTHER requires explicit label', () => {
  const otherBase = parsePersonRelationshipList([projection({
    relationship_kind: 'OTHER',
    custom_label: '牌友',
  })], PERSON_A)[0]
  assert.deepEqual(buildPersonRelationshipPatchPayload(otherBase, {
    relationshipKind: 'FRIEND',
    customLabel: '牌友',
    note: '大学同学',
  }), {
    expected_revision: 3,
    relationship_kind: 'FRIEND',
  })

  const friendBase = parsePersonRelationshipList([projection()], PERSON_A)[0]
  assert.throws(() => buildPersonRelationshipPatchPayload(friendBase, {
    relationshipKind: 'OTHER',
    customLabel: '',
    note: '大学同学',
  }), /必须填写/)
})

test('field-aware rebase never writes back server-only note change from stale draft', () => {
  const base = parsePersonRelationshipList([projection()], PERSON_A)[0]
  const latest = parsePersonRelationshipList([projection({
    revision: 4,
    note: '服务器新备注',
  })], PERSON_A)[0]
  const rebased = rebasePersonRelationshipDraft(base, {
    relationshipKind: 'COLLEAGUE',
    customLabel: '',
    note: '大学同学',
  }, latest)

  assert.deepEqual(rebased.conflicts, [])
  assert.equal(rebased.keepUserDraft.relationshipKind, 'COLLEAGUE')
  assert.equal(rebased.keepUserDraft.note, '服务器新备注')
  assert.deepEqual(buildPersonRelationshipPatchPayload(latest, rebased.keepUserDraft), {
    expected_revision: 4,
    relationship_kind: 'COLLEAGUE',
  })
})

test('same-field relationship/note conflicts require explicit resolution candidates', () => {
  const base = parsePersonRelationshipList([projection()], PERSON_A)[0]
  const latest = parsePersonRelationshipList([projection({
    relationship_kind: 'FAMILY',
    note: '服务器备注',
    revision: 4,
  })], PERSON_A)[0]
  const rebased = rebasePersonRelationshipDraft(base, {
    relationshipKind: 'COLLEAGUE',
    customLabel: '',
    note: '我的备注',
  }, latest)

  assert.deepEqual(rebased.conflicts, ['relationship', 'note'])
  assert.equal(rebased.keepUserDraft.relationshipKind, 'COLLEAGUE')
  assert.equal(rebased.keepUserDraft.note, '我的备注')
  assert.equal(rebased.keepServerDraft.relationshipKind, 'FAMILY')
  assert.equal(rebased.keepServerDraft.note, '服务器备注')
})

test('candidate picker excludes current Person only and keeps same display names distinct/order', () => {
  const people = parsePersonList([
    personRow(PERSON_A, '小王'),
    personRow(PERSON_B, '同名'),
    personRow(PERSON_C, '同名'),
  ])
  const candidates = candidatePeopleForRelationship(people, PERSON_A)
  assert.deepEqual(candidates.map((person) => person.id), [PERSON_B, PERSON_C])
  assert.deepEqual(candidates.map((person) => person.display_name), ['同名', '同名'])
})

test('relationship UI authority binds owner, route, edge, revision and selected candidate', () => {
  const authority = new PersonRelationshipUiAuthority()
  const snapshot = authority.capture({
    owner: OWNER,
    sessionEpoch: 5,
    personId: PERSON_A,
    action: 'patch',
    relationshipId: EDGE_A,
    revision: 3,
    otherPersonId: PERSON_B,
  })
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 5,
    personId: PERSON_A,
    action: 'patch',
    relationshipId: EDGE_A,
    revision: 3,
    otherPersonId: PERSON_B,
  }), true)
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 5,
    personId: PERSON_C,
    action: 'patch',
    relationshipId: EDGE_A,
    revision: 3,
    otherPersonId: PERSON_B,
  }), false)
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 6,
    personId: PERSON_A,
    action: 'patch',
    relationshipId: EDGE_A,
    revision: 3,
    otherPersonId: PERSON_B,
  }), false)
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 5,
    personId: PERSON_A,
    action: 'patch',
    relationshipId: EDGE_A,
    revision: 3,
    otherPersonId: PERSON_C,
  }), false)
  authority.invalidate()
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 5,
    personId: PERSON_A,
    action: 'patch',
    relationshipId: EDGE_A,
    revision: 3,
    otherPersonId: PERSON_B,
  }), false)
})

test('bounded errors cover direct-edge conflicts without raw backend detail', () => {
  assert.match(personRelationshipErrorMessage('PERSON_RELATIONSHIP_CONFLICT') || '', /已经存在/)
  assert.match(personRelationshipErrorMessage('PERSON_RELATIONSHIP_REVISION_CONFLICT') || '', /已经变化/)
  assert.match(personRelationshipErrorMessage('PERSON_RELATIONSHIP_CUSTOM_LABEL_REQUIRED') || '', /必须填写/)
  assert.equal(personRelationshipErrorMessage('RAW_SQL_ERROR secret'), null)
})

test('paths are exact direct-edge surfaces', () => {
  assert.equal(
    buildPersonRelationshipsPath(PERSON_A, 100),
    '/people/' + PERSON_A + '/relationships?limit=100',
  )
  assert.equal(
    buildPersonRelationshipPath(EDGE_A),
    '/people/relationships/' + EDGE_A,
  )
})

test('component locks explicit create conflict, revision conflict and destructive copy', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')
  assert.match(source, /PERSON_RELATIONSHIP_CONFLICT/)
  assert.match(source, /await refreshRelationships\(true\)/)
  assert.match(source, /PERSON_RELATIONSHIP_REVISION_CONFLICT/)
  assert.match(source, /recoverEditConflict\(base, editDraft\)/)
  assert.equal((source.match(/patchPersonRelationship\(/g) || []).length, 1)
  assert.match(source, /title: '删除人物关系？'/)
  assert.match(source, /不会删除任何人物或记忆/)
  assert.match(source, /删除关系失败，当前关系仍然保留/)
})

test('component has explicit text kind choices and no local ranking/inference/traversal', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')
  assert.match(source, /relationshipKindLabel\(kind\)/)
  assert.match(source, /添加人物关系/)
  assert.match(source, /编辑关系/)
  assert.match(source, /删除关系/)
  assert.doesNotMatch(source, /sort\(|rank|score|frequency|travers|suggest|infer/i)
})

test('V2-C API adapter uses only canonical direct-edge endpoints and never deletes Person/Memory', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  const start = api.indexOf('export async function listPersonRelationships')
  const end = api.indexOf('export async function listPersonMemoryTimeline')
  const block = api.slice(start, end)
  assert.match(block, /'POST', '\/people\/relationships'/)
  assert.match(block, /buildPersonRelationshipsPath/)
  assert.match(block, /buildPersonRelationshipPath/)
  assert.match(block, /'PATCH'/)
  assert.match(block, /'DELETE'/)
  assert.doesNotMatch(block, /DELETE[^\n]*\/people\/\$\{encodeURIComponent\(personId\)\}/)
  assert.doesNotMatch(block, /\/memories\//)
  assert.doesNotMatch(block, /user_id/)
})

test('candidate picker malformed collection fails closed before current-Person filtering', () => {
  assert.throws(() => parsePersonList([
    personRow(PERSON_A, '当前'),
    { ...(personRow(PERSON_B, '坏数据') as Record<string, unknown>), aliases: 'not-an-array' },
    personRow(PERSON_C, '其他'),
  ]), /人物数据异常/)

  const parsedWithInvalidEndpointId = parsePersonList([
    personRow(PERSON_A, '当前'),
    personRow('not-a-uuid', '坏端点'),
    personRow(PERSON_C, '其他'),
  ])
  assert.throws(
    () => candidatePeopleForRelationship(parsedWithInvalidEndpointId, PERSON_A),
    /人物关系数据异常/,
  )
})

test('relationship list preserves canonical backend order without local ranking', () => {
  const secondEdge = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
  const rows = parsePersonRelationshipList([
    projection({ relationship_id: secondEdge, other_person: { id: PERSON_C, display_name: '后创建' } }),
    projection({ relationship_id: EDGE_A, other_person: { id: PERSON_B, display_name: '先创建' } }),
  ], PERSON_A)
  assert.deepEqual(rows.map((row) => row.relationship_id), [secondEdge, EDGE_A])
})

test('response relationship shape fails closed for invalid OTHER/non-OTHER custom labels', () => {
  assert.throws(() => parsePersonRelationshipList([
    projection({ relationship_kind: 'OTHER', custom_label: null }),
  ], PERSON_A), /人物关系数据异常/)
  assert.throws(() => parsePersonRelationshipList([
    projection({ relationship_kind: 'FRIEND', custom_label: '不应存在' }),
  ], PERSON_A), /人物关系数据异常/)
})

test('create conflict refreshes canonical list and never falls back to PATCH', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')
  const start = source.indexOf('const submitCreate = async')
  const end = source.indexOf('const beginEdit')
  const createFlow = source.slice(start, end)
  assert.match(createFlow, /PERSON_RELATIONSHIP_CONFLICT/)
  assert.match(createFlow, /await refreshRelationships\(true\)/)
  assert.doesNotMatch(createFlow, /patchPersonRelationship\(/)
})

test('revision conflict rebases latest canonical edge and requires explicit re-save', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')
  const recoverStart = source.indexOf('const recoverEditConflict = async')
  const recoverEnd = source.indexOf('const saveEdit = async')
  const recovery = source.slice(recoverStart, recoverEnd)
  assert.match(recovery, /listPersonRelationships\(personId, 100\)/)
  assert.match(recovery, /rebasePersonRelationshipDraft\(base, userDraft, latest\)/)
  assert.match(recovery, /title: '人物关系同时被修改'/)
  assert.match(recovery, /confirmText: '保留我的修改'/)
  assert.match(recovery, /cancelText: '使用服务器值'/)
  assert.match(recovery, /setEditBase\(latest\)/)
  assert.match(recovery, /setEditDraft\(nextDraft\)/)

  const saveStart = source.indexOf('const saveEdit = async')
  const saveEnd = source.indexOf('const confirmDelete')
  const saveFlow = source.slice(saveStart, saveEnd)
  assert.equal((saveFlow.match(/patchPersonRelationship\(/g) || []).length, 1)
  assert.match(saveFlow, /PERSON_RELATIONSHIP_REVISION_CONFLICT/)
  assert.match(saveFlow, /await recoverEditConflict\(base, editDraft\)/)
})

test('list/create/PATCH/DELETE success and errors are gated by current relationship authority', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')
  assert.match(source, /listPersonRelationships\(personId, 100\)[\s\S]*?authority\.current\.isCurrent\(snapshot/)
  assert.match(source, /createPersonRelationship\([\s\S]*?authority\.current\.isCurrent\(snapshot/)
  assert.match(source, /patchPersonRelationship\([\s\S]*?authority\.current\.isCurrent/)
  assert.match(source, /deletePersonRelationship\(row\.relationship_id\)[\s\S]*?authority\.current\.isCurrent/)
  assert.match(source, /subscribeAuthSession/)
})

test('relationship feature never calls graph/traversal or destructive Person/Memory controls', () => {
  const component = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')
  const service = readFileSync(resolve(process.cwd(), 'src/services/personRelationships.ts'), 'utf8')
  const source = [component, service].join('\n')
  assert.doesNotMatch(source, /\/graph|\/relationships\/neighborhood|travers|friends.of.friends/i)
  assert.doesNotMatch(source, /deletePerson\(|deleteMemory\(|createTextMemory\(/)
})

test('Mini CI keeps V2-A/V2-B triggers and adds canonical V2-C surfaces', () => {
  const workflow = readFileSync(resolve(process.cwd(), '../.github/workflows/miniprogram-ci.yml'), 'utf8')
  for (const path of [
    'backend/app/api/people.py',
    'backend/app/person_schemas.py',
    'backend/app/services/person_service.py',
    'backend/app/person_memory_schemas.py',
    'backend/app/services/person_memory_service.py',
    'backend/app/api/memories.py',
    'backend/app/person_relationship_schemas.py',
    'backend/app/services/person_relationship_service.py',
    'backend/app/person_relationship_models.py',
  ]) {
    assert.equal(workflow.includes(path), true)
  }
})

test('Person free-text relationship_label remains separate from direct-edge relationship state', () => {
  const personService = readFileSync(resolve(process.cwd(), 'src/services/people.ts'), 'utf8')
  const relationshipService = readFileSync(resolve(process.cwd(), 'src/services/personRelationships.ts'), 'utf8')
  assert.match(personService, /relationship_label/)
  assert.doesNotMatch(relationshipService, /relationship_label/)
})

test('create relationship requires an explicit kind selection before POST', () => {
  assert.throws(() => buildPersonRelationshipCreatePayload(PERSON_A, PERSON_B, {
    relationshipKind: null,
    customLabel: '',
    note: '',
  }), /请选择人物关系类型/)

  const source = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')
  assert.match(source, /const EMPTY_CREATE_DRAFT: PersonRelationshipCreateDraft = \{[\s\S]*?relationshipKind: null/)
  assert.match(source, /disabled=\{createDraft\.relationshipKind === null \|\| Boolean\(mutationKey\)\}/)

  const createStart = source.indexOf('const submitCreate = async')
  const createEnd = source.indexOf('const beginEdit')
  const createFlow = source.slice(createStart, createEnd)
  assert.match(createFlow, /buildPersonRelationshipCreatePayload\(personId, selectedOtherId, createDraft\)/)
  assert.doesNotMatch(createFlow, /relationshipKind:\s*'FAMILY'/)
})

test('PATCH and conflict recovery lock edit controls until the current operation finishes', () => {
  const source = readFileSync(resolve(process.cwd(), 'src/components/personRelationships/PersonRelationshipsSection.tsx'), 'utf8')

  const saveStart = source.indexOf('const saveEdit = async')
  const saveEnd = source.indexOf('const confirmDelete')
  const saveFlow = source.slice(saveStart, saveEnd)
  const revisionBranch = saveFlow.slice(
    saveFlow.indexOf("if (apiErrorCode(patchError) === 'PERSON_RELATIONSHIP_REVISION_CONFLICT')"),
    saveFlow.indexOf("setStatus(personRelationshipErrorMessage"),
  )
  assert.match(revisionBranch, /await recoverEditConflict\(base, editDraft\)/)
  assert.doesNotMatch(revisionBranch, /setMutationKey\(''\)/)

  const recoveryStart = source.indexOf('const recoverEditConflict = async')
  const recoveryEnd = source.indexOf('const saveEdit = async')
  const recovery = source.slice(recoveryStart, recoveryEnd)
  assert.match(recovery, /finally \{[\s\S]*?setMutationKey\(''\)/)

  const editorStart = source.indexOf("<View className='relationship-editor'>")
  const editorEnd = source.indexOf("</View>\n          ) : (", editorStart)
  const editor = source.slice(editorStart, editorEnd > editorStart ? editorEnd : editorStart + 6500)
  assert.match(editor, /disabled=\{Boolean\(mutationKey\)\}[\s\S]*?value=\{editDraft\.customLabel\}/)
  assert.match(editor, /disabled=\{Boolean\(mutationKey\)\}[\s\S]*?value=\{editDraft\.note\}/)
})
