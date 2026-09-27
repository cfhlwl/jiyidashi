import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import {
  buildMemoryPickerPath,
  buildPersonInteractionsPath,
  buildPersonMemoryCreatePayload,
  buildPersonMemoryLinkPath,
  buildPersonMemoryPatchPayload,
  buildPersonMemoryTimelinePath,
  parseMemoryPickerRows,
  parsePersonInteractions,
  parsePersonMemoryLink,
  parsePersonMemoryTimeline,
  PersonMemoryUiAuthority,
  personMemoryErrorMessage,
  personMemoryRelationLabel,
} from '../src/services/personMemories'

const OWNER = '11111111-1111-4111-8111-111111111111'
const PERSON_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const PERSON_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const MEMORY_A = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
const MEMORY_B = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
const LINK_A = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'

function timelineRow(overrides: Record<string, unknown> = {}): unknown {
  return {
    id: LINK_A,
    person_id: PERSON_A,
    memory_id: MEMORY_A,
    relation_kind: 'RELATED',
    revision: 2,
    created_at: '2026-09-20T01:00:00Z',
    updated_at: '2026-09-21T01:00:00Z',
    occurred_at: '2026-09-19T08:30:00+08:00',
    memory_title: '一起喝茶',
    memory_content: '下午在小区门口聊了半小时。',
    memory_type: 'NOTE',
    ...overrides,
  }
}

function memoryRead(overrides: Record<string, unknown> = {}): unknown {
  return {
    id: MEMORY_A,
    user_id: OWNER,
    memory_type: 'NOTE',
    title: '旧同学聚会',
    content: '记录内容',
    occurred_at: '2026-09-20T09:00:00+08:00',
    source_type: 'USER_TEXT',
    confidence: 1,
    place_id: null,
    latitude: null,
    longitude: null,
    is_confirmed: true,
    metadata_json: {},
    edit_revision: 0,
    edited_at: null,
    created_at: '2026-09-20T01:00:00Z',
    ...overrides,
  }
}

test('timeline parser is strict, bounded, person-bound and preserves server order', () => {
  const rows = parsePersonMemoryTimeline([
    timelineRow({ memory_id: MEMORY_A, hidden_score: 999 }),
    timelineRow({
      id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      memory_id: MEMORY_B,
      relation_kind: 'MET',
    }),
  ], PERSON_A, 50)
  assert.deepEqual(rows.map((row) => row.memory_id), [MEMORY_A, MEMORY_B])
  assert.equal(Object.prototype.hasOwnProperty.call(rows[0], 'hidden_score'), false)
  assert.throws(() => parsePersonMemoryTimeline([timelineRow({ person_id: PERSON_B })], PERSON_A), /人物记忆数据异常/)
  assert.throws(() => parsePersonMemoryTimeline([timelineRow({ relation_kind: 'FRIEND' })], PERSON_A), /人物记忆数据异常/)
  assert.throws(() => parsePersonMemoryTimeline([timelineRow({ revision: -1 })], PERSON_A), /人物记忆数据异常/)
  assert.throws(() => parsePersonMemoryTimeline([timelineRow({ occurred_at: '2026-09-19' })], PERSON_A), /人物记忆数据异常/)
  assert.throws(() => parsePersonMemoryTimeline([timelineRow({ memory_content: ' ' })], PERSON_A), /人物记忆数据异常/)
  assert.throws(() => parsePersonMemoryTimeline([timelineRow({ memory_type: 'UNKNOWN' })], PERSON_A), /人物记忆数据异常/)
  assert.throws(() => parsePersonMemoryTimeline(Array.from({ length: 51 }, () => timelineRow()), PERSON_A, 50), /人物记忆数据异常/)
})

test('Memory picker reuses strict MemoryRead, keeps current owner only, and preserves order', () => {
  const rows = parseMemoryPickerRows([
    memoryRead({ id: MEMORY_A }),
    memoryRead({ id: MEMORY_B, user_id: '22222222-2222-4222-8222-222222222222' }),
    { ...(memoryRead() as Record<string, unknown>), id: 'not-a-uuid' },
    memoryRead({ id: MEMORY_B }),
  ], OWNER, 50)
  assert.deepEqual(rows.map((row) => row.id), [MEMORY_A, MEMORY_B])
  assert.ok(rows.every((row) => row.user_id === OWNER))
})

test('RELATED/MET create is explicit; PATCH uses latest revision and same relation is no-op', () => {
  assert.deepEqual(buildPersonMemoryCreatePayload('RELATED'), { relation_kind: 'RELATED' })
  assert.deepEqual(buildPersonMemoryCreatePayload('MET'), { relation_kind: 'MET' })
  const link = parsePersonMemoryLink(timelineRow(), PERSON_A, MEMORY_A)
  assert.equal(buildPersonMemoryPatchPayload(link, 'RELATED'), null)
  assert.deepEqual(buildPersonMemoryPatchPayload(link, 'MET'), {
    relation_kind: 'MET',
    expected_revision: 2,
  })
})

test('paths are exact and never send user_id', () => {
  assert.equal(buildPersonMemoryTimelinePath(PERSON_A, 50), `/people/${PERSON_A}/memories?limit=50`)
  assert.equal(buildPersonMemoryLinkPath(PERSON_A, MEMORY_A), `/people/${PERSON_A}/memories/${MEMORY_A}`)
  assert.equal(buildPersonInteractionsPath(20), '/people/interactions?limit=20')
  assert.equal(buildMemoryPickerPath(50), '/timeline?limit=50')
  assert.equal(buildPersonMemoryLinkPath(PERSON_A, MEMORY_A).includes('user_id='), false)
})

test('stable error mapping hides unknown backend detail', () => {
  assert.equal(personMemoryErrorMessage('PERSON_MEMORY_LINK_RELATION_CONFLICT'), '这条记忆已经以另一种关系关联，请先刷新或修改关系')
  assert.equal(personMemoryErrorMessage('PERSON_MEMORY_LINK_REVISION_CONFLICT'), '这条人物记忆关联已经变化，请刷新后重新选择关系')
  assert.equal(personMemoryErrorMessage('SENSITIVE_RAW_DETAIL'), null)
})

test('recent interactions accept MET only and preserve server order', () => {
  const rows = parsePersonInteractions([
    {
      id: LINK_A,
      person_id: PERSON_A,
      memory_id: MEMORY_A,
      relation_kind: 'MET',
      revision: 1,
      created_at: '2026-09-20T01:00:00Z',
      updated_at: '2026-09-20T01:00:00Z',
      person_display_name: '王阿姨',
      occurred_at: '2026-09-26T10:00:00+08:00',
    },
    {
      id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
      person_id: PERSON_B,
      memory_id: MEMORY_B,
      relation_kind: 'MET',
      revision: 0,
      created_at: '2026-09-18T01:00:00Z',
      updated_at: '2026-09-18T01:00:00Z',
      person_display_name: '李老师',
      occurred_at: '2026-09-20T10:00:00+08:00',
    },
  ], 20)
  assert.deepEqual(rows.map((row) => row.person_display_name), ['王阿姨', '李老师'])
  assert.throws(() => parsePersonInteractions([{ ...rows[0], relation_kind: 'RELATED' }]), /人物记忆数据异常/)
})

test('action guard binds owner, epoch, person, memory, revision and generation', () => {
  const authority = new PersonMemoryUiAuthority()
  const snapshot = authority.capture({
    owner: OWNER,
    sessionEpoch: 4,
    personId: PERSON_A,
    action: 'patch:MET',
    memoryId: MEMORY_A,
    linkRevision: 2,
  })
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 4,
    personId: PERSON_A,
    action: 'patch:MET',
    memoryId: MEMORY_A,
    linkRevision: 2,
  }), true)
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 5,
    personId: PERSON_A,
    action: 'patch:MET',
    memoryId: MEMORY_A,
    linkRevision: 2,
  }), false)
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 4,
    personId: PERSON_B,
    action: 'patch:MET',
    memoryId: MEMORY_A,
    linkRevision: 2,
  }), false)
  authority.invalidate()
  assert.equal(authority.isCurrent(snapshot, {
    owner: OWNER,
    sessionEpoch: 4,
    personId: PERSON_A,
    action: 'patch:MET',
    memoryId: MEMORY_A,
    linkRevision: 2,
  }), false)
})

test('UI requires explicit relation choice and never infers MET', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/components/personMemories/PersonMemorySection.tsx'), 'utf8')
  assert.match(page, /setSelectedRelation\('RELATED'\)/)
  assert.match(page, /setSelectedRelation\('MET'\)/)
  assert.match(page, /selectedRelation === 'RELATED'/)
  assert.match(page, /selectedRelation === 'MET'/)
  assert.doesNotMatch(page, /infer|guess|detect.*met/i)
})

test('relation create/revision conflicts refresh canonical timeline and do not auto-PATCH', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/components/personMemories/PersonMemorySection.tsx'), 'utf8')
  assert.match(page, /PERSON_MEMORY_LINK_RELATION_CONFLICT/)
  assert.match(page, /PERSON_MEMORY_LINK_REVISION_CONFLICT/)
  assert.equal((page.match(/patchPersonMemoryLink\(/g) || []).length, 1)
})

test('unlink confirmation says Memory is not deleted and failed unlink stays visible', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/components/personMemories/PersonMemorySection.tsx'), 'utf8')
  assert.match(page, /title: '取消人物关联？'/)
  assert.match(page, /不会删除这条记忆/)
  assert.match(page, /取消关联失败，当前关联仍然保留/)
})

test('timeline, picker and all mutations publish only after current action snapshot', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/components/personMemories/PersonMemorySection.tsx'), 'utf8')
  assert.match(page, /listPersonMemoryTimeline\(personId, 50\)[\s\S]*?isCurrent\(snapshot/)
  assert.match(page, /listMemoryPickerRows\(owner, 50\)[\s\S]*?isCurrent\(snapshot/)
  assert.match(page, /createPersonMemoryLink\([\s\S]*?isCurrent\(snapshot/)
  assert.match(page, /patchPersonMemoryLink\([\s\S]*?isCurrent\(snapshot/)
  assert.match(page, /deletePersonMemoryLink\([\s\S]*?isCurrent\(snapshot/)
})

test('recent interactions are backend projection only and stale owner responses are guarded', () => {
  const page = readFileSync(resolve(process.cwd(), 'src/components/personMemories/RecentPersonInteractions.tsx'), 'utf8')
  assert.match(page, /listPersonInteractions\(20\)/)
  assert.match(page, /isCurrent\(snapshot, identity\(\)\)/)
  assert.match(page, /subscribeAuthSession/)
  assert.doesNotMatch(page, /sort\(|rank|score|frequency|streak/i)
})

test('V2-B source stays out of relationships/graph and Memory management', () => {
  const section = readFileSync(resolve(process.cwd(), 'src/components/personMemories/PersonMemorySection.tsx'), 'utf8')
  const recent = readFileSync(resolve(process.cwd(), 'src/components/personMemories/RecentPersonInteractions.tsx'), 'utf8')
  const service = readFileSync(resolve(process.cwd(), 'src/services/personMemories.ts'), 'utf8')
  const source = [section, recent, service].join('\n')
  assert.doesNotMatch(source, /\/relationships|\/graph|deleteMemory\(|createTextMemory\(|submitMemoryFeedback/)
})

test('relation labels are exact', () => {
  assert.equal(personMemoryRelationLabel('RELATED'), '相关')
  assert.equal(personMemoryRelationLabel('MET'), '见过 / 互动过')
})

test('V2-B API adapter uses only canonical endpoints and never Memory DELETE', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  const start = api.indexOf('export async function listPersonMemoryTimeline')
  const end = api.indexOf('export async function getFamily')
  const block = api.slice(start, end)
  assert.match(block, /buildPersonMemoryTimelinePath/)
  assert.match(block, /buildPersonMemoryLinkPath/)
  assert.match(block, /buildPersonInteractionsPath/)
  assert.match(block, /buildMemoryPickerPath/)
  assert.doesNotMatch(block, /\/relationships|\/graph/)
  assert.doesNotMatch(block, /request<void>\('DELETE', `\/memories\//)
})

test('Mini CI remains bound to V2-A and all V2-B backend contracts', () => {
  const workflow = readFileSync(resolve(process.cwd(), '../.github/workflows/miniprogram-ci.yml'), 'utf8')
  for (const path of [
    'backend/app/api/people.py',
    'backend/app/person_schemas.py',
    'backend/app/services/person_service.py',
    'backend/app/person_memory_schemas.py',
    'backend/app/services/person_memory_service.py',
    'backend/app/api/memories.py',
    'backend/app/schemas.py',
  ]) {
    assert.equal(workflow.includes(path), true)
  }
})
