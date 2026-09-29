import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'
import test from 'node:test'

const lifePage = readFileSync(resolve(process.cwd(), 'src/pages/life/index.tsx'), 'utf8')
const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
const appConfig = readFileSync(resolve(process.cwd(), 'src/app.config.ts'), 'utf8')
const todayPage = readFileSync(resolve(process.cwd(), 'src/pages/index/index.tsx'), 'utf8')
const personDetail = readFileSync(resolve(process.cwd(), 'src/pages/person-detail/index.tsx'), 'utf8')
const knownDuration = readFileSync(
  resolve(process.cwd(), 'src/components/personKnownDuration/PersonKnownDurationSection.tsx'),
  'utf8',
)

test('Mini navigation exposes one coherent Life area, not seven home buttons', () => {
  assert.match(appConfig, /pages\/life\/index/)
  assert.match(todayPage, /打开人生/)
  assert.match(todayPage, /\/pages\/life\/index/)
  assert.match(lifePage, /人生事件/)
  assert.match(lifePage, /人生阶段/)
  assert.match(lifePage, /多年时间线/)
  assert.match(lifePage, /年度电子回忆录/)
  assert.match(lifePage, /人生回忆录/)
})

test('all seven flows use canonical current APIs', () => {
  const block = api.slice(
    api.indexOf('function createAdvancedV2RequestSessionGuard'),
    api.indexOf('export async function listPeople'),
  )
  for (const path of [
    '/life-events',
    '/life-stages',
    '/reason',
    '/life-history/timeline',
    '/memoirs/annual',
    '/memoirs/life/stages',
    '/known-duration',
  ]) {
    assert.match(block, new RegExp(path.replaceAll('/', '\\/')))
  }
  assert.doesNotMatch(block, /user_id|confidence|plan_code|trust_state|evidence_id/)
  assert.match(block, /\{ question: question\.trim\(\) \}/)
  assert.match(block, /\{ target_year: targetYear \}/)
})

test('LifeEvent place field uses owner-scoped canonical Place rows, not a free UUID', () => {
  assert.match(lifePage, /listPlaces\(100\)/)
  assert.match(lifePage, /placeChoices\.map\(\(place\) => place\.name\)/)
  assert.match(lifePage, /placeId: index <= 0 \? '' : \(placeChoices\[index - 1\]\?\.id \|\| ''\)/)
  assert.match(lifePage, /place_id: draft\.placeId \|\| null/)
  assert.doesNotMatch(lifePage, /placeholder=['"][^'"]*place[_ ]?id/i)
  assert.match(lifePage, /placeAuthority\.current\.invalidate\(\)/)
})

test('LifeEvent evidence picker uses actual owner Memory rows and no free UUID input', () => {
  assert.match(lifePage, /listMemoryPickerRows\(owner, 50\)/)
  assert.match(lifePage, /memory\.source_type !== 'AI_INFERENCE'/)
  assert.match(lifePage, /linkLifeEventMemory\(target\.id, memory\.id\)/)
  assert.doesNotMatch(lifePage, /placeholder=['"]Memory UUID/)
})

test('LifeStage links only existing loaded events and never auto-links by similarity', () => {
  assert.match(lifePage, /availableEvents = events\.filter/)
  assert.match(lifePage, /linkLifeStageEvent\(stage\.id, event\.id\)/)
  assert.doesNotMatch(lifePage, /similarity|autoLink|auto-link/i)
})

test('destructive event/stage/unlink actions use existing explicit modal confirmation', () => {
  assert.match(lifePage, /title: '删除人生事件？'/)
  assert.match(lifePage, /title: '删除人生阶段？'/)
  assert.match(lifePage, /title: '取消证据关联？'/)
  assert.match(lifePage, /title: '取消事件关联？'/)
  assert.doesNotMatch(lifePage, /SEC-014/)
})

test('deterministic surfaces do not consume AI presentation labels', () => {
  assert.match(lifePage, /这是服务端确定性投影，不是 AI 推断/)
  assert.match(knownDuration, /不会根据人物创建时间、别名或关系记录猜测/)
  assert.doesNotMatch(knownDuration, /AI 推断|reasoningPresentation|annualNarrativePresentation/)
  assert.match(personDetail, /PersonKnownDurationSection/)
})

test('actual AI surfaces explicitly reuse SEC-013 mappings', () => {
  assert.match(lifePage, /reasoningPresentation\(reasoning\.status\)/)
  assert.match(lifePage, /annualNarrativePresentation\(annual\.narrative_status\)/)
  assert.match(lifePage, /lifeMemoirPresentation\(chapter\)/)
  assert.match(lifePage, /state === 'INFERRED'/)
  assert.match(lifePage, /reasoning\.citations\.map/)
  assert.match(lifePage, /annual\.narrative_citations\.map/)
  assert.match(lifePage, /chapter\.citations\.map/)
})

test('Life section navigation invalidates hidden requests and published AI state', () => {
  assert.match(lifePage, /const openSection = \(next: Section\) => \{[\s\S]*?invalidateAll\(\)/)
  assert.match(lifePage, /setReasoning\(null\)/)
  assert.match(lifePage, /setAnnual\(null\)/)
  assert.match(lifePage, /setChapter\(null\)/)
  assert.match(lifePage, /onClick=\{\(\) => openSection\('home'\)\}/)
})

test('owner/session/page/resource authority invalidates old reads and AI generations', () => {
  assert.match(lifePage, /subscribeAuthSession/)
  assert.match(lifePage, /useDidHide/)
  assert.match(lifePage, /invalidateAll\(\)/)
  assert.match(lifePage, /eventDetailAuthority\.current\.invalidate\(\)/)
  assert.match(lifePage, /reasoningAuthority\.current\.invalidate\(\)/)
  assert.match(lifePage, /historyAuthority\.current\.invalidate\(\)/)
  assert.match(lifePage, /annualAuthority\.current\.invalidate\(\)/)
  assert.match(lifePage, /memoirChapterAuthority\.current\.invalidate\(\)/)
  assert.match(knownDuration, /currentAuthSessionEpoch\(\)/)
})

test('pagination passes opaque cursors and resets on range/year switches', () => {
  assert.match(lifePage, /getLifeHistory\(range\.start, range\.end, \{ limit: 50, cursor: nextCursor \}\)/)
  assert.match(lifePage, /getAnnualMemoirPhotos\(annual\.target_year, \{ limit: 24, cursor: annualPhotoCursor \}\)/)
  assert.match(lifePage, /getLifeMemoirStages\(\{ limit: 50, cursor: nextCursor \}\)/)
  assert.match(lifePage, /setHistoryCursor\(null\)/)
  assert.match(lifePage, /setAnnualPhotoCursor\(null\)/)
  assert.match(lifePage, /setMemoirCursor\(null\)/)
})

test('AI identity switches release old local gates without letting stale finally clear a new gate', () => {
  assert.match(lifePage, /reasoningAuthority\.current\.invalidate\(\)[\s\S]*?reasoningGate\.current\.end\(\)/)
  assert.match(lifePage, /memoirChapterAuthority\.current\.invalidate\(\)[\s\S]*?chapterGate\.current\.end\(\)/)
  assert.match(lifePage, /annualAuthority\.current\.invalidate\(\)[\s\S]*?annualGate\.current\.end\(\)/)
  assert.match(
    lifePage,
    /if \(isCurrent\(reasoningAuthority\.current, snapshot\)\) \{[\s\S]*?reasoningGate\.current\.end\(\)/,
  )
  assert.match(
    lifePage,
    /if \(isCurrent\(annualAuthority\.current, snapshot\)\) \{[\s\S]*?annualGate\.current\.end\(\)/,
  )
  assert.match(
    lifePage,
    /if \(isCurrent\(memoirChapterAuthority\.current, snapshot\)\) \{[\s\S]*?chapterGate\.current\.end\(\)/,
  )
})

test('mutation workflow uses token-bound gate and owner/session-bound continuation', () => {
  assert.match(lifePage, /new AdvancedV2MutationFlight\(\)/)
  assert.match(lifePage, /mutationGate\.current\.invalidate\(\)/)
  assert.match(lifePage, /continueAdvancedV2Mutation\(/)
  assert.match(lifePage, /currentAuthenticatedUserId,[\s\S]*?currentAuthSessionEpoch/)
  assert.match(
    lifePage,
    /await continueMutationRefresh\(snapshot, \[[\s\S]*?loadEvents,[\s\S]*?loadEventDetail\(saved\.id\)/,
  )
  assert.match(
    lifePage,
    /await continueMutationRefresh\(snapshot, \[[\s\S]*?loadStages,[\s\S]*?loadStageDetail\(saved\.id\)/,
  )
  assert.match(lifePage, /mutationGate\.current\.end\(snapshot\.mutationToken\)/)
  assert.match(lifePage, /if \(mutationGate\.current\.end\(snapshot\.mutationToken\)\)/)
})

test('mutating and generating actions use local single-flight gates', () => {
  assert.match(lifePage, /mutationGate/)
  assert.match(lifePage, /reasoningGate/)
  assert.match(lifePage, /annualGate/)
  assert.match(lifePage, /chapterGate/)
})

test('verified annual photo gallery signs only selected canonical media item', () => {
  assert.match(lifePage, /getVerifiedMediaDownload\(mediaId\)/)
  assert.match(lifePage, /Taro\.previewImage/)
  assert.doesNotMatch(lifePage, /listObjects|bucket|objectKey|object_key/)
})
