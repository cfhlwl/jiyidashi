import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  buildPeoplePath,
  buildPersonCreatePayload,
  buildPersonPatchPayload,
  hasPersonPatchChanges,
  isPersonRevisionConflict,
  parsePersonList,
  parsePersonRead,
  PeopleUiAuthority,
  personDetailRoute,
  personErrorMessage,
  type PersonRead,
} from '../src/services/people'

const PERSON_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const PERSON_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'

function rawPerson(overrides: Record<string, unknown> = {}): unknown {
  return {
    id: PERSON_A,
    display_name: '王阿姨',
    relationship_label: '邻居',
    note: '住在楼上',
    aliases: ['王姐', '小王阿姨'],
    revision: 3,
    created_at: '2026-09-27T10:00:00Z',
    updated_at: '2026-09-27T10:05:00Z',
    ...overrides,
  }
}

function person(): PersonRead {
  return parsePersonRead(rawPerson())
}

test('Person parser publishes only canonical DTO fields and fails closed', () => {
  const parsed = parsePersonRead({ ...(rawPerson() as object), user_id: 'must-not-be-authority' }, PERSON_A)
  assert.deepEqual(Object.keys(parsed).sort(), [
    'aliases',
    'created_at',
    'display_name',
    'id',
    'note',
    'relationship_label',
    'revision',
    'updated_at',
  ])
  assert.equal(parsed.id, PERSON_A)
  assert.throws(() => parsePersonRead(rawPerson({ id: '' })), /人物数据异常/)
  assert.throws(() => parsePersonRead(rawPerson({ aliases: '王姐' })), /人物数据异常/)
  assert.throws(() => parsePersonRead(rawPerson({ aliases: [''] })), /人物数据异常/)
  assert.throws(() => parsePersonRead(rawPerson({ revision: -1 })), /人物数据异常/)
  assert.throws(() => parsePersonRead(rawPerson({ revision: 1.5 })), /人物数据异常/)
  assert.throws(() => parsePersonRead(rawPerson({ note: {} })), /人物数据异常/)
  assert.throws(() => parsePersonRead(rawPerson(), PERSON_B), /人物数据异常/)
})

test('People list accepts explicit empty, preserves server order, and rejects malformed/duplicate ids', () => {
  assert.deepEqual(parsePersonList([]), [])
  const rows = parsePersonList([
    rawPerson({ id: PERSON_B, display_name: '张老师' }),
    rawPerson({ id: PERSON_A, display_name: '王阿姨' }),
  ])
  assert.deepEqual(rows.map((row) => row.id), [PERSON_B, PERSON_A])
  assert.throws(() => parsePersonList({ items: [] }), /人物数据异常/)
  assert.throws(() => parsePersonList([rawPerson(), rawPerson()]), /人物数据异常/)
})

test('create payload trims explicit input and omits blank nullable fields instead of serializing null', () => {
  assert.deepEqual(
    buildPersonCreatePayload({
      displayName: '  王阿姨  ',
      relationshipLabel: '  ',
      note: '',
      aliases: [' 王姐 ', ' 小王阿姨 '],
    }),
    {
      display_name: '王阿姨',
      aliases: ['王姐', '小王阿姨'],
    },
  )
  assert.deepEqual(
    buildPersonCreatePayload({
      displayName: '李老师',
      relationshipLabel: ' 老师 ',
      note: ' 以前的班主任 ',
      aliases: [],
    }),
    {
      display_name: '李老师',
      relationship_label: '老师',
      note: '以前的班主任',
    },
  )
})

test('PATCH preserves expected_revision and omitted / null / aliases=[] semantics', () => {
  const base = person()
  const unchanged = buildPersonPatchPayload(base, {
    displayName: base.display_name,
    relationshipLabel: base.relationship_label || '',
    note: base.note || '',
    aliases: [...base.aliases],
  })
  assert.deepEqual(unchanged, { expected_revision: 3 })
  assert.equal(hasPersonPatchChanges(unchanged), false)

  const cleared = buildPersonPatchPayload(base, {
    displayName: base.display_name,
    relationshipLabel: ' ',
    note: '',
    aliases: [],
  })
  assert.deepEqual(cleared, {
    expected_revision: 3,
    relationship_label: null,
    note: null,
    aliases: [],
  })
  assert.equal(hasPersonPatchChanges(cleared), true)

  const renamed = buildPersonPatchPayload(base, {
    displayName: ' 王阿姨（新） ',
    relationshipLabel: base.relationship_label || '',
    note: base.note || '',
    aliases: [...base.aliases],
  })
  assert.deepEqual(renamed, {
    expected_revision: 3,
    display_name: '王阿姨（新）',
  })
})

test('alias input remains explicit, bounded, ordered, and blank aliases fail locally', () => {
  const base = person()
  const reordered = buildPersonPatchPayload(base, {
    displayName: base.display_name,
    relationshipLabel: base.relationship_label || '',
    note: base.note || '',
    aliases: ['小王阿姨', '王姐'],
  })
  assert.deepEqual(reordered.aliases, ['小王阿姨', '王姐'])
  assert.throws(() => buildPersonPatchPayload(base, {
    displayName: base.display_name,
    relationshipLabel: '',
    note: '',
    aliases: [''],
  }), /别名不能为空/)
  assert.throws(() => buildPersonCreatePayload({
    displayName: '测试',
    relationshipLabel: '',
    note: '',
    aliases: Array.from({ length: 101 }, (_, index) => `别名${index}`),
  }), /最多 100 个/)
})

test('People authority drops stale owner/session success and error', () => {
  const authority = new PeopleUiAuthority()
  const a = authority.capture('user-a', 7, 'people:list')
  assert.equal(authority.isCurrent(a, 'user-a', 7, 'people:list'), true)
  assert.equal(authority.isCurrent(a, 'user-b', 8, 'people:list'), false)
  assert.equal(authority.isCurrent(a, 'user-a', 8, 'people:list'), false)
})

test('detail A response cannot overwrite detail B and newer edit/reload wins', () => {
  const authority = new PeopleUiAuthority()
  const detailA = authority.capture('user-a', 2, PERSON_A)
  assert.equal(authority.isCurrent(detailA, 'user-a', 2, PERSON_B), false)

  authority.invalidate()
  const detailB = authority.capture('user-a', 2, PERSON_B)
  assert.equal(authority.isCurrent(detailA, 'user-a', 2, PERSON_A), false)
  assert.equal(authority.isCurrent(detailB, 'user-a', 2, PERSON_B), true)

  const editOne = detailB
  authority.invalidate()
  const reload = authority.capture('user-a', 2, PERSON_B)
  assert.equal(authority.isCurrent(editOne, 'user-a', 2, PERSON_B), false)
  assert.equal(authority.isCurrent(reload, 'user-a', 2, PERSON_B), true)
})

test('revision conflict is explicit and never mapped as a successful overwrite', () => {
  assert.equal(isPersonRevisionConflict('PERSON_REVISION_CONFLICT'), true)
  assert.equal(isPersonRevisionConflict('PERSON_NOT_FOUND'), false)
  assert.equal(personErrorMessage('PERSON_REVISION_CONFLICT'), '人物已发生变化，请查看最新内容后重新提交')
})

test('People API wrappers use only canonical CRUD endpoints and never send user_id', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  const start = api.indexOf('export async function listPeople')
  const end = api.indexOf('export async function getFamily')
  const peopleApi = api.slice(start, end)

  assert.match(peopleApi, /buildPeoplePath\(limit\)/)
  assert.match(peopleApi, /'POST', '\/people'/)
  assert.match(peopleApi, /'GET',[\s\S]*?`\/people\/\$\{encodeURIComponent\(personId\)\}`/)
  assert.match(peopleApi, /'PATCH'/)
  assert.match(peopleApi, /'DELETE'/)
  assert.doesNotMatch(peopleApi, /user_id|\/memories|\/relationships|\/graph/)
})

test('delete is named second-confirmation and failure keeps the Person visible', () => {
  const detail = readFileSync(resolve(process.cwd(), 'src/pages/person-detail/index.tsx'), 'utf8')
  const deleteStart = detail.indexOf('const confirmDelete = async')
  const deleteEnd = detail.indexOf("if (phase === 'signed-out')")
  const deleteFlow = detail.slice(deleteStart, deleteEnd)

  assert.match(deleteFlow, /Taro\.showModal/)
  assert.match(deleteFlow, /title: '删除人物？'/)
  assert.match(deleteFlow, /detail\.display_name/)
  assert.match(deleteFlow, /if \(!modal\.confirm \|\| !isCurrent\(modalSnapshot\)\) return/)
  assert.match(deleteFlow, /await deletePerson\(personId\)/)
  assert.match(deleteFlow, /删除失败，人物仍然保留/)
  assert.doesNotMatch(deleteFlow, /setDetail\(null\)/)
})

test('detail conflict reload preserves draft and does not auto-retry PATCH', () => {
  const detail = readFileSync(resolve(process.cwd(), 'src/pages/person-detail/index.tsx'), 'utf8')
  const refreshStart = detail.indexOf('const refreshAfterConflict = async')
  const refreshEnd = detail.indexOf('useEffect(() => subscribeElderMode')
  const conflictReload = detail.slice(refreshStart, refreshEnd)
  assert.match(conflictReload, /setDetail\(latest\)/)
  assert.match(conflictReload, /setEditing\(true\)/)
  assert.doesNotMatch(conflictReload, /setDraft\(/)

  const saveStart = detail.indexOf('const saveEdit = async')
  const saveEnd = detail.indexOf('const confirmDelete = async')
  const saveFlow = detail.slice(saveStart, saveEnd)
  assert.match(saveFlow, /isPersonRevisionConflict\(apiErrorCode\(saveError\)\)/)
  assert.match(saveFlow, /await refreshAfterConflict\(\)/)
  assert.equal((saveFlow.match(/patchPerson\(/g) || []).length, 1)
})

test('list/detail guard auth owner epoch and Elder mode without hidden gesture controls', () => {
  const list = readFileSync(resolve(process.cwd(), 'src/pages/people/index.tsx'), 'utf8')
  const detail = readFileSync(resolve(process.cwd(), 'src/pages/person-detail/index.tsx'), 'utf8')
  for (const source of [list, detail]) {
    assert.match(source, /new PeopleUiAuthority\(\)/)
    assert.match(source, /currentAuthenticatedUserId\(\)/)
    assert.match(source, /currentAuthSessionEpoch\(\)/)
    assert.match(source, /subscribeAuthSession/)
    assert.match(source, /subscribeElderMode\(setElderMode\)/)
    assert.match(source, /elderClassName\(elderMode\)/)
  }
  assert.match(list, /createOpen \? '收起新增' : '新增人物'/)
  assert.match(detail, /onClick=\{beginEdit\}/)
  assert.match(detail, /'删除人物'/)
})

test('list/create publish success and errors only while owner-session action snapshot is current', () => {
  const list = readFileSync(resolve(process.cwd(), 'src/pages/people/index.tsx'), 'utf8')
  const loadStart = list.indexOf('const loadPeople = async')
  const loadEnd = list.indexOf('useEffect(() => subscribeElderMode')
  const loadFlow = list.slice(loadStart, loadEnd)
  assert.match(loadFlow, /const snapshot = authority\.current\.capture\(owner, currentAuthSessionEpoch\(\), identity\)/)
  assert.match(loadFlow, /const rows = await listPeople\(100\)[\s\S]*?if \(!isCurrent\(snapshot, identity\)\) return[\s\S]*?setPeople\(rows\)/)
  assert.match(loadFlow, /catch[\s\S]*?if \(!isCurrent\(snapshot, identity\)\) return[\s\S]*?setError\(/)

  const createStart = list.indexOf('const submitCreate = async')
  const createEnd = list.indexOf('const openDetail = async')
  const createFlow = list.slice(createStart, createEnd)
  assert.match(createFlow, /const created = await createPerson\(payload\)[\s\S]*?if \(!isCurrent\(snapshot, identity\)\) return/)
  assert.match(createFlow, /catch \(createError\)[\s\S]*?if \(!isCurrent\(snapshot, identity\)\) return/)
})

test('PATCH and DELETE publish success/error only while exact detail owner-session snapshot is current', () => {
  const detail = readFileSync(resolve(process.cwd(), 'src/pages/person-detail/index.tsx'), 'utf8')

  const saveStart = detail.indexOf('const saveEdit = async')
  const saveEnd = detail.indexOf('const confirmDelete = async')
  const saveFlow = detail.slice(saveStart, saveEnd)
  assert.match(saveFlow, /const snapshot = authority\.current\.capture\(owner, currentAuthSessionEpoch\(\), personId\)/)
  assert.match(saveFlow, /const updated = await patchPerson\(personId, payload\)[\s\S]*?if \(!isCurrent\(snapshot\)\) return[\s\S]*?setDetail\(updated\)/)
  assert.match(saveFlow, /catch \(saveError\)[\s\S]*?if \(!isCurrent\(snapshot\)\) return/)

  const deleteStart = detail.indexOf('const confirmDelete = async')
  const deleteEnd = detail.indexOf("if (phase === 'signed-out')")
  const deleteFlow = detail.slice(deleteStart, deleteEnd)
  assert.match(deleteFlow, /if \(!modal\.confirm \|\| !isCurrent\(modalSnapshot\)\) return/)
  assert.match(deleteFlow, /await deletePerson\(personId\)[\s\S]*?if \(!isCurrent\(snapshot\)\) return[\s\S]*?Taro\.navigateBack\(\)/)
  assert.match(deleteFlow, /catch \(deleteError\)[\s\S]*?if \(!isCurrent\(snapshot\)\) return/)
})

test('Mini V2-A navigation is under 我的 and does not add a sixth tab or graph scope', () => {
  const app = readFileSync(resolve(process.cwd(), 'src/app.config.ts'), 'utf8')
  const profile = readFileSync(resolve(process.cwd(), 'src/pages/profile/index.tsx'), 'utf8')
  const list = readFileSync(resolve(process.cwd(), 'src/pages/people/index.tsx'), 'utf8')
  const detail = readFileSync(resolve(process.cwd(), 'src/pages/person-detail/index.tsx'), 'utf8')
  const service = readFileSync(resolve(process.cwd(), 'src/services/people.ts'), 'utf8')

  assert.match(app, /'pages\/people\/index'/)
  assert.match(app, /'pages\/person-detail\/index'/)
  assert.equal((app.match(/pagePath:/g) || []).length, 5)
  assert.match(profile, /url: '\/pages\/people\/index'/)

  const v2a = [list, detail, service].join('\n')
  assert.doesNotMatch(v2a, /PersonMemory|memory timeline|\/memories|\/relationships|\/graph|face recognition|contact/i)
})

test('route/list path carry only Person identity and bounded limit', () => {
  assert.equal(buildPeoplePath(100), '/people?limit=100')
  assert.throws(() => buildPeoplePath(101), /1 到 100/)
  assert.equal(
    personDetailRoute(PERSON_A),
    `/pages/person-detail/index?personId=${PERSON_A}`,
  )
  assert.equal(personDetailRoute(PERSON_A).includes('user_id='), false)
})
