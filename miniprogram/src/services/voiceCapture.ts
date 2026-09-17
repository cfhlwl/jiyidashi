import type { SignedTransfer } from './photoCapture'

export type AudioContentType = 'audio/mpeg'
export type AudioMediaStatus = 'PENDING' | 'READY'

export type AudioMediaRead = {
  id: string
  kind: 'AUDIO'
  status: AudioMediaStatus
  content_type: string
  size_bytes: number
  original_filename?: string | null
  created_at: string
  completed_at?: string | null
}

export type AudioMediaUploadResponse = AudioMediaRead & {
  upload?: SignedTransfer | null
}

export type VoiceMemoryResponse = {
  media: AudioMediaRead
  memory: {
    id: string
    content?: string
    confidence?: number
  }
}

export type VoiceSubmissionPhase =
  | 'recorded'
  | 'uploading'
  | 'verifying'
  | 'transcribing'
  | 'saved'
  | 'failed'

export type VoiceSubmissionInput = {
  clientUploadId: string
  originalFilename?: string | null
  occurredAt?: string
  title?: string
  loadBody: () => Promise<ArrayBuffer>
}

export type VoiceSubmissionDependencies = {
  createUpload: (input: {
    clientUploadId: string
    contentType: AudioContentType
    sizeBytes: number
    originalFilename?: string | null
  }) => Promise<AudioMediaUploadResponse>
  putUpload: (transfer: SignedTransfer, body: ArrayBuffer) => Promise<void>
  completeUpload: (mediaId: string) => Promise<AudioMediaRead>
  createVoiceMemory: (
    mediaId: string,
    input: { title?: string; occurredAt?: string },
  ) => Promise<VoiceMemoryResponse>
}

// [人工注释][S1-004] 语音提交与录音本身分离：录音结束后同一 temp file 在失败重试期间
// 必须复用同一个 client_upload_id，只有页面清除/卸载或提交成功后才由页面负责 unlink。
export class VoiceSubmissionLock {
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

// [人工注释][S1-004][S1-007] 小程序只上传 RecorderManager 生成的原始 MP3，并消费服务端
// READY + ASR 协议；客户端不提交 transcript/confidence/provider/confirmed 等可信字段。
export async function submitVoiceMemory(
  input: VoiceSubmissionInput,
  dependencies: VoiceSubmissionDependencies,
  onPhase: (phase: VoiceSubmissionPhase) => void = () => undefined,
): Promise<{ mediaId: string; memoryId: string }> {
  try {
    onPhase('uploading')
    const body = await input.loadBody()
    if (body.byteLength <= 0) throw new Error('录音文件为空，请重新录制')

    const created = await dependencies.createUpload({
      clientUploadId: input.clientUploadId,
      contentType: 'audio/mpeg',
      sizeBytes: body.byteLength,
      originalFilename: input.originalFilename,
    })

    let readyMedia = created
    if (created.status === 'PENDING') {
      if (!created.upload || created.upload.method.toUpperCase() !== 'PUT') {
        throw new Error('服务端没有返回可用的语音上传凭据')
      }
      await dependencies.putUpload(created.upload, body)
      onPhase('verifying')
      readyMedia = await dependencies.completeUpload(created.id)
    }

    if (readyMedia.kind !== 'AUDIO' || readyMedia.status !== 'READY') {
      throw new Error('录音尚未通过服务端验证')
    }

    onPhase('transcribing')
    const result = await dependencies.createVoiceMemory(readyMedia.id, {
      ...(input.title?.trim() ? { title: input.title.trim() } : {}),
      ...(input.occurredAt ? { occurredAt: input.occurredAt } : {}),
    })
    onPhase('saved')
    return { mediaId: readyMedia.id, memoryId: result.memory.id }
  } catch (error) {
    onPhase('failed')
    throw error
  }
}
