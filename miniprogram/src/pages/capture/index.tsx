import { Button, Image, Input, Textarea, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useEffect, useRef, useState } from 'react'
import {
  completeAudioMediaUpload,
  completeImageMediaUpload,
  createCaptureSessionGuard,
  createAudioMediaUpload,
  createImageMediaUpload,
  createPhotoMemory,
  createTextMemory,
  createVoiceMemory,
  currentElderModeEnabled,
  getPrivacyStatus,
  isAuthenticated,
  subscribeElderMode,
  markObjectLocationStale,
  putSignedMediaObject,
  rememberObjectLocation,
} from '../../services/api'
import { elderClassName } from '../../services/elderMode'
import {
  createClientUploadId,
  detectImageContentType,
  ensureMicrophonePermission,
  isUserSelectionCancellation,
  PhotoSubmissionLock,
  RecorderLifecycleController,
  recoverMicrophonePermission,
  submitPhotoMemory,
  type MicrophonePermissionAdapter,
  type PhotoSubmissionPhase,
} from '../../services/photoCapture'
import {
  submitVoiceMemory,
  VoiceSubmissionLock,
  type VoiceSubmissionPhase,
} from '../../services/voiceCapture'
import './index.scss'

type SelectedPhoto = {
  tempFilePath: string
  originalFilename: string | null
  clientUploadId: string
  sizeBytes: number
}

type VoiceClip = {
  tempFilePath: string
  durationMs: number
  originalFilename: string | null
  clientUploadId: string
  occurredAt: string
}

const PHOTO_PHASE_TEXT: Record<PhotoSubmissionPhase, string> = {
  selected: '待上传',
  uploading: '上传中',
  verifying: '服务端验证中',
  saving: '正在写入记忆',
  recorded: '已记录',
  failed: '失败，可重试',
}

const VOICE_PHASE_TEXT: Record<VoiceSubmissionPhase, string> = {
  recorded: '待上传',
  uploading: '上传原始录音中',
  verifying: '服务端验证音频中',
  transcribing: '服务端转写中',
  saved: '已记录',
  failed: '失败，可重试',
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'object' && error !== null && 'errMsg' in error) {
    return String((error as { errMsg?: unknown }).errMsg || fallback)
  }
  return fallback
}

function filenameFromPath(filePath: string): string | null {
  const normalized = filePath.split('?')[0].replace(/\\/g, '/')
  const value = normalized.split('/').pop()?.trim()
  return value || null
}

// [人工注释][S1-005] MIME 预判只读取文件头 64B，不先把原图整体搬进 JS 内存；服务端 create upload 仍负责权威大小门禁。
function readFilePrefix(filePath: string, maxBytes: number): Promise<ArrayBuffer> {
  const fileSystem = Taro.getFileSystemManager()
  return new Promise((resolve, reject) => {
    fileSystem.readFile({
      filePath,
      position: 0,
      length: maxBytes,
      success: (result) => {
        if (result.data instanceof ArrayBuffer) {
          resolve(result.data)
          return
        }
        reject(new Error('无法读取图片文件头'))
      },
      fail: (error) => reject(new Error(getErrorMessage(error, '读取图片文件头失败'))),
    })
  })
}

// [人工注释][S1-005] 完整原图只允许在服务端 create upload 接受 size_bytes 后读取，用于真实 signed PUT；超限请求在此之前由服务端拒绝。
function readFileAsArrayBuffer(filePath: string): Promise<ArrayBuffer> {
  const fileSystem = Taro.getFileSystemManager()
  return new Promise((resolve, reject) => {
    fileSystem.readFile({
      filePath,
      success: (result) => {
        if (result.data instanceof ArrayBuffer) {
          resolve(result.data)
          return
        }
        reject(new Error('无法读取图片原始数据'))
      },
      fail: (error) => reject(new Error(getErrorMessage(error, '读取图片失败'))),
    })
  })
}

// [人工注释][S1-004] 60 秒 MP3 在提交时读取一次原始 ArrayBuffer；失败时临时文件仍保留，
// 重试继续使用同一个 client_upload_id。可信大小与真实 MP3 文件头仍由服务端校验。
function readVoiceFileAsArrayBuffer(filePath: string): Promise<ArrayBuffer> {
  const fileSystem = Taro.getFileSystemManager()
  return new Promise((resolve, reject) => {
    fileSystem.readFile({
      filePath,
      success: (result) => {
        if (result.data instanceof ArrayBuffer) {
          resolve(result.data)
          return
        }
        reject(new Error('无法读取录音原始数据'))
      },
      fail: (error) => reject(new Error(getErrorMessage(error, '读取录音失败'))),
    })
  })
}

// [人工注释][S1-004] 本地录音文件生命周期属于隐私边界；页面清除、换录音和卸载都只能做本地 unlink，
// 真实语音提交成功后也必须立即清除本地临时副本；上传/ASR 失败则保留供用户显式重试。
function deleteTempFile(filePath?: string | null): void {
  if (!filePath) return
  try {
    Taro.getFileSystemManager().unlink({ filePath, fail: () => undefined })
  } catch {
    // 临时文件可能已被微信回收；这里只做 best-effort 生命周期清理。
  }
}

// [人工注释][S1-004] 麦克风权限只服务用户主动 RecorderManager；拒绝后必须由用户主动进入设置恢复，不做隐式授权兜底。
const microphonePermissionAdapter: MicrophonePermissionAdapter = {
  current: async () => {
    const setting = await Taro.getSetting()
    return setting.authSetting['scope.record']
  },
  request: async () => {
    try {
      await Taro.authorize({ scope: 'scope.record' })
      return true
    } catch {
      return false
    }
  },
  openSettings: async () => {
    try {
      const setting = await Taro.openSetting()
      return setting.authSetting['scope.record'] === true
    } catch {
      return false
    }
  },
}

// [人工注释][S1-004] 微信 RecorderManager 是全局唯一实例；底层 onStart/onStop/onError 在模块生命周期只注册一次，页面只订阅 controller。
const recorderManager = Taro.getRecorderManager()
const recorderController = new RecorderLifecycleController(
  {
    onStart: (callback) => recorderManager.onStart(callback),
    onStop: (callback) => recorderManager.onStop(callback),
    onError: (callback) => recorderManager.onError(callback),
    start: () => recorderManager.start({ duration: 60_000, format: 'mp3' }),
    stop: () => recorderManager.stop(),
  },
  (filePath) => deleteTempFile(filePath),
)

export default function Page() {
  const [elderMode, setElderMode] = useState(currentElderModeEnabled)
  const [privacyPaused, setPrivacyPaused] = useState(false)

  useEffect(() => subscribeElderMode(setElderMode), [])

  useEffect(() => {
    if (!elderMode || !isAuthenticated()) {
      setPrivacyPaused(false)
      return
    }
    let cancelled = false
    let guard: (() => void) | null = null
    try {
      guard = createCaptureSessionGuard()
    } catch {
      setPrivacyPaused(false)
      return
    }
    void getPrivacyStatus()
      .then((value) => {
        guard?.()
        if (!cancelled) setPrivacyPaused(value.recording_paused === true)
      })
      .catch(() => {
        if (!cancelled) setPrivacyPaused(false)
      })
    return () => {
      cancelled = true
    }
  }, [elderMode])

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [objectName, setObjectName] = useState('')
  const [locationText, setLocationText] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)

  const [selectedPhoto, setSelectedPhoto] = useState<SelectedPhoto | null>(null)
  const [photoTitle, setPhotoTitle] = useState('')
  const [photoContent, setPhotoContent] = useState('')
  const [photoPhase, setPhotoPhase] = useState<PhotoSubmissionPhase>('selected')
  const [photoError, setPhotoError] = useState('')
  const [photoMemoryId, setPhotoMemoryId] = useState<string | null>(null)
  const [photoSubmitting, setPhotoSubmitting] = useState(false)
  const photoSubmitLock = useRef(new PhotoSubmissionLock())

  const [voicePermission, setVoicePermission] = useState<'unknown' | 'granted' | 'denied'>('unknown')
  const [voiceRecording, setVoiceRecording] = useState(false)
  const [voiceClip, setVoiceClip] = useState<VoiceClip | null>(null)
  const [voiceTitle, setVoiceTitle] = useState('')
  const [voicePhase, setVoicePhase] = useState<VoiceSubmissionPhase>('recorded')
  const [voiceError, setVoiceError] = useState('')
  const [voiceMemoryId, setVoiceMemoryId] = useState<string | null>(null)
  const [voiceSubmitting, setVoiceSubmitting] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState('录音完成后可上传，由服务端验证原始音频并执行 ASR。')
  const voiceClipRef = useRef<VoiceClip | null>(null)
  const voiceSubmitLock = useRef(new VoiceSubmissionLock())

  useEffect(() => {
    // [人工注释][S1-004] 页面只订阅模块级 RecorderLifecycleController；卸载先取消 subscriber，
    // 若仍在录音则 controller 会 stop，并在全局 onStop 返回后直接删除新生成的 tempFilePath，禁止回调已卸载页面。
    const unsubscribeRecorder = recorderController.subscribe({
      onStart: () => {
        setVoiceRecording(true)
        setVoiceStatus('正在录音…最长 60 秒。')
      },
      onStop: (result) => {
        setVoiceRecording(false)
        const nextClip: VoiceClip = {
          tempFilePath: result.tempFilePath,
          durationMs: result.duration,
          originalFilename: filenameFromPath(result.tempFilePath) || 'voice.mp3',
          clientUploadId: createClientUploadId(),
          occurredAt: new Date().toISOString(),
        }
        voiceClipRef.current = nextClip
        setVoiceClip(nextClip)
        setVoicePhase('recorded')
        setVoiceError('')
        setVoiceMemoryId(null)
        setVoiceStatus(`录音已完成（${Math.max(1, Math.round(result.duration / 1000))} 秒），可上传并由服务端转写。`)
      },
      onError: (error) => {
        setVoiceRecording(false)
        setVoiceStatus(getErrorMessage(error, '录音失败，请重试'))
      },
    })

    return () => {
      unsubscribeRecorder()
      deleteTempFile(voiceClipRef.current?.tempFilePath)
      voiceClipRef.current = null
    }
  }, [])

  const ensureLogin = () => {
    if (isAuthenticated()) return true
    setStatus('请先到“我的”页面登录正式账号')
    return false
  }

  const saveMemory = async () => {
    if (!ensureLogin()) return
    if (!content.trim()) {
      setStatus('请先写下需要记住的内容')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      const guard = createCaptureSessionGuard()
      const memory = await createTextMemory(content, title)
      guard()
      setContent('')
      setTitle('')
      setStatus(`✓ 已经帮你记住 · ${memory.id}`)
    } catch (error) {
      setStatus(getErrorMessage(error, '保存失败'))
    } finally {
      setLoading(false)
    }
  }

  const choosePhoto = async () => {
    if (photoSubmitLock.current.busy) return
    try {
      // [人工注释][S1-005] 只有用户主动点击才调用微信统一媒体选择器，一次只取一张原图；不会后台扫描相册。
      const result = await Taro.chooseMedia({
        count: 1,
        mediaType: ['image'],
        sizeType: ['original'],
        sourceType: ['album', 'camera'],
      })
      const selectedFile = result.tempFiles[0]
      const tempFilePath = selectedFile?.tempFilePath
      if (!tempFilePath || typeof selectedFile.size !== 'number') return
      setSelectedPhoto({
        tempFilePath,
        originalFilename: filenameFromPath(tempFilePath),
        clientUploadId: createClientUploadId(),
        sizeBytes: selectedFile.size,
      })
      setPhotoPhase('selected')
      setPhotoError('')
      setPhotoMemoryId(null)
    } catch (error) {
      if (isUserSelectionCancellation(error)) {
        // [人工注释][S1-005] 用户取消选择时尚未调用 create upload，因此不会产生服务器媒体记录。
        setPhotoError('')
        return
      }
      setPhotoError(getErrorMessage(error, '选择图片失败'))
      setPhotoPhase('failed')
    }
  }

  const submitPhoto = async () => {
    if (!ensureLogin()) return
    if (!selectedPhoto) {
      setPhotoError('请先拍照或选择一张图片')
      return
    }
    if (!photoContent.trim()) {
      setPhotoError('请写下这张图片需要帮你记住的内容')
      return
    }
    // [人工注释][S1-005] 同步单飞锁在 React state 更新前生效，阻止快速双击产生并发 create upload。
    if (!photoSubmitLock.current.tryAcquire()) return
    setPhotoSubmitting(true)
    setPhotoError('')
    setStatus('')
    try {
      const guard = createCaptureSessionGuard()
      const prefix = await readFilePrefix(selectedPhoto.tempFilePath, 64)
      const contentType = detectImageContentType(prefix)
      if (!contentType) {
        throw new Error('仅支持 JPEG、PNG、WebP、HEIC、HEIF 图片')
      }

      const result = await submitPhotoMemory(
        {
          clientUploadId: selectedPhoto.clientUploadId,
          contentType,
          sizeBytes: selectedPhoto.sizeBytes,
          originalFilename: selectedPhoto.originalFilename,
          loadBody: () => readFileAsArrayBuffer(selectedPhoto.tempFilePath),
          title: photoTitle,
          content: photoContent,
        },
        {
          createUpload: async (input) => {
            guard()
            const value = await createImageMediaUpload(input)
            guard()
            return value
          },
          putUpload: async (transfer, body) => {
            guard()
            await putSignedMediaObject(transfer, body)
            guard()
          },
          completeUpload: async (mediaId) => {
            guard()
            const value = await completeImageMediaUpload(mediaId)
            guard()
            return value
          },
          createPhotoMemory: async (mediaId, input) => {
            guard()
            const value = await createPhotoMemory(mediaId, input)
            guard()
            return value
          },
        },
        (phase) => {
          guard()
          setPhotoPhase(phase)
        },
      )
      guard()
      setPhotoMemoryId(result.memoryId)
      setPhotoTitle('')
      setPhotoContent('')
    } catch (error) {
      setPhotoError(getErrorMessage(error, '图片记录失败'))
    } finally {
      photoSubmitLock.current.release()
      setPhotoSubmitting(false)
    }
  }

  const startVoiceRecording = async () => {
    if (voiceSubmitLock.current.busy) return
    try {
      const granted = await ensureMicrophonePermission(microphonePermissionAdapter)
      if (!granted) {
        setVoicePermission('denied')
        setVoiceStatus('麦克风权限未开启。可点击“打开设置”恢复；不会创建任何语音记忆。')
        return
      }
      setVoicePermission('granted')
      if (voiceClipRef.current) {
        deleteTempFile(voiceClipRef.current.tempFilePath)
        voiceClipRef.current = null
        setVoiceClip(null)
      }
      setVoiceError('')
      setVoiceMemoryId(null)
      setVoicePhase('recorded')
      if (!recorderController.start()) {
        setVoiceStatus('上一段录音仍在停止并清理，请稍后再试。')
      }
    } catch (error) {
      setVoiceStatus(getErrorMessage(error, '无法开始录音'))
    }
  }

  const stopVoiceRecording = () => {
    try {
      recorderController.stop()
    } catch (error) {
      setVoiceStatus(getErrorMessage(error, '停止录音失败'))
    }
  }

  const openMicrophoneSettings = async () => {
    const granted = await recoverMicrophonePermission(microphonePermissionAdapter)
    setVoicePermission(granted ? 'granted' : 'denied')
    setVoiceStatus(granted ? '麦克风权限已恢复，可以开始录音。' : '麦克风权限仍未开启，不会录音或提交任何语音数据。')
  }

  const submitVoice = async () => {
    if (!ensureLogin()) return
    const clip = voiceClipRef.current
    if (!clip) {
      setVoiceError('请先录一段语音')
      return
    }
    // [人工注释][S1-004] 失败重试必须保留同一 temp file + client_upload_id；同步锁阻止
    // 快速双击并发 create upload。只有完整 Memory/Evidence 成功后才删除本地临时文件。
    if (!voiceSubmitLock.current.tryAcquire()) return
    setVoiceSubmitting(true)
    setVoiceError('')
    setStatus('')
    try {
      const guard = createCaptureSessionGuard()
      const result = await submitVoiceMemory(
        {
          clientUploadId: clip.clientUploadId,
          originalFilename: clip.originalFilename,
          occurredAt: clip.occurredAt,
          title: voiceTitle,
          loadBody: () => readVoiceFileAsArrayBuffer(clip.tempFilePath),
        },
        {
          createUpload: async (input) => {
            guard()
            const value = await createAudioMediaUpload(input)
            guard()
            return value
          },
          putUpload: async (transfer, body) => {
            guard()
            await putSignedMediaObject(transfer, body)
            guard()
          },
          completeUpload: async (mediaId) => {
            guard()
            const value = await completeAudioMediaUpload(mediaId)
            guard()
            return value
          },
          createVoiceMemory: async (mediaId, input) => {
            guard()
            const value = await createVoiceMemory(mediaId, input)
            guard()
            return value
          },
        },
        (phase) => {
          guard()
          setVoicePhase(phase)
        },
      )
      guard()
      deleteTempFile(clip.tempFilePath)
      if (voiceClipRef.current === clip) voiceClipRef.current = null
      setVoiceClip(null)
      setVoiceTitle('')
      setVoiceMemoryId(result.memoryId)
      setVoiceStatus(`✓ 原始录音已验证、转写并写入可信 Evidence · ${result.memoryId}`)
    } catch (error) {
      setVoiceError(getErrorMessage(error, '语音记录失败'))
      setVoiceStatus('提交失败，本地临时录音已保留，可使用同一录音重试。')
    } finally {
      voiceSubmitLock.current.release()
      setVoiceSubmitting(false)
    }
  }

  const clearVoiceClip = () => {
    if (voiceSubmitLock.current.busy) return
    deleteTempFile(voiceClipRef.current?.tempFilePath)
    voiceClipRef.current = null
    setVoiceClip(null)
    setVoiceError('')
    setVoicePhase('recorded')
    setVoiceStatus('本地临时录音已清除；未提交的录音不会成为 Memory。')
  }

  const saveObject = async () => {
    if (!ensureLogin()) return
    if (!objectName.trim() || !locationText.trim()) {
      setStatus('请填写物品名称和位置')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      // [人工注释][S1-009] 物品位置记录直接走服务端 ObjectLocation 可信链，不在小程序本地伪造当前位置。
      await rememberObjectLocation(objectName, locationText)
      setStatus(`✓ 已记录：${objectName.trim()} 在 ${locationText.trim()}`)
    } catch (error) {
      setStatus(getErrorMessage(error, '保存失败'))
    } finally {
      setLoading(false)
    }
  }

  const staleObject = async () => {
    if (!ensureLogin()) return
    if (!objectName.trim()) {
      setStatus('请先填写需要失效的物品名称')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      // [人工注释][S1-011] “已经不在那里”必须把服务端 CURRENT 改为 STALE，
      // 后续查询才能可靠返回 NO_EVIDENCE。
      await markObjectLocationStale(objectName)
      setStatus(`✓ 已标记：${objectName.trim()} 已经不在原位置`)
      setLocationText('')
    } catch (error) {
      setStatus(getErrorMessage(error, '操作失败'))
    } finally {
      setLoading(false)
    }
  }

  const elderVoiceState = voiceRecording
    ? '正在听你说'
    : voiceMemoryId
      ? '已经记住了'
      : voiceSubmitting
        ? VOICE_PHASE_TEXT[voicePhase]
        : voiceError
          ? '这次没有保存成功'
          : voiceClip
            ? '已经录好了'
            : '准备好了，点“开始说”'

  const busy = loading || photoSubmitting || voiceSubmitting

  return (
    <View className={elderClassName(elderMode)}>
      <View className='title'>{elderMode ? '帮我记一下' : '记一下'}</View>
      <View className='subtitle'>
        {elderMode
          ? '先用语音说下来；你也可以选择打字或拍照。'
          : '主动写下、拍下或录下需要记住的内容；图片和语音都必须通过服务端 Evidence 门禁后才算真正记录。'}
      </View>

      {elderMode && privacyPaused && (
        <View className='status elder-capture-notice'>
          自动记录已暂停；你主动记下的内容仍可以保存。
        </View>
      )}

      {elderMode && (
        <View className='card elder-remember-card'>
          <View className='card-title'>帮我记一下</View>
          <View className='muted capture-note'>只有你点“开始说”后才会录音；说完后还要由你确认保存。</View>
          <View className='elder-voice-state' aria-live='polite'>{elderVoiceState}</View>
          {!voiceRecording && !voiceClip && (
            <Button
              className='primary-button elder-remember-primary'
              disabled={busy}
              aria-label='开始说'
              onClick={startVoiceRecording}
            >
              开始说
            </Button>
          )}
          {voiceRecording && (
            <Button
              className='primary-button recording-button elder-remember-primary'
              aria-label='说完了'
              onClick={stopVoiceRecording}
            >
              说完了
            </Button>
          )}
          {voicePermission === 'denied' && (
            <Button className='secondary-button' disabled={busy} onClick={openMicrophoneSettings}>
              打开设置恢复麦克风权限
            </Button>
          )}
          {voiceClip && (
            <>
              <View className={`capture-state capture-state-${voicePhase}`}>
                {VOICE_PHASE_TEXT[voicePhase]} · {Math.max(1, Math.round(voiceClip.durationMs / 1000))} 秒
              </View>
              <Button
                className='primary-button elder-remember-primary'
                disabled={busy}
                aria-label='保存这段话'
                onClick={submitVoice}
              >
                {voiceSubmitting
                  ? VOICE_PHASE_TEXT[voicePhase]
                  : voicePhase === 'failed'
                    ? '重试保存这段话'
                    : '保存这段话'}
              </Button>
              <Button className='secondary-button' disabled={voiceSubmitting} onClick={clearVoiceClip}>
                不保存，清除录音
              </Button>
            </>
          )}
          {voiceError && <View className='error'>{voiceError}</View>}
          <View className={voicePermission === 'denied' ? 'error' : 'status'}>{voiceStatus}</View>
        </View>
      )}

      <View className='card'>
        <View className='card-title'>{elderMode ? '我想打字记' : '写一句'}</View>
        <Input className='field' type='text' placeholder='标题（可选）' value={title} onInput={(e) => setTitle(e.detail.value)} />
        <Textarea className='field textarea' placeholder='例如：老张周五下午来公司取合同。' value={content} onInput={(e) => setContent(e.detail.value)} />
        <Button className='primary-button' disabled={busy} onClick={saveMemory}>帮我记住</Button>
      </View>

      <View className='card'>
        <View className='card-title'>拍张照片记住</View>
        <View className='muted capture-note'>主动拍照或从相册选择一张原图。迹忆不会后台扫描相册，也不会在本阶段识图或 OCR。</View>
        <Button className='secondary-button' disabled={busy} onClick={choosePhoto}>拍照或选择图片</Button>
        {selectedPhoto && (
          <View className='photo-preview-wrap'>
            <Image className='photo-preview' src={selectedPhoto.tempFilePath} mode='aspectFit' />
            <View className={`capture-state capture-state-${photoPhase}`}>{PHOTO_PHASE_TEXT[photoPhase]}</View>
          </View>
        )}
        {selectedPhoto && (
          <>
            <Input className='field' type='text' placeholder='图片标题（可选）' value={photoTitle} onInput={(e) => setPhotoTitle(e.detail.value)} />
            <Textarea
              className='field textarea'
              placeholder='请自己写下需要记住的内容，例如：这是出差报销需要的酒店发票。'
              value={photoContent}
              onInput={(e) => setPhotoContent(e.detail.value)}
            />
            <Button
              className='primary-button'
              disabled={busy || photoPhase === 'recorded'}
              onClick={submitPhoto}
            >
              {photoPhase === 'failed' ? '重试记录这张图片' : photoSubmitting ? PHOTO_PHASE_TEXT[photoPhase] : '上传并帮我记住'}
            </Button>
          </>
        )}
        {photoError && <View className='error'>{photoError}</View>}
        {photoMemoryId && <View className='status'>✓ 图片已通过服务端验证并记录 · {photoMemoryId}</View>}
      </View>

      {!elderMode && (
      <View className='card'>
        <View className='card-title'>录一句</View>
        <View className='muted capture-note'>用户主动录音最长 60 秒。原始 MP3 会先进入私有 Evidence；服务端验证后再执行 ASR。失败、超时、空文本或低置信结果都不会生成 Memory。</View>
        {!voiceRecording && <Button className='secondary-button' disabled={busy} onClick={startVoiceRecording}>开始录音</Button>}
        {voiceRecording && <Button className='primary-button recording-button' onClick={stopVoiceRecording}>停止录音</Button>}
        {voicePermission === 'denied' && <Button className='secondary-button' disabled={busy} onClick={openMicrophoneSettings}>打开设置恢复麦克风权限</Button>}
        {voiceClip && (
          <>
            <View className={`capture-state capture-state-${voicePhase}`}>{VOICE_PHASE_TEXT[voicePhase]} · {Math.max(1, Math.round(voiceClip.durationMs / 1000))} 秒</View>
            <Input className='field' type='text' placeholder='语音标题（可选）' value={voiceTitle} onInput={(e) => setVoiceTitle(e.detail.value)} />
            <Button className='primary-button' disabled={busy} onClick={submitVoice}>
              {voiceSubmitting ? VOICE_PHASE_TEXT[voicePhase] : voicePhase === 'failed' ? '重试这段录音' : '上传、转写并帮我记住'}
            </Button>
            <Button className='secondary-button' disabled={voiceSubmitting} onClick={clearVoiceClip}>清除本地临时录音</Button>
          </>
        )}
        {voiceError && <View className='error'>{voiceError}</View>}
        {voiceMemoryId && <View className='status'>✓ 语音已形成可信 Memory / Evidence · {voiceMemoryId}</View>}
        <View className={voicePermission === 'denied' ? 'error' : 'status'}>{voiceStatus}</View>
      </View>
      )}

      <View className='card'>
        <View className='card-title'>东西在哪</View>
        <Input className='field' type='text' placeholder='物品，例如：护照' value={objectName} onInput={(e) => setObjectName(e.detail.value)} />
        <Input className='field' type='text' placeholder='位置，例如：书房左侧柜子第二层' value={locationText} onInput={(e) => setLocationText(e.detail.value)} />
        <Button className='secondary-button' disabled={busy} onClick={saveObject}>记录当前位置</Button>
        <Button className='secondary-button' disabled={busy} onClick={staleObject}>已经不在那里</Button>
      </View>

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
