import assert from 'node:assert/strict'
import test from 'node:test'

import {
  submitVoiceMemory,
  VoiceSubmissionLock,
  type AudioMediaRead,
  type AudioMediaUploadResponse,
  type VoiceSubmissionPhase,
} from '../src/services/voiceCapture'
import type { SignedTransfer } from '../src/services/photoCapture'

const transfer: SignedTransfer = {
  method: 'PUT',
  url: 'https://private-storage.test/upload?temporary=1',
  headers: { 'Content-Type': 'audio/mpeg' },
  expires_at: '2026-09-17T12:00:00Z',
}

function pendingMedia(): AudioMediaUploadResponse {
  return {
    id: 'media-1',
    kind: 'AUDIO',
    status: 'PENDING',
    content_type: 'audio/mpeg',
    size_bytes: 8,
    original_filename: 'voice.mp3',
    created_at: '2026-09-17T11:00:00Z',
    completed_at: null,
    upload: transfer,
  }
}

function readyMedia(): AudioMediaRead {
  return {
    ...pendingMedia(),
    status: 'READY',
    completed_at: '2026-09-17T11:00:01Z',
  }
}

// [人工注释][S1-004][S1-007] 正常链必须严格经过原始 body -> signed PUT -> READY ->
// voice-memory；客户端只传 title/occurred_at，绝不提交 transcript/confidence。
test('voice submission runs upload, READY verification and server ASR memory in order', async () => {
  const phases: VoiceSubmissionPhase[] = []
  const calls: string[] = []
  const body = new Uint8Array([0x49, 0x44, 0x33, 1, 2, 3, 4, 5]).buffer

  const result = await submitVoiceMemory(
    {
      clientUploadId: '11111111-1111-4111-8111-111111111111',
      originalFilename: 'voice.mp3',
      title: '  复查安排  ',
      occurredAt: '2026-09-17T19:00:00+08:00',
      loadBody: async () => {
        calls.push('load')
        return body
      },
    },
    {
      createUpload: async (input) => {
        calls.push('create')
        assert.equal(input.contentType, 'audio/mpeg')
        assert.equal(input.sizeBytes, 8)
        assert.equal(input.clientUploadId, '11111111-1111-4111-8111-111111111111')
        return pendingMedia()
      },
      putUpload: async (signed, uploaded) => {
        calls.push('put')
        assert.equal(signed, transfer)
        assert.equal(uploaded.byteLength, 8)
      },
      completeUpload: async (mediaId) => {
        calls.push('complete')
        assert.equal(mediaId, 'media-1')
        return readyMedia()
      },
      createVoiceMemory: async (mediaId, input) => {
        calls.push('memory')
        assert.equal(mediaId, 'media-1')
        assert.deepEqual(input, {
          title: '复查安排',
          occurredAt: '2026-09-17T19:00:00+08:00',
        })
        return {
          media: readyMedia(),
          memory: { id: 'memory-1', content: '明天下午复查', confidence: 0.91 },
        }
      },
    },
    (phase) => phases.push(phase),
  )

  assert.deepEqual(result, { mediaId: 'media-1', memoryId: 'memory-1' })
  assert.deepEqual(calls, ['load', 'create', 'put', 'complete', 'memory'])
  assert.deepEqual(phases, ['uploading', 'verifying', 'transcribing', 'saved'])
})

// [人工注释][S1-007] 如果同一 client_upload_id 已经完成 READY（例如上次 ASR 超时），
// 重试不得再次 PUT/complete，只重新请求服务端 voice-memory。
test('READY retry skips upload and only retries server voice memory', async () => {
  let putCalls = 0
  let completeCalls = 0
  const phases: VoiceSubmissionPhase[] = []

  const result = await submitVoiceMemory(
    {
      clientUploadId: '22222222-2222-4222-8222-222222222222',
      originalFilename: 'voice.mp3',
      loadBody: async () => new Uint8Array([0x49, 0x44, 0x33]).buffer,
    },
    {
      createUpload: async () => ({ ...readyMedia(), upload: null }),
      putUpload: async () => { putCalls += 1 },
      completeUpload: async () => {
        completeCalls += 1
        return readyMedia()
      },
      createVoiceMemory: async () => ({ media: readyMedia(), memory: { id: 'memory-2' } }),
    },
    (phase) => phases.push(phase),
  )

  assert.equal(result.memoryId, 'memory-2')
  assert.equal(putCalls, 0)
  assert.equal(completeCalls, 0)
  assert.deepEqual(phases, ['uploading', 'transcribing', 'saved'])
})

// [人工注释][S1-004] 空文件在创建服务端 MediaAsset 前失败；调用方可保留/清理 temp file，
// 本纯提交服务不偷偷删除本地文件，从而不会破坏显式重试语义。
test('empty local recording fails before create upload', async () => {
  let createCalls = 0
  const phases: VoiceSubmissionPhase[] = []

  await assert.rejects(
    submitVoiceMemory(
      {
        clientUploadId: '33333333-3333-4333-8333-333333333333',
        loadBody: async () => new ArrayBuffer(0),
      },
      {
        createUpload: async () => {
          createCalls += 1
          return pendingMedia()
        },
        putUpload: async () => undefined,
        completeUpload: async () => readyMedia(),
        createVoiceMemory: async () => ({ media: readyMedia(), memory: { id: 'unused' } }),
      },
      (phase) => phases.push(phase),
    ),
    /录音文件为空/,
  )

  assert.equal(createCalls, 0)
  assert.deepEqual(phases, ['uploading', 'failed'])
})

// [人工注释][S1-004] 上传/ASR 任一阶段失败只把 phase 置 failed；temp file 生命周期仍由页面持有，
// 因此用户可以用同一 clip/client_upload_id 重试，避免产生另一份媒体身份。
test('upload failure is retryable and submission lock prevents double click', async () => {
  const lock = new VoiceSubmissionLock()
  assert.equal(lock.tryAcquire(), true)
  assert.equal(lock.tryAcquire(), false)
  assert.equal(lock.busy, true)
  lock.release()
  assert.equal(lock.tryAcquire(), true)
  lock.release()

  const phases: VoiceSubmissionPhase[] = []
  await assert.rejects(
    submitVoiceMemory(
      {
        clientUploadId: '44444444-4444-4444-8444-444444444444',
        loadBody: async () => new Uint8Array([0x49, 0x44, 0x33]).buffer,
      },
      {
        createUpload: async () => pendingMedia(),
        putUpload: async () => { throw new Error('synthetic upload failure') },
        completeUpload: async () => readyMedia(),
        createVoiceMemory: async () => ({ media: readyMedia(), memory: { id: 'unused' } }),
      },
      (phase) => phases.push(phase),
    ),
    /synthetic upload failure/,
  )
  assert.deepEqual(phases, ['uploading', 'failed'])
})
