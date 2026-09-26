import Taro from '@tarojs/taro'
import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  ApiRequestError,
  apiErrorCode,
  getMemory,
  currentElderModeEnabled,
  isAuthenticated,
  subscribeElderMode,
  MemoryQueryResult,
  queryMemory,
  submitMemoryFeedback,
} from '../../services/api'
import { elderClassName } from '../../services/elderMode'
import {
  buildCorrectionFeedback,
  createMemoryFeedbackOperation,
  executeMemoryFeedbackOperation,
  feedbackErrorMessage,
  isDisplayableEvidence,
  isRevisionConflictCode,
  MemoryFeedbackSingleFlightGate,
  MemoryReviewEpoch,
  provenanceLabel,
  trustPresentation,
  type MemoryFeedbackOperation,
  type MemoryRead,
} from '../../services/memoryFeedback'
import './index.scss'

function sourceLabel(sourceType: string): string {
  const labels: Record<string, string> = {
    USER_TEXT: '用户文字记录',
    USER_VOICE: '用户语音记录',
    USER_PHOTO: '用户照片记录',
    GPS: 'GPS 位置证据',
    PHOTO_EXIF: '照片位置信息',
    SYSTEM_PLACE: '系统地点识别',
    AI_INFERENCE: 'AI 推测',
  }
  return labels[sourceType] || sourceType
}

function shortMemoryId(memoryId: string): string {
  return memoryId.length > 12 ? `${memoryId.slice(0, 8)}…${memoryId.slice(-4)}` : memoryId
}

function memoryPreview(memory: MemoryRead): string {
  const title = memory.title?.trim()
  const content = memory.content.trim()
  return title ? `${title}\n\n${content}` : content
}

export default function Page() {
  const [elderMode, setElderMode] = useState(currentElderModeEnabled)

  useEffect(() => subscribeElderMode(setElderMode), [])

  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<MemoryQueryResult | null>(null)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const queryBusyRef = useRef(false)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewMemory, setReviewMemory] = useState<MemoryRead | null>(null)
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const feedbackGate = useRef(new MemoryFeedbackSingleFlightGate())
  const reviewEpoch = useRef(new MemoryReviewEpoch())
  const feedbackOperationRef = useRef<MemoryFeedbackOperation | null>(null)
  const [retryAvailable, setRetryAvailable] = useState(false)
  const [correctionBase, setCorrectionBase] = useState<MemoryRead | null>(null)
  const [correctionTitle, setCorrectionTitle] = useState('')
  const [correctionContent, setCorrectionContent] = useState('')

  const clearReviewState = () => {
    reviewEpoch.current.invalidate()
    setReviewMemory(null)
    setCorrectionBase(null)
    setCorrectionTitle('')
    setCorrectionContent('')
    feedbackOperationRef.current = null
    setRetryAvailable(false)
  }

  const beginFeedback = (): boolean => {
    // This synchronous gate closes the pre-render window where button disabled state
    // has not reached the UI yet. Query and feedback mutations never start together.
    if (queryBusyRef.current) return false
    if (!feedbackGate.current.begin()) return false
    reviewEpoch.current.invalidate()
    setFeedbackBusy(true)
    return true
  }

  const endFeedback = () => {
    feedbackGate.current.end()
    setFeedbackBusy(false)
  }

  const submit = async () => {
    if (queryBusyRef.current || feedbackGate.current.isPending()) return
    if (!isAuthenticated()) {
      setStatus('请先到“我的”页面登录正式账号')
      return
    }
    if (!question.trim()) {
      setStatus('请输入你想回忆的问题')
      return
    }

    // Set the ref before the first await so a rapid second tap or a feedback action
    // cannot enter during React's state-render gap.
    queryBusyRef.current = true
    setLoading(true)
    setStatus('')
    clearReviewState()
    try {
      setResult(await queryMemory(question))
    } catch {
      setResult(null)
      setStatus('查询失败，请稍后重试')
    } finally {
      queryBusyRef.current = false
      setLoading(false)
    }
  }

  const loadCurrentMemory = async (
    memoryId: string,
    capturedReviewEpoch: number,
  ): Promise<MemoryRead | null> => {
    try {
      const memory = await getMemory(memoryId)
      if (!reviewEpoch.current.isCurrent(capturedReviewEpoch)) return null
      setReviewMemory(memory)
      return memory
    } catch (error) {
      // A new query invalidates both late success and late error from the previous
      // Memory review request. Old responses must never repopulate current trust UI.
      if (!reviewEpoch.current.isCurrent(capturedReviewEpoch)) return null
      const message = feedbackErrorMessage(apiErrorCode(error))
      setStatus(message || '记忆加载失败，请稍后重试')
      if (apiErrorCode(error) === 'MEMORY_NOT_FOUND') {
        setResult(null)
        clearReviewState()
      }
      return null
    }
  }

  const openReview = async () => {
    if (queryBusyRef.current || reviewLoading || feedbackGate.current.isPending()) return
    const memoryId = result?.memory_ids?.[0]
    if (!memoryId) return
    const capturedReviewEpoch = reviewEpoch.current.capture()
    setReviewLoading(true)
    setStatus('')
    setCorrectionBase(null)
    try {
      await loadCurrentMemory(memoryId, capturedReviewEpoch)
    } finally {
      setReviewLoading(false)
    }
  }

  const handleRevisionConflict = async (memoryId: string) => {
    feedbackOperationRef.current = null
    setRetryAvailable(false)
    setCorrectionBase(null)
    setCorrectionTitle('')
    setCorrectionContent('')
    try {
      const latest = await getMemory(memoryId)
      setReviewMemory(latest)
      setStatus('记录已发生变化，请重新查看当前内容后再次选择操作')
    } catch (error) {
      if (apiErrorCode(error) === 'MEMORY_NOT_FOUND') {
        setResult(null)
        clearReviewState()
        setStatus('这条记忆已不存在，请重新查询')
        return
      }
      setReviewMemory(null)
      setStatus('记录已发生变化，请重新查询后再操作')
    }
  }

  const handleFeedbackFailure = async (operation: MemoryFeedbackOperation, error: unknown) => {
    const code = apiErrorCode(error)
    if (isRevisionConflictCode(code)) {
      await handleRevisionConflict(operation.memoryId)
      return
    }

    const mapped = feedbackErrorMessage(code)
    if (mapped) {
      feedbackOperationRef.current = null
      setRetryAvailable(false)
      if (code === 'MEMORY_NOT_FOUND' || code === 'IDEMPOTENT_RESOURCE_GONE') {
        setResult(null)
        setReviewMemory(null)
        setCorrectionBase(null)
      }
      setStatus(mapped)
      return
    }

    // Transport failure / 5xx is ambiguous: the server may have committed before the
    // response was lost. Keep the exact operation object so retry reuses key + payload.
    if (!(error instanceof ApiRequestError) || error.statusCode >= 500) {
      feedbackOperationRef.current = operation
      setRetryAvailable(true)
      setStatus('提交结果暂未确认，可重试同一次操作')
      return
    }

    feedbackOperationRef.current = null
    setRetryAvailable(false)
    setStatus('操作未完成，请重新查看当前记忆后再试')
  }

  const handleFeedbackSuccess = (
    operation: MemoryFeedbackOperation,
    feedback: Awaited<ReturnType<typeof submitMemoryFeedback>>,
  ) => {
    feedbackOperationRef.current = null
    setRetryAvailable(false)

    if (operation.payload.action === 'CONFIRM') {
      setStatus('已记录：这条记忆正确')
      return
    }

    // CORRECT / DELETE mutate the backing Memory, so the previous query answer and
    // evidence are now stale. Invalidate any in-flight review read as part of the same
    // transition; it must not repopulate a stale/deleted Memory after success.
    setResult(null)
    clearReviewState()

    if (operation.payload.action === 'CORRECT') {
      setStatus(
        feedback.result_revision === null
          ? '已纠正，请重新查询查看最新结果'
          : `已纠正（修订版 ${feedback.result_revision}），请重新查询查看最新结果`,
      )
      return
    }
    setStatus('这条记忆已删除，请重新查询查看最新结果')
  }

  const sendFeedbackOperation = async (operation: MemoryFeedbackOperation) => {
    feedbackOperationRef.current = operation
    setRetryAvailable(false)
    try {
      const feedback = await executeMemoryFeedbackOperation(operation, submitMemoryFeedback)
      handleFeedbackSuccess(operation, feedback)
    } catch (error) {
      await handleFeedbackFailure(operation, error)
    }
  }

  const confirmMemory = async () => {
    const memoryId = reviewMemory?.id || result?.memory_ids?.[0]
    if (!memoryId || !beginFeedback()) return
    setStatus('')
    try {
      // Re-fetch at action time. The revision shown when the review card was opened is
      // not authority for a later feedback submission.
      const latest = await getMemory(memoryId)
      setReviewMemory(latest)
      if (latest.memory_type === 'OBJECT_LOCATION') {
        setStatus('这类位置记忆需要在对应的位置功能中修改')
        return
      }
      const modal = await Taro.showModal({
        title: '确认这条记忆正确？',
        content: memoryPreview(latest),
        confirmText: '确认正确',
      })
      if (!modal.confirm) return

      const operation = createMemoryFeedbackOperation(latest.id, {
        action: 'CONFIRM',
        expected_revision: latest.edit_revision,
      })
      await sendFeedbackOperation(operation)
    } catch (error) {
      const message = feedbackErrorMessage(apiErrorCode(error))
      setStatus(message || '读取最新记忆失败，请稍后重试')
    } finally {
      endFeedback()
    }
  }

  const startCorrection = async () => {
    const memoryId = reviewMemory?.id || result?.memory_ids?.[0]
    if (!memoryId || !beginFeedback()) return
    setStatus('')
    try {
      const latest = await getMemory(memoryId)
      setReviewMemory(latest)
      if (latest.memory_type === 'OBJECT_LOCATION') {
        setStatus('这类位置记忆需要在对应的位置功能中修改')
        return
      }
      setCorrectionBase(latest)
      setCorrectionTitle(latest.title || '')
      setCorrectionContent(latest.content)
      feedbackOperationRef.current = null
      setRetryAvailable(false)
    } catch (error) {
      const message = feedbackErrorMessage(apiErrorCode(error))
      setStatus(message || '读取最新记忆失败，请稍后重试')
    } finally {
      endFeedback()
    }
  }

  const submitCorrection = async () => {
    const base = correctionBase
    if (!base) return

    let draftPayload: ReturnType<typeof buildCorrectionFeedback>
    try {
      // Client-side validation errors are deliberate product copy. Network/parser
      // failures below stay generic and never expose raw backend/runtime details.
      draftPayload = buildCorrectionFeedback(base, correctionTitle, correctionContent)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '请检查需要纠正的内容')
      return
    }

    if (!beginFeedback()) return
    setStatus('')
    try {
      // Re-fetch once more immediately before submit so an old form cannot overwrite
      // a newer authoritative revision.
      const latest = await getMemory(base.id)
      setReviewMemory(latest)
      if (latest.edit_revision !== base.edit_revision) {
        setCorrectionBase(null)
        setCorrectionTitle('')
        setCorrectionContent('')
        feedbackOperationRef.current = null
        setRetryAvailable(false)
        setStatus('记录已发生变化，请重新点击“纠正这条记忆”查看最新内容')
        return
      }

      const operation = createMemoryFeedbackOperation(latest.id, {
        ...draftPayload,
        expected_revision: latest.edit_revision,
      })
      await sendFeedbackOperation(operation)
    } catch (error) {
      if (error instanceof ApiRequestError) {
        const operation = feedbackOperationRef.current
        if (operation) {
          await handleFeedbackFailure(operation, error)
        } else {
          const message = feedbackErrorMessage(apiErrorCode(error))
          setStatus(message || '纠正失败，请重新查看当前记忆后再试')
        }
      } else {
        setStatus('纠正失败，请稍后重试')
      }
    } finally {
      endFeedback()
    }
  }

  const deleteMemoryByFeedback = async () => {
    const memoryId = reviewMemory?.id || result?.memory_ids?.[0]
    if (!memoryId || !beginFeedback()) return
    setStatus('')
    try {
      const latest = await getMemory(memoryId)
      setReviewMemory(latest)
      if (latest.memory_type === 'OBJECT_LOCATION') {
        setStatus('这类位置记忆需要在对应的位置功能中修改')
        return
      }
      const modal = await Taro.showModal({
        title: '删除这条记忆？',
        content: `${memoryPreview(latest)}\n\n删除后，当前查询答案会立即清空。`,
        confirmText: '删除',
        confirmColor: '#b3261e',
      })
      if (!modal.confirm) return

      const operation = createMemoryFeedbackOperation(latest.id, {
        action: 'DELETE',
        expected_revision: latest.edit_revision,
      })
      await sendFeedbackOperation(operation)
    } catch (error) {
      const message = feedbackErrorMessage(apiErrorCode(error))
      setStatus(message || '读取最新记忆失败，请稍后重试')
    } finally {
      endFeedback()
    }
  }

  const retryLastFeedback = async () => {
    const operation = feedbackOperationRef.current
    if (!operation || !retryAvailable || !beginFeedback()) return
    setStatus('')
    try {
      // Reuse the same immutable operation object: identical key + memory + payload.
      await sendFeedbackOperation(operation)
    } finally {
      endFeedback()
    }
  }

  const trust = result ? trustPresentation(result) : null
  const visibleEvidence = result
    ? result.evidence.filter((evidence) => isDisplayableEvidence(evidence.source_type))
    : []

  return (
    <View className={elderClassName(elderMode)}>
      <View className='title'>问记忆</View>
      <View className='subtitle'>只从你的真实记忆证据里找答案。</View>
      <View className='card'>
        <Input
          className='field'
          type='text'
          placeholder='例如：我的护照在哪里？'
          value={question}
          onInput={(event) => setQuestion(event.detail.value)}
        />
        <Button
          className='primary-button'
          disabled={loading || reviewLoading || feedbackBusy}
          onClick={submit}
        >
          {loading ? '查找中…' : '从我的记忆里查找'}
        </Button>
      </View>

      {result && trust && (
        <View className='card'>
          <View className='answer-row'>
            <View className='card-title answer-title'>
              {result.can_answer
                ? result.answer || '找到相关证据，但答案暂不可显示。'
                : '我没有找到足够证据回答这个问题。'}
            </View>
            <View className={`trust-badge trust-${trust.tone}`}>{trust.label}</View>
          </View>
          <View className='muted trust-detail'>{trust.detail}</View>
          <View className='muted'>查询类型：{result.intent}</View>

          {visibleEvidence.map((evidence) => {
            const provenance = provenanceLabel(evidence.provenance)
            return (
              <View className='evidence' key={evidence.memory_source_id}>
                {/* AI_INFERENCE is deliberately filtered above and is never promoted as source evidence. */}
                <Text>{evidence.excerpt}</Text>
                <View className='muted'>来源：{sourceLabel(evidence.source_type)}</View>
                {provenance && <View className='muted'>来源链：{provenance}</View>}
                <View className='muted'>证据类型：{evidence.kind} · 时间：{evidence.occurred_at}</View>
                <View className='muted'>可信度：{evidence.confidence}</View>
              </View>
            )
          })}

          {result.memory_ids.length > 0 && (
            <Button
              className='secondary-button'
              disabled={loading || reviewLoading || feedbackBusy}
              onClick={openReview}
            >
              {reviewLoading ? '正在读取最新记忆…' : '查看并评价最相关记忆'}
            </Button>
          )}
        </View>
      )}

      {reviewMemory && (
        <View className='card review-card'>
          <View className='review-heading'>
            <View>
              <View className='card-title'>正在评价这条记忆</View>
              <View className='muted'>记忆 ID：{shortMemoryId(reviewMemory.id)} · 当前版本：{reviewMemory.edit_revision}</View>
            </View>
          </View>
          {reviewMemory.title && <View className='memory-title'>{reviewMemory.title}</View>}
          <View className='memory-content'>{reviewMemory.content}</View>
          <View className='muted'>记录时间：{reviewMemory.occurred_at}</View>

          {reviewMemory.memory_type === 'OBJECT_LOCATION' ? (
            <View className='review-note'>这类结构化位置记忆暂不通过通用反馈修改，请在对应的位置功能中处理。</View>
          ) : (
            <View className='feedback-actions'>
              <Button className='secondary-button compact-button' disabled={feedbackBusy} onClick={confirmMemory}>
                这条记忆正确
              </Button>
              <Button className='secondary-button compact-button' disabled={feedbackBusy} onClick={startCorrection}>
                纠正这条记忆
              </Button>
              <Button className='danger-button compact-button' disabled={feedbackBusy} onClick={deleteMemoryByFeedback}>
                删除这条记忆
              </Button>
            </View>
          )}
        </View>
      )}

      {correctionBase && (
        <View className='card correction-card'>
          <View className='card-title'>纠正当前版本</View>
          <View className='muted'>提交前会再次读取最新版本；如果记录已变化，不会自动覆盖。</View>
          <Input
            className='field'
            type='text'
            maxlength={240}
            placeholder='标题（可留空）'
            value={correctionTitle}
            onInput={(event) => setCorrectionTitle(event.detail.value)}
          />
          <Textarea
            className='field correction-content'
            maxlength={20000}
            value={correctionContent}
            onInput={(event) => setCorrectionContent(event.detail.value)}
          />
          <View className='correction-actions'>
            <Button
              className='secondary-button compact-button'
              disabled={feedbackBusy}
              onClick={() => {
                setCorrectionBase(null)
                setCorrectionTitle('')
                setCorrectionContent('')
              }}
            >
              取消
            </Button>
            <Button className='primary-button compact-button' disabled={feedbackBusy} onClick={submitCorrection}>
              {feedbackBusy ? '正在提交…' : '提交纠正'}
            </Button>
          </View>
        </View>
      )}

      {retryAvailable && feedbackOperationRef.current && (
        <View className='card retry-card'>
          <View className='card-title'>上次提交结果暂未确认</View>
          <View className='muted'>重试会复用同一个操作标识和完全相同的请求内容，不会新建一次反馈。</View>
          <Button className='secondary-button' disabled={feedbackBusy} onClick={retryLastFeedback}>
            {feedbackBusy ? '正在重试…' : '重试同一次操作'}
          </Button>
        </View>
      )}

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
