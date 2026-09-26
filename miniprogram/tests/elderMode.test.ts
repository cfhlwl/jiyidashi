import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ElderProjectionStore,
  elderClassName,
  parseElderUserProfile,
} from '../src/services/elderMode'

const base = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  nickname: '测试用户',
  email: 'elder@example.com',
  timezone: 'Asia/Shanghai',
  locale: 'zh-CN',
}

test('elder profile accepts exact boolean and defaults malformed preference to normal mode', () => {
  assert.equal(parseElderUserProfile({ ...base, elder_mode_enabled: true }).elder_mode_enabled, true)
  assert.equal(parseElderUserProfile({ ...base, elder_mode_enabled: false }).elder_mode_enabled, false)

  for (const malformed of ['true', 1, 0, null, {}, []]) {
    assert.equal(
      parseElderUserProfile({ ...base, elder_mode_enabled: malformed }).elder_mode_enabled,
      false,
    )
  }
  assert.equal(parseElderUserProfile(base).elder_mode_enabled, false)
})

test('elder class modifier is presentation-only', () => {
  assert.equal(elderClassName(false), 'page')
  assert.equal(elderClassName(true), 'page elder-mode')
})

test('profile mutation is self-only partial PATCH and session projection clears on auth changes', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')

  assert.match(api, /updateElderMode\(enabled: boolean\)/)
  assert.match(api, /updateProfile\(\{ elder_mode_enabled: enabled \}\)/)
  assert.match(api, /payload\.elder_mode_enabled = input\.elder_mode_enabled/)
  assert.match(
    api,
    /export function updateElderMode\(enabled: boolean\): Promise<UserProfile> \{[\s\S]*?updateProfile\(\{ elder_mode_enabled: enabled \}\)/,
  )
  assert.doesNotMatch(
    api,
    /updateElderMode\([^)]*userId|updateElderMode[\s\S]{0,180}target_user_id/,
  )
  assert.match(api, /authSessionEpoch \+= 1[\s\S]*?resetElderProjection\(\)/)
  assert.match(api, /epoch !== authSessionEpoch/)
  assert.match(api, /const elderProjection = new ElderProjectionStore\(\)/)
  assert.match(api, /resetElderProjection\(\)[\s\S]*?elderProjection\.reset\(\)/)
  assert.match(api, /elderProjection\.publish\(profile\.id, profile\.elder_mode_enabled\)/)
  assert.match(api, /elderProjection\.current\(currentAuthOwner\(\)\)/)
})

test('Mini elder mode is profile-driven and Family role never enables it', () => {
  const profile = readFileSync(resolve(process.cwd(), 'src/pages/profile/index.tsx'), 'utf8')
  const home = readFileSync(resolve(process.cwd(), 'src/pages/index/index.tsx'), 'utf8')

  assert.match(profile, /updateElderMode\(enabled\)/)
  assert.match(profile, /profile\.elder_mode_enabled/)
  assert.match(profile, /只调整你自己的文字大小、按钮尺寸和页面层级/)
  assert.match(home, /getProfile\(\)[\s\S]*?profile\.elder_mode_enabled/)
  assert.doesNotMatch(profile, /current_user_role[\s\S]*?elder/i)
  assert.doesNotMatch(home, /FamilyRole|current_user_role/)
})

test('elder home only elevates existing production capabilities', () => {
  const home = readFileSync(resolve(process.cwd(), 'src/pages/index/index.tsx'), 'utf8')

  assert.match(home, /switchTab\(\{ url: '\/pages\/capture\/index' \}\)/)
  assert.match(home, /switchTab\(\{ url: '\/pages\/query\/index' \}\)/)
  assert.match(home, /switchTab\(\{ url: '\/pages\/family\/index' \}\)/)
  assert.match(home, /今天去了哪里/)
  assert.match(home, /本页下方“今日足迹”直接展示现有可信 Visit 数据/)
  assert.doesNotMatch(home, /elder.*intent|elder.*ASR|帮我记一下|我想找东西/)
})

test('elder shared CSS keeps minimum logical touch target and same palette tokens', () => {
  const css = readFileSync(resolve(process.cwd(), 'src/app.scss'), 'utf8')
  assert.match(css, /\.elder-mode[\s\S]*?button[\s\S]*?min-height: 96rpx/)
  assert.match(css, /\.elder-mode \.primary-button/)
  assert.doesNotMatch(css, /\.elder-mode[\s\S]*?#(?:ff0000|000000)/i)
})


test('Mini process bootstrap is normal until authoritative profile publishes elder state', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /const elderProjection = new ElderProjectionStore\(\)/)
  assert.doesNotMatch(api, /getStorageSync<boolean>\([^)]*elder/i)
})

test('mounted capture/query react normal -> elder when projection toggles ON', () => {
  const capture = readFileSync(resolve(process.cwd(), 'src/pages/capture/index.tsx'), 'utf8')
  const query = readFileSync(resolve(process.cwd(), 'src/pages/query/index.tsx'), 'utf8')
  for (const source of [capture, query]) {
    assert.match(source, /useState\(currentElderModeEnabled\)/)
    assert.match(source, /useEffect\(\(\) => subscribeElderMode\(setElderMode\), \[\]\)/)
    assert.match(source, /elderClassName\(elderMode\)/)
  }

  const store = new ElderProjectionStore()
  const seen: boolean[] = []
  const unsubscribe = store.subscribe(() => 'user-a', (enabled) => seen.push(enabled))
  assert.deepEqual(seen, [false])
  store.publish('user-a', true)
  assert.deepEqual(seen, [false, true])
  unsubscribe()
})

test('mounted capture/query react elder -> normal when projection toggles OFF', () => {
  const store = new ElderProjectionStore()
  const seen: boolean[] = []
  const unsubscribe = store.subscribe(() => 'user-a', (enabled) => seen.push(enabled))
  store.publish('user-a', true)
  store.publish('user-a', false)
  assert.deepEqual(seen, [false, true, false])
  unsubscribe()
})

test('account switch cannot leave user A elder UI mounted for user B', () => {
  const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
  assert.match(api, /logout\(\)[\s\S]*?resetElderProjection\(\)/)
  assert.match(api, /loginAccount[\s\S]*?authSessionEpoch \+= 1[\s\S]*?resetElderProjection\(\)/)
  assert.match(api, /epoch !== authSessionEpoch/)

  const store = new ElderProjectionStore()
  let owner: string | null = 'user-a'
  const seen: boolean[] = []
  const unsubscribe = store.subscribe(() => owner, (enabled) => seen.push(enabled))

  store.publish('user-a', true)
  store.reset()
  owner = 'user-b'
  store.publish('user-b', false)

  assert.deepEqual(seen, [false, true, false, false])
  assert.equal(store.current('user-a'), false)
  assert.equal(store.current('user-b'), false)
  unsubscribe()
})
