import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  CaptureActionAuthority,
  deriveElderRememberState,
  elderRememberStateLabel,
  isCaptureActionStaleError,
} from '../src/services/elderRemember'

const capture = readFileSync(resolve(process.cwd(), 'src/pages/capture/index.tsx'), 'utf8')
const api = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')
const css = readFileSync(resolve(process.cwd(), 'src/pages/capture/index.scss'), 'utf8')

test('elder remember is reactive voice-first presentation only', () => {
  assert.match(capture, /useState\(currentElderModeEnabled\)/)
  assert.match(capture, /subscribeElderMode\(setElderMode\)/)
  assert.match(capture, /elderMode \? '帮我记一下' : '记一下'/)
  assert.match(capture, /elderMode && \([\s\S]*?className='card elder-remember-card'/)
  assert.match(capture, /开始说/)
  assert.match(capture, /说完了/)
  assert.match(capture, /保存这段话/)
  assert.match(capture, /我想打字记/)
  assert.match(capture, /拍张照片记住/)
})

test('entering elder capture page never starts microphone automatically', () => {
  const startDefinition = capture.indexOf('const startVoiceRecording = async')
  assert.ok(startDefinition > 0)
  const beforeExplicitHandler = capture.slice(0, startDefinition)
  assert.doesNotMatch(beforeExplicitHandler, /recorderController\.start\(\)/)

  assert.match(
    capture,
    /onClick=\{startVoiceRecording\}[\s\S]*?>\s*开始说\s*<\/Button>/,
  )
  assert.match(
    capture,
    /onClick=\{stopVoiceRecording\}[\s\S]*?>\s*说完了\s*<\/Button>/,
  )
})

test('elder voice reuses the existing recorder submission and single-flight seams', () => {
  assert.match(capture, /new VoiceSubmissionLock\(\)/)
  assert.match(capture, /voiceSubmitLock\.current\.tryAcquire\(\)/)
  assert.match(capture, /submitVoiceMemory\(/)
  assert.match(capture, /createAudioMediaUpload/)
  assert.match(capture, /putSignedMediaObject/)
  assert.match(capture, /completeAudioMediaUpload/)
  assert.match(capture, /createVoiceMemory/)
  assert.match(capture, /RecorderLifecycleController/)
})

test('elder text and photo reuse existing trusted capture APIs', () => {
  assert.match(capture, /createTextMemory\(content, title\)/)
  assert.match(capture, /submitPhotoMemory\(/)
  assert.match(capture, /createImageMediaUpload/)
  assert.match(capture, /completeImageMediaUpload/)
  assert.match(capture, /createPhotoMemory/)
  assert.doesNotMatch(api, /\/elder\/.*(?:memory|capture|voice|intent)/)
})

test('privacy pause is informative and does not disable explicit elder capture', () => {
  assert.match(capture, /getPrivacyStatus\(\)/)
  assert.match(
    capture,
    /自动记录已暂停；你主动记下的内容仍可以保存。/,
  )
  const heroStart = capture.indexOf("className='card elder-remember-card'")
  const heroEnd = capture.indexOf("className='card'", heroStart + 1)
  const hero = capture.slice(heroStart, heroEnd > heroStart ? heroEnd : undefined)
  assert.doesNotMatch(hero, /privacyPaused[\s\S]*?disabled/)
  assert.match(hero, /disabled=\{busy\}/)
})

test('capture session guard blocks stale account continuation without persistence', () => {
  assert.match(api, /export function createCaptureSessionGuard\(\): \(\) => void/)
  assert.match(api, /const epoch = authSessionEpoch/)
  assert.match(api, /const owner = currentAuthOwner\(\)/)
  assert.match(api, /epoch !== authSessionEpoch \|\| currentAuthOwner\(\) !== owner/)
  assert.doesNotMatch(api, /setStorageSync\([^\n]*capture/i)
  assert.match(capture, /const guard = createCaptureSessionGuard\(\)/)
})

test('permission denial recovery remains explicit', () => {
  assert.match(capture, /ensureMicrophonePermission\(microphonePermissionAdapter\)/)
  assert.match(capture, /voicePermission === 'denied'/)
  assert.match(capture, /openMicrophoneSettings/)
  assert.match(capture, /recoverMicrophonePermission\(microphonePermissionAdapter\)/)
  assert.match(capture, /打开设置恢复麦克风权限/)
})

test('elder remember has no AI intent or wake-word routing', () => {
  assert.doesNotMatch(capture, /intentRouter|wake.?word|always.?listen|LLM|elder.*prompt/i)
  assert.doesNotMatch(api, /elder.*(?:intent|asr|prompt)|(?:intent|prompt).*elder/i)
  assert.doesNotMatch(capture, /queryMemory\(/)
})

test('elder remember controls meet enlarged target and non-color state requirements', () => {
  assert.match(css, /\.elder-remember-primary[\s\S]*?min-height: 112rpx/)
  assert.match(css, /\.elder-voice-state[\s\S]*?font-size: 40rpx/)
  assert.match(capture, /aria-live='polite'/)
  assert.match(capture, /aria-label='开始说'/)
  assert.match(capture, /aria-label='说完了'/)
  assert.match(capture, /aria-label='保存这段话'/)
  assert.match(capture, /elderVoiceState/)
})


test('cached Mini capture clears local state on auth session change and tab hide', () => {
  assert.match(api, /export function subscribeAuthSession/)
  assert.match(capture, /subscribeAuthSession\(/)
  assert.match(capture, /resetLocalCaptureForSessionChange/)
  assert.match(capture, /deleteTempFile\(voiceClipRef\.current\?\.tempFilePath\)/)
  assert.match(capture, /deleteTempFile\(selectedPhotoRef\.current\?\.tempFilePath\)/)
  assert.match(capture, /useDidHide\(\(\) =>/)
  assert.match(capture, /discardNextVoiceStopRef\.current = true/)
  assert.match(capture, /录音已因离开页面而取消；不会上传或保存。/)
})

test('stale account errors never repopulate capture UI', () => {
  assert.match(capture, /function isStaleCaptureSessionError/)
  assert.match(capture, /if \(!isStaleCaptureSessionError\(error\)\)[\s\S]*?setStatus/)
  assert.match(capture, /if \(!isStaleCaptureSessionError\(error\)\)[\s\S]*?setPhotoError/)
  assert.match(capture, /if \(!isStaleCaptureSessionError\(error\)\)[\s\S]*?setVoiceError/)
})


test('Elder remember state machine maps recorder and trusted submission phases exactly', () => {
  const base = {
    recording: false,
    hasClip: false,
    memorySaved: false,
    submitting: false,
    phase: 'recorded' as const,
    hasError: false,
  }
  assert.equal(deriveElderRememberState(base), 'IDLE')
  assert.equal(deriveElderRememberState({ ...base, recording: true }), 'RECORDING')
  assert.equal(deriveElderRememberState({ ...base, hasClip: true }), 'RECORDED')
  assert.equal(
    deriveElderRememberState({ ...base, hasClip: true, submitting: true, phase: 'uploading' }),
    'UPLOADING',
  )
  assert.equal(
    deriveElderRememberState({ ...base, hasClip: true, submitting: true, phase: 'verifying' }),
    'VERIFYING',
  )
  assert.equal(
    deriveElderRememberState({ ...base, hasClip: true, submitting: true, phase: 'transcribing' }),
    'TRANSCRIBING',
  )
  assert.equal(deriveElderRememberState({ ...base, memorySaved: true }), 'SAVED')
  assert.equal(deriveElderRememberState({ ...base, hasError: true, phase: 'failed' }), 'FAILED')

  assert.equal(elderRememberStateLabel('IDLE'), '准备好了，点“开始说”')
  assert.equal(elderRememberStateLabel('RECORDING'), '正在听你说')
  assert.equal(elderRememberStateLabel('RECORDED'), '已经录好了')
  assert.equal(elderRememberStateLabel('SAVED'), '已经记住了')
  assert.equal(elderRememberStateLabel('FAILED'), '这次没有保存成功')
})


test('pending microphone permission cannot revive recorder after capture action invalidation', async () => {
  const authority = new CaptureActionAuthority()
  let sessionValid = true
  let recorderStartCount = 0
  let resolvePermission!: (granted: boolean) => void
  const permission = new Promise<boolean>((resolve) => {
    resolvePermission = resolve
  })
  const sessionGuard = () => {
    if (!sessionValid) throw new Error('登录状态已变化；旧会话不可继续')
  }
  const action = authority.begin(sessionGuard)

  const pendingStart = (async () => {
    const granted = await permission
    action.assertCurrent()
    if (granted) recorderStartCount += 1
  })()

  sessionValid = false
  authority.invalidate()
  resolvePermission(true)

  await assert.rejects(pendingStart, (error: unknown) => {
    assert.equal(
      isCaptureActionStaleError(error)
        || (error instanceof Error && error.message.startsWith('登录状态已变化；')),
      true,
    )
    return true
  })
  assert.equal(recorderStartCount, 0)
})

test('pending photo picker cannot publish A-origin result after account switch to B', async () => {
  const authority = new CaptureActionAuthority()
  let owner = 'user-a'
  let selectedPhoto: string | null = null
  let resolvePicker!: (path: string) => void
  const picker = new Promise<string>((resolve) => {
    resolvePicker = resolve
  })
  const snapshotOwner = owner
  const action = authority.begin(() => {
    if (owner !== snapshotOwner) throw new Error('登录状态已变化；旧账号素材不可继续')
  })

  const pendingSelection = (async () => {
    const path = await picker
    action.assertCurrent()
    selectedPhoto = path
  })()

  owner = 'user-b'
  authority.invalidate()
  resolvePicker('wxfile://tmp/a-origin.jpg')

  await assert.rejects(pendingSelection)
  assert.equal(selectedPhoto, null)
})

test('same-session permission and picker completions remain usable', async () => {
  const authority = new CaptureActionAuthority()
  let owner = 'user-a'
  let recorderStartCount = 0
  let selectedPhoto: string | null = null
  const snapshotOwner = owner
  const sessionGuard = () => {
    if (owner !== snapshotOwner) throw new Error('session changed')
  }

  const voiceAction = authority.begin(sessionGuard)
  const granted = await Promise.resolve(true)
  voiceAction.assertCurrent()
  if (granted) recorderStartCount += 1

  const photoAction = authority.begin(sessionGuard)
  const path = await Promise.resolve('wxfile://tmp/same-session.jpg')
  photoAction.assertCurrent()
  selectedPhoto = path

  assert.equal(recorderStartCount, 1)
  assert.equal(selectedPhoto, 'wxfile://tmp/same-session.jpg')
  owner = 'user-a'
})
