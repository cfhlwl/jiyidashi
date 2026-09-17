import assert from 'node:assert/strict'
import test from 'node:test'
import {
  detectImageContentType,
  ensureMicrophonePermission,
  isUserSelectionCancellation,
  PhotoSubmissionLock,
  RecorderLifecycleController,
  recoverMicrophonePermission,
  submitPhotoMemory,
  type MediaRead,
  type MediaUploadResponse,
  type PhotoSubmissionDependencies,
  type PhotoSubmissionPhase,
  type RecorderError,
  type RecorderStopResult,
  type SignedTransfer,
} from '../src/services/photoCapture'

function bytes(values: number[]): ArrayBuffer {
  return Uint8Array.from(values).buffer as ArrayBuffer
}

function ascii(value: string): number[] {
  return Array.from(value).map((char) => char.charCodeAt(0))
}

const transfer: SignedTransfer = {
  method: 'PUT',
  url: 'https://storage.example.invalid/signed',
  headers: { 'Content-Type': 'image/jpeg' },
  expires_at: '2026-09-16T12:00:00Z',
}

function media(status: 'PENDING' | 'READY'): MediaRead {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    kind: 'IMAGE',
    status,
    content_type: 'image/jpeg',
    size_bytes: 3,
    original_filename: 'photo.jpg',
    created_at: '2026-09-16T11:00:00Z',
    completed_at: status === 'READY' ? '2026-09-16T11:00:01Z' : null,
  }
}

function pendingUpload(): MediaUploadResponse {
  return { ...media('PENDING'), upload: transfer }
}

function input() {
  return {
    clientUploadId: '22222222-2222-4222-8222-222222222222',
    contentType: 'image/jpeg' as const,
    sizeBytes: 3,
    originalFilename: 'photo.jpg',
    loadBody: async () => bytes([0xff, 0xd8, 0xff]),
    title: '票据',
    content: '这是出差报销需要的酒店发票',
  }
}

// [人工注释][S1-005] 客户端 MIME 识别只服务于冻结上传协议；五种允许格式均有确定性回归，
// 但最终 READY 仍必须经过服务端自己的文件头校验。
test('detectImageContentType recognizes all Stage 1 image containers', () => {
  assert.equal(detectImageContentType(bytes([0xff, 0xd8, 0xff, 0x00])), 'image/jpeg')
  assert.equal(detectImageContentType(bytes([0x89, ...ascii('PNG'), 0x0d, 0x0a, 0x1a, 0x0a])), 'image/png')
  assert.equal(detectImageContentType(bytes([...ascii('RIFF'), 0, 0, 0, 0, ...ascii('WEBP')])), 'image/webp')
  assert.equal(
    detectImageContentType(bytes([0, 0, 0, 24, ...ascii('ftyp'), ...ascii('heic'), 0, 0, 0, 0, ...ascii('heic')])),
    'image/heic',
  )
  assert.equal(
    detectImageContentType(bytes([0, 0, 0, 24, ...ascii('ftyp'), ...ascii('mif1'), 0, 0, 0, 0, ...ascii('mif1')])),
    'image/heif',
  )
  assert.equal(detectImageContentType(bytes(ascii('not-an-image'))), null)
})

test('photo submission follows create -> body read -> PUT -> complete READY -> memory', async () => {
  const phases: PhotoSubmissionPhase[] = []
  const calls: string[] = []
  const request = input()
  request.loadBody = async () => {
    calls.push('load')
    return bytes([0xff, 0xd8, 0xff])
  }
  const dependencies: PhotoSubmissionDependencies = {
    createUpload: async () => {
      calls.push('create')
      return pendingUpload()
    },
    putUpload: async () => {
      calls.push('put')
    },
    completeUpload: async () => {
      calls.push('complete')
      return media('READY')
    },
    createPhotoMemory: async () => {
      calls.push('memory')
      return { media: media('READY'), memory: { id: '44444444-4444-4444-8444-444444444444' } }
    },
  }

  const result = await submitPhotoMemory(request, dependencies, (phase) => phases.push(phase))
  assert.deepEqual(calls, ['create', 'load', 'put', 'complete', 'memory'])
  assert.deepEqual(phases, ['uploading', 'verifying', 'saving', 'recorded'])
  assert.equal(result.memoryId, '44444444-4444-4444-8444-444444444444')
})

// [人工注释][S1-005] size_bytes 先交给服务端 create upload 做权威限制检查；服务端拒绝时不得读取完整原图。
test('create upload rejection happens before full image body is loaded', async () => {
  let loadCalls = 0
  const request = input()
  request.sizeBytes = 30 * 1024 * 1024
  request.loadBody = async () => {
    loadCalls += 1
    return bytes([0xff, 0xd8, 0xff])
  }

  await assert.rejects(
    submitPhotoMemory(request, {
      createUpload: async () => {
        throw new Error('MEDIA_TOO_LARGE')
      },
      putUpload: async () => undefined,
      completeUpload: async () => media('READY'),
      createPhotoMemory: async () => ({ media: media('READY'), memory: { id: 'never' } }),
    }),
    /MEDIA_TOO_LARGE/,
  )
  assert.equal(loadCalls, 0)
})

// [人工注释][S1-005] PUT 失败必须硬停止，不能继续 complete 或先显示“已记录”。
test('PUT failure stops before complete and memory', async () => {
  let completeCalls = 0
  let memoryCalls = 0
  const phases: PhotoSubmissionPhase[] = []
  await assert.rejects(
    submitPhotoMemory(
      input(),
      {
        createUpload: async () => pendingUpload(),
        putUpload: async () => {
          throw new Error('PUT_FAILED')
        },
        completeUpload: async () => {
          completeCalls += 1
          return media('READY')
        },
        createPhotoMemory: async () => {
          memoryCalls += 1
          return { media: media('READY'), memory: { id: 'never' } }
        },
      },
      (phase) => phases.push(phase),
    ),
    /PUT_FAILED/,
  )
  assert.equal(completeCalls, 0)
  assert.equal(memoryCalls, 0)
  assert.deepEqual(phases, ['uploading', 'failed'])
})

// [人工注释][S1-005] complete 返回非 READY 时绝不能创建 USER_PHOTO Memory。
test('complete non-READY stops before photo memory creation', async () => {
  let memoryCalls = 0
  await assert.rejects(
    submitPhotoMemory(input(), {
      createUpload: async () => pendingUpload(),
      putUpload: async () => undefined,
      completeUpload: async () => media('PENDING'),
      createPhotoMemory: async () => {
        memoryCalls += 1
        return { media: media('READY'), memory: { id: 'never' } }
      },
    }),
    /尚未通过服务端验证/,
  )
  assert.equal(memoryCalls, 0)
})

// [人工注释][S1-005] 服务端 complete 的 409（例如 MEDIA_IMAGE_INVALID）由 API 适配层抛错后，
// 工作流必须停在 failed；不允许继续创建 USER_PHOTO Memory/Evidence。
test('complete rejection stops before photo memory creation', async () => {
  let memoryCalls = 0
  const phases: PhotoSubmissionPhase[] = []
  await assert.rejects(
    submitPhotoMemory(
      input(),
      {
        createUpload: async () => pendingUpload(),
        putUpload: async () => undefined,
        completeUpload: async () => {
          throw new Error('MEDIA_IMAGE_INVALID')
        },
        createPhotoMemory: async () => {
          memoryCalls += 1
          return { media: media('READY'), memory: { id: 'never' } }
        },
      },
      (phase) => phases.push(phase),
    ),
    /MEDIA_IMAGE_INVALID/,
  )
  assert.equal(memoryCalls, 0)
  assert.deepEqual(phases, ['uploading', 'verifying', 'failed'])
})

test('memory failure never reaches recorded phase', async () => {
  const phases: PhotoSubmissionPhase[] = []
  await assert.rejects(
    submitPhotoMemory(
      input(),
      {
        createUpload: async () => pendingUpload(),
        putUpload: async () => undefined,
        completeUpload: async () => media('READY'),
        createPhotoMemory: async () => {
          throw new Error('MEMORY_FAILED')
        },
      },
      (phase) => phases.push(phase),
    ),
    /MEMORY_FAILED/,
  )
  assert.deepEqual(phases, ['uploading', 'verifying', 'saving', 'failed'])
})

// [人工注释][S1-005] Memory 写入失败后的重试复用相同 client_upload_id；服务端若已 READY，
// 客户端必须跳过完整文件读取、PUT/complete，直接继续幂等的 media -> memory 创建。
test('READY retry skips duplicate body read, PUT and complete', async () => {
  let loadCalls = 0
  let putCalls = 0
  let completeCalls = 0
  let memoryCalls = 0
  const readyUpload: MediaUploadResponse = { ...media('READY'), upload: null }
  const request = input()
  request.loadBody = async () => {
    loadCalls += 1
    return bytes([0xff, 0xd8, 0xff])
  }
  await submitPhotoMemory(request, {
    createUpload: async (createRequest) => {
      assert.equal(createRequest.clientUploadId, input().clientUploadId)
      return readyUpload
    },
    putUpload: async () => {
      putCalls += 1
    },
    completeUpload: async () => {
      completeCalls += 1
      return media('READY')
    },
    createPhotoMemory: async () => {
      memoryCalls += 1
      return { media: media('READY'), memory: { id: '44444444-4444-4444-8444-444444444444' } }
    },
  })
  assert.equal(loadCalls, 0)
  assert.equal(putCalls, 0)
  assert.equal(completeCalls, 0)
  assert.equal(memoryCalls, 1)
})

// [人工注释][S1-005] 用户取消相机/相册选择时页面必须在 create upload 之前结束；
// cancel 与真实错误分开识别，防止取消动作制造服务器 MediaAsset。
test('user image selection cancellation is a no-submit path', () => {
  let createUploadCalls = 0
  const error = { errMsg: 'chooseMedia:fail cancel' }
  if (!isUserSelectionCancellation(error)) createUploadCalls += 1
  assert.equal(isUserSelectionCancellation(error), true)
  assert.equal(isUserSelectionCancellation({ errMsg: 'chooseMedia:fail permission denied' }), false)
  assert.equal(createUploadCalls, 0)
})

// [人工注释][S1-005] 快速双击只允许第一个点击取得同步锁；直到 finally release 后下一次重试才可进入。
test('photo submit lock blocks duplicate fast clicks', () => {
  const lock = new PhotoSubmissionLock()
  assert.equal(lock.tryAcquire(), true)
  assert.equal(lock.busy, true)
  assert.equal(lock.tryAcquire(), false)
  lock.release()
  assert.equal(lock.busy, false)
  assert.equal(lock.tryAcquire(), true)
})

// [人工注释][S1-004] 已拒绝麦克风权限时不重复弹 authorize；恢复只能由用户点击设置入口完成。
test('microphone denial is recoverable through explicit settings without fake recording', async () => {
  let requestCalls = 0
  let settingsCalls = 0
  const adapter = {
    current: async () => false,
    request: async () => {
      requestCalls += 1
      return true
    },
    openSettings: async () => {
      settingsCalls += 1
      return true
    },
  }
  assert.equal(await ensureMicrophonePermission(adapter), false)
  assert.equal(requestCalls, 0)
  assert.equal(await recoverMicrophonePermission(adapter), true)
  assert.equal(settingsCalls, 1)
})

function createRecorderHarness() {
  let startHandler: (() => void) | null = null
  let stopHandler: ((result: RecorderStopResult) => void) | null = null
  let errorHandler: ((error: RecorderError) => void) | null = null
  let startRegistrations = 0
  let stopRegistrations = 0
  let errorRegistrations = 0
  let startCalls = 0
  let stopCalls = 0

  const adapter = {
    onStart: (callback: () => void) => {
      startRegistrations += 1
      startHandler = callback
    },
    onStop: (callback: (result: RecorderStopResult) => void) => {
      stopRegistrations += 1
      stopHandler = callback
    },
    onError: (callback: (error: RecorderError) => void) => {
      errorRegistrations += 1
      errorHandler = callback
    },
    start: () => {
      startCalls += 1
    },
    stop: () => {
      stopCalls += 1
    },
  }

  return {
    adapter,
    emitStart: () => startHandler?.(),
    emitStop: (result: RecorderStopResult) => stopHandler?.(result),
    emitError: (error: RecorderError) => errorHandler?.(error),
    registrations: () => ({ startRegistrations, stopRegistrations, errorRegistrations }),
    calls: () => ({ startCalls, stopCalls }),
  }
}

// [人工注释][S1-004] 录音过程中页面卸载时先取消页面 subscriber，再 stop；异步 onStop 新生成的临时文件必须由 controller 删除且不得 setState。
test('recorder unmount during recording deletes late stop temp file without page callback', () => {
  const harness = createRecorderHarness()
  const deleted: string[] = []
  let pageStopCalls = 0
  const controller = new RecorderLifecycleController(harness.adapter, (filePath) => deleted.push(filePath))
  const unsubscribe = controller.subscribe({
    onStart: () => undefined,
    onStop: () => {
      pageStopCalls += 1
    },
    onError: () => undefined,
  })

  assert.equal(controller.start(), true)
  harness.emitStart()
  unsubscribe()
  assert.equal(harness.calls().stopCalls, 1)

  harness.emitStop({ tempFilePath: '/tmp/unmount-recording.mp3', duration: 1200 })
  assert.deepEqual(deleted, ['/tmp/unmount-recording.mp3'])
  assert.equal(pageStopCalls, 0)
})

// [人工注释][S1-004] 页面反复 mount/unmount 只能更换 subscriber；底层全局 RecorderManager 三类 listener 始终各注册一次，禁止累积。
test('recorder remount does not accumulate underlying listeners', () => {
  const harness = createRecorderHarness()
  const controller = new RecorderLifecycleController(harness.adapter, () => undefined)
  let firstPageStops = 0
  let secondPageStops = 0

  const unsubscribeFirst = controller.subscribe({
    onStart: () => undefined,
    onStop: () => {
      firstPageStops += 1
    },
    onError: () => undefined,
  })
  unsubscribeFirst()

  controller.subscribe({
    onStart: () => undefined,
    onStop: () => {
      secondPageStops += 1
    },
    onError: () => undefined,
  })

  assert.deepEqual(harness.registrations(), {
    startRegistrations: 1,
    stopRegistrations: 1,
    errorRegistrations: 1,
  })
  assert.equal(controller.start(), true)
  harness.emitStart()
  controller.stop()
  harness.emitStop({ tempFilePath: '/tmp/second-page.mp3', duration: 900 })
  assert.equal(firstPageStops, 0)
  assert.equal(secondPageStops, 1)
  assert.equal(harness.calls().stopCalls, 1)
})

// [人工注释][S1-PR9-FIX-001] start 时必须固定 session owner；A 在底层 onStart 到达前卸载后，
// B 即使已经 subscribe 也不能收到 A 的 late start/stop，旧临时文件必须清理，随后 B 自己的 session 仍要正常工作。
test('late recorder events stay with the original session owner across remount', () => {
  const harness = createRecorderHarness()
  const deleted: string[] = []
  const controller = new RecorderLifecycleController(harness.adapter, (filePath) => deleted.push(filePath))

  let firstStarts = 0
  let firstStops = 0
  const unsubscribeFirst = controller.subscribe({
    onStart: () => {
      firstStarts += 1
    },
    onStop: () => {
      firstStops += 1
    },
    onError: () => undefined,
  })

  assert.equal(controller.start(), true)
  unsubscribeFirst()
  assert.equal(harness.calls().stopCalls, 1)

  let secondStarts = 0
  let secondStops = 0
  controller.subscribe({
    onStart: () => {
      secondStarts += 1
    },
    onStop: () => {
      secondStops += 1
    },
    onError: () => undefined,
  })

  harness.emitStart()
  assert.equal(firstStarts, 0)
  assert.equal(secondStarts, 0)

  harness.emitStop({ tempFilePath: '/tmp/old-session.mp3', duration: 500 })
  assert.deepEqual(deleted, ['/tmp/old-session.mp3'])
  assert.equal(firstStops, 0)
  assert.equal(secondStops, 0)

  assert.equal(controller.start(), true)
  harness.emitStart()
  assert.equal(secondStarts, 1)
  controller.stop()
  harness.emitStop({ tempFilePath: '/tmp/new-session.mp3', duration: 800 })
  assert.equal(secondStops, 1)
  assert.deepEqual(deleted, ['/tmp/old-session.mp3'])
  assert.deepEqual(harness.calls(), { startCalls: 2, stopCalls: 2 })
})
