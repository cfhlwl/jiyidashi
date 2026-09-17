export type ImageContentType =
  | 'image/jpeg'
  | 'image/png'
  | 'image/webp'
  | 'image/heic'
  | 'image/heif'

export type MediaStatus = 'PENDING' | 'READY'

export type SignedTransfer = {
  method: string
  url: string
  headers: Record<string, string>
  expires_at: string
}

export type MediaRead = {
  id: string
  kind: 'IMAGE'
  status: MediaStatus
  content_type: string
  size_bytes: number
  original_filename?: string | null
  created_at: string
  completed_at?: string | null
}

export type MediaUploadResponse = MediaRead & {
  upload?: SignedTransfer | null
}

export type PhotoMemoryResponse = {
  media: MediaRead
  memory: { id: string }
}

export type PhotoSubmissionPhase =
  | 'selected'
  | 'uploading'
  | 'verifying'
  | 'saving'
  | 'recorded'
  | 'failed'

export type PhotoSubmissionInput = {
  clientUploadId: string
  contentType: ImageContentType
  sizeBytes: number
  originalFilename?: string | null
  loadBody: () => Promise<ArrayBuffer>
  title?: string
  content: string
}

export type PhotoSubmissionDependencies = {
  createUpload: (input: {
    clientUploadId: string
    contentType: ImageContentType
    sizeBytes: number
    originalFilename?: string | null
  }) => Promise<MediaUploadResponse>
  putUpload: (transfer: SignedTransfer, body: ArrayBuffer) => Promise<void>
  completeUpload: (mediaId: string) => Promise<MediaRead>
  createPhotoMemory: (mediaId: string, input: { title?: string; content: string }) => Promise<PhotoMemoryResponse>
}

// [人工注释][S1-005] client_upload_id 只承担当前用户域内的重试幂等，不是认证凭据；
// 选择同一张待提交图片后的重试必须复用同一个 UUID，禁止每次点击重试都生成新媒体身份。
export function createClientUploadId(random: () => number = Math.random): string {
  const bytes = Array.from({ length: 16 }, () => Math.floor(random() * 256) & 0xff)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = bytes.map((value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'object' && error !== null && 'errMsg' in error) {
    return String((error as { errMsg?: unknown }).errMsg || '')
  }
  return ''
}

// [人工注释][S1-005] 微信选择器的 cancel 属于用户主动取消，不是上传失败；
// 取消发生在 create upload 之前，页面必须直接返回且不能制造服务器 MediaAsset。
export function isUserSelectionCancellation(error: unknown): boolean {
  return /cancel/i.test(errorText(error))
}

// [人工注释][S1-005] React state 更新不是同步互斥锁；快速双击必须先经过同步单飞门禁，
// 第二次点击在第一次释放前不能进入 create upload。
export class PhotoSubmissionLock {
  private active = false

  get busy(): boolean {
    return this.active
  }

  tryAcquire(): boolean {
    if (this.active) return false
    this.active = true
    return true
  }

  release(): void {
    this.active = false
  }
}

function ascii(bytes: Uint8Array, start: number, end: number): string {
  return String.fromCharCode(...bytes.slice(start, end))
}

function isoBmffBrands(bytes: Uint8Array): Set<string> {
  if (bytes.length < 16 || ascii(bytes, 4, 8) !== 'ftyp') return new Set()
  const boxSize = ((bytes[0] << 24) | (bytes[1] << 16) | (bytes[2] << 8) | bytes[3]) >>> 0
  if (boxSize < 16) return new Set()
  const end = Math.min(bytes.length, boxSize)
  const brands = new Set<string>([ascii(bytes, 8, 12)])
  for (let offset = 16; offset + 3 < end; offset += 4) {
    brands.add(ascii(bytes, offset, offset + 4))
  }
  return brands
}

// [人工注释][S1-005] 小程序只做与后端一致的确定性文件类型识别，用于声明冻结协议里的 content_type；
// 这里不解析图片内容、不做 OCR/Vision，也不把客户端识别结果当作 READY 证据，最终可信门禁仍由服务端完成。
export function detectImageContentType(body: ArrayBuffer): ImageContentType | null {
  const bytes = new Uint8Array(body, 0, Math.min(body.byteLength, 64))
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg'
  if (
    bytes.length >= 8 &&
    bytes[0] === 0x89 &&
    ascii(bytes, 1, 4) === 'PNG' &&
    bytes[4] === 0x0d &&
    bytes[5] === 0x0a &&
    bytes[6] === 0x1a &&
    bytes[7] === 0x0a
  ) return 'image/png'
  if (bytes.length >= 12 && ascii(bytes, 0, 4) === 'RIFF' && ascii(bytes, 8, 12) === 'WEBP') return 'image/webp'

  const brands = isoBmffBrands(bytes)
  const heicBrands = new Set(['heic', 'heix', 'hevc', 'hevx', 'heim', 'heis', 'hevm', 'hevs'])
  for (const brand of brands) {
    if (heicBrands.has(brand)) return 'image/heic'
  }
  if (brands.has('mif1') || brands.has('msf1')) return 'image/heif'
  return null
}

// [人工注释][S1-005] 真实图片提交先让服务端 create upload 用 size_bytes 做权威大小门禁；
// 只有 create 接受且仍为 PENDING 时才读取完整原图并执行 PUT，避免明显超限文件先制造整文件内存峰值。
export async function submitPhotoMemory(
  input: PhotoSubmissionInput,
  dependencies: PhotoSubmissionDependencies,
  onPhase: (phase: PhotoSubmissionPhase) => void = () => undefined,
): Promise<{ mediaId: string; memoryId: string }> {
  const content = input.content.trim()
  if (!content) throw new Error('请填写这张图片需要记住的内容')

  try {
    onPhase('uploading')
    const created = await dependencies.createUpload({
      clientUploadId: input.clientUploadId,
      contentType: input.contentType,
      sizeBytes: input.sizeBytes,
      originalFilename: input.originalFilename,
    })

    let readyMedia = created
    if (created.status === 'PENDING') {
      if (!created.upload || created.upload.method.toUpperCase() !== 'PUT') {
        throw new Error('服务端没有返回可用的图片上传凭据')
      }
      const body = await input.loadBody()
      if (body.byteLength !== input.sizeBytes) {
        throw new Error('图片文件大小已变化，请重新选择')
      }
      await dependencies.putUpload(created.upload, body)
      onPhase('verifying')
      readyMedia = await dependencies.completeUpload(created.id)
    }

    if (readyMedia.status !== 'READY') {
      throw new Error('图片尚未通过服务端验证')
    }

    onPhase('saving')
    const result = await dependencies.createPhotoMemory(readyMedia.id, {
      ...(input.title?.trim() ? { title: input.title.trim() } : {}),
      content,
    })
    onPhase('recorded')
    return { mediaId: readyMedia.id, memoryId: result.memory.id }
  } catch (error) {
    onPhase('failed')
    throw error
  }
}

export type MicrophonePermissionAdapter = {
  current: () => Promise<boolean | undefined>
  request: () => Promise<boolean>
  openSettings: () => Promise<boolean>
}

// [人工注释][S1-004] 本轮语音只处理麦克风权限状态；false 表示曾拒绝，必须由用户主动打开设置恢复，
// 不会在权限失败时伪造录音、上传、ASR 文本或 confirmed Memory。
export async function ensureMicrophonePermission(adapter: MicrophonePermissionAdapter): Promise<boolean> {
  const current = await adapter.current()
  if (current === true) return true
  if (current === false) return false
  return adapter.request()
}

// [人工注释][S1-004] 已拒绝权限后的恢复只能由用户主动进入微信设置完成，不能静默绕过系统授权。
export function recoverMicrophonePermission(adapter: MicrophonePermissionAdapter): Promise<boolean> {
  return adapter.openSettings()
}

export type RecorderStopResult = {
  tempFilePath: string
  duration: number
}

export type RecorderError = {
  errMsg?: string
}

export type RecorderManagerAdapter = {
  onStart: (callback: () => void) => void
  onStop: (callback: (result: RecorderStopResult) => void) => void
  onError: (callback: (error: RecorderError) => void) => void
  start: () => void
  stop: () => void
}

export type RecorderSubscriber = {
  onStart: () => void
  onStop: (result: RecorderStopResult) => void
  onError: (error: RecorderError) => void
}

type RecorderSubscription = {
  subscriber: RecorderSubscriber
  active: boolean
}

type RecorderSession = {
  owner: RecorderSubscription
  started: boolean
  stopRequested: boolean
}

// [人工注释][S1-004] 微信 RecorderManager 是全局唯一实例且公开契约没有 offStart/offStop/offError；
// 底层 listener 只注册一次。每次 start 固定本次 session 的 owner subscription，后续页面 subscribe 不能接管旧 session 的 late start/stop/error。
export class RecorderLifecycleController {
  private currentSubscription: RecorderSubscription | null = null
  private session: RecorderSession | null = null

  constructor(
    private readonly adapter: RecorderManagerAdapter,
    private readonly deleteTempFile: (filePath: string) => void,
  ) {
    adapter.onStart(() => {
      const session = this.session
      if (!session) return
      session.started = true
      if (session.owner.active) session.owner.subscriber.onStart()
    })
    adapter.onStop((result) => {
      const session = this.session
      this.session = null
      if (!session || !session.owner.active) {
        this.deleteTempFile(result.tempFilePath)
        return
      }
      session.owner.subscriber.onStop(result)
    })
    adapter.onError((error) => {
      const session = this.session
      this.session = null
      if (session?.owner.active) session.owner.subscriber.onError(error)
    })
  }

  subscribe(subscriber: RecorderSubscriber): () => void {
    const subscription: RecorderSubscription = { subscriber, active: true }
    this.currentSubscription = subscription
    let disposed = false
    return () => {
      if (disposed) return
      disposed = true
      subscription.active = false
      if (this.currentSubscription === subscription) this.currentSubscription = null

      const session = this.session
      if (!session || session.owner !== subscription || session.stopRequested) return
      session.stopRequested = true
      try {
        this.adapter.stop()
      } catch {
        if (this.session === session) this.session = null
      }
    }
  }

  // [人工注释][S1-004] start 必须把当前页面 subscription 快照为 session owner；事件到达时绝不能重新读取“当前页面”，避免旧录音 late onStart 污染新页面。
  start(): boolean {
    if (this.session) return false
    const owner = this.currentSubscription
    if (!owner || !owner.active) return false

    const session: RecorderSession = { owner, started: false, stopRequested: false }
    this.session = session
    try {
      this.adapter.start()
      return true
    } catch (error) {
      if (this.session === session) this.session = null
      throw error
    }
  }

  stop(): void {
    const session = this.session
    if (!session || session.stopRequested) return
    session.stopRequested = true
    try {
      this.adapter.stop()
    } catch (error) {
      if (this.session === session) session.stopRequested = false
      throw error
    }
  }
}