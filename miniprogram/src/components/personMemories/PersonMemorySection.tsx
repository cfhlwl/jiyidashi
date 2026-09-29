import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  apiErrorCode,
  createPersonMemoryLink,
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  deletePersonMemoryLink,
  listMemoryPickerRows,
  listPersonMemoryTimeline,
  patchPersonMemoryLink,
  subscribeAuthSession,
} from '../../services/api'
import {
  buildPersonMemoryPatchPayload,
  formatPersonMemoryTime,
  PersonMemoryUiAuthority,
  personMemoryErrorMessage,
  personMemoryPreview,
  personMemoryRelationLabel,
  personMemoryTypeLabel,
  type PersonMemoryRelationKind,
  type PersonMemoryTimelineRow,
} from '../../services/personMemories'
import type { MemoryRead } from '../../services/memoryFeedback'
import './index.scss'

type Props = { personId: string }

export default function PersonMemorySection({ personId }: Props) {
  const [timeline, setTimeline] = useState<PersonMemoryTimelineRow[]>([])
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [pickerLoading, setPickerLoading] = useState(false)
  const [pickerError, setPickerError] = useState('')
  const [pickerRows, setPickerRows] = useState<MemoryRead[]>([])
  const [selectedMemoryId, setSelectedMemoryId] = useState<string | null>(null)
  const [selectedRelation, setSelectedRelation] = useState<PersonMemoryRelationKind | null>(null)
  const [mutationKey, setMutationKey] = useState('')
  const authority = useRef(new PersonMemoryUiAuthority())
  const authSubscriptionReady = useRef(false)

  const identity = (
    action: string,
    memoryId: string | null = null,
    linkRevision: number | null = null,
  ) => ({
    owner: currentAuthenticatedUserId(),
    sessionEpoch: currentAuthSessionEpoch(),
    personId,
    action,
    memoryId,
    linkRevision,
  })

  const clear = () => {
    setTimeline([])
    setLoading(false)
    setLoaded(false)
    setError('')
    setStatus('')
    setPickerOpen(false)
    setPickerLoading(false)
    setPickerError('')
    setPickerRows([])
    setSelectedMemoryId(null)
    setSelectedRelation(null)
    setMutationKey('')
  }

  const refreshTimeline = async (preserveStatus = false) => {
    authority.current.invalidate()
    const action = 'timeline'
    let snapshot
    try {
      snapshot = authority.current.capture(identity(action))
    } catch {
      clear()
      return
    }
    setLoading(true)
    setLoaded(false)
    setError('')
    if (!preserveStatus) setStatus('')
    try {
      const rows = await listPersonMemoryTimeline(personId, 50)
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setTimeline(rows)
      setLoaded(true)
    } catch (loadError) {
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setTimeline([])
      setLoaded(true)
      setError(personMemoryErrorMessage(apiErrorCode(loadError)) || '相关记忆加载失败，请重试')
    } finally {
      if (authority.current.isCurrent(snapshot, identity(action))) setLoading(false)
    }
  }

  useEffect(() => subscribeAuthSession((owner) => {
    if (!authSubscriptionReady.current) {
      authSubscriptionReady.current = true
      return
    }
    authority.current.invalidate()
    clear()
    if (owner) void refreshTimeline()
  }), [personId])

  useEffect(() => {
    void refreshTimeline()
    return () => authority.current.invalidate()
  }, [personId])

  const openPicker = async () => {
    authority.current.invalidate()
    const action = 'picker'
    let snapshot
    try {
      snapshot = authority.current.capture(identity(action))
    } catch {
      clear()
      return
    }
    setPickerOpen(true)
    setPickerLoading(true)
    setPickerError('')
    setPickerRows([])
    setSelectedMemoryId(null)
    setSelectedRelation(null)
    setStatus('')
    try {
      const owner = currentAuthenticatedUserId()
      if (!owner) throw new Error('请先登录')
      const rows = await listMemoryPickerRows(owner, 50)
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setPickerRows(rows)
    } catch {
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setPickerRows([])
      setPickerError('可关联记忆加载失败，请重试')
    } finally {
      if (authority.current.isCurrent(snapshot, identity(action))) setPickerLoading(false)
    }
  }

  const closePicker = () => {
    authority.current.invalidate()
    setPickerOpen(false)
    setPickerRows([])
    setSelectedMemoryId(null)
    setSelectedRelation(null)
    setPickerError('')
  }

  const submitLink = async () => {
    if (!selectedMemoryId || !selectedRelation || mutationKey) return
    authority.current.invalidate()
    const action = `link:${selectedRelation}`
    const snapshot = authority.current.capture(identity(action, selectedMemoryId))
    setMutationKey(`link:${selectedMemoryId}`)
    setStatus('')
    try {
      await createPersonMemoryLink(personId, selectedMemoryId, selectedRelation)
      if (!authority.current.isCurrent(snapshot, identity(action, selectedMemoryId))) return
      setMutationKey('')
      setPickerOpen(false)
      setPickerRows([])
      setSelectedMemoryId(null)
      setSelectedRelation(null)
      setStatus('关于 TA 的记忆已保存')
      await refreshTimeline(true)
    } catch (linkError) {
      if (!authority.current.isCurrent(snapshot, identity(action, selectedMemoryId))) return
      setMutationKey('')
      const code = apiErrorCode(linkError)
      setStatus(personMemoryErrorMessage(code) || '关联失败，请重试')
      if (code === 'PERSON_MEMORY_LINK_RELATION_CONFLICT') await refreshTimeline(true)
    }
  }

  const changeRelation = async (
    row: PersonMemoryTimelineRow,
    nextRelation: PersonMemoryRelationKind,
  ) => {
    if (mutationKey) return
    const payload = buildPersonMemoryPatchPayload(row, nextRelation)
    if (!payload) return
    authority.current.invalidate()
    const action = `patch:${nextRelation}`
    const snapshot = authority.current.capture(identity(action, row.memory_id, row.revision))
    setMutationKey(`patch:${row.memory_id}`)
    setStatus('')
    try {
      await patchPersonMemoryLink(personId, row.memory_id, payload)
      if (!authority.current.isCurrent(snapshot, identity(action, row.memory_id, row.revision))) return
      setMutationKey('')
      setStatus('关联关系已更新')
      await refreshTimeline(true)
    } catch (patchError) {
      if (!authority.current.isCurrent(snapshot, identity(action, row.memory_id, row.revision))) return
      setMutationKey('')
      const code = apiErrorCode(patchError)
      setStatus(personMemoryErrorMessage(code) || '关系修改失败，请重试')
      if (code === 'PERSON_MEMORY_LINK_REVISION_CONFLICT') await refreshTimeline(true)
    }
  }

  const unlink = async (row: PersonMemoryTimelineRow) => {
    if (mutationKey) return
    const confirmAction = 'unlink-confirm'
    const confirmSnapshot = authority.current.capture(identity(
      confirmAction,
      row.memory_id,
      row.revision,
    ))
    const modal = await Taro.showModal({
      title: '取消人物关联？',
      content: '这只会取消“人物 ↔ 记忆”的关联，不会删除这条记忆。',
      confirmText: '取消关联',
      confirmColor: '#b3261e',
    })
    if (
      !modal.confirm
      || !authority.current.isCurrent(
        confirmSnapshot,
        identity(confirmAction, row.memory_id, row.revision),
      )
    ) return

    authority.current.invalidate()
    const action = 'unlink'
    const snapshot = authority.current.capture(identity(action, row.memory_id, row.revision))
    setMutationKey(`unlink:${row.memory_id}`)
    setStatus('')
    try {
      await deletePersonMemoryLink(personId, row.memory_id)
      if (!authority.current.isCurrent(snapshot, identity(action, row.memory_id, row.revision))) return
      setMutationKey('')
      setStatus('关联已取消，原记忆仍然保留')
      await refreshTimeline(true)
    } catch (unlinkError) {
      if (!authority.current.isCurrent(snapshot, identity(action, row.memory_id, row.revision))) return
      setMutationKey('')
      setStatus(personMemoryErrorMessage(apiErrorCode(unlinkError)) || '取消关联失败，当前关联仍然保留')
    }
  }

  return (
    <View className='card person-memory-section'>
      <View className='card-title'>关于 TA 的记忆</View>
      <Text className='muted'>这里只显示你主动关联的记忆，不会根据文字、地点、照片或 AI 自动关联。</Text>

      {loading && <View className='person-memory-status'>正在加载相关记忆…</View>}
      {!loading && loaded && error && (
        <>
          <View className='error'>{error}</View>
          <Button className='secondary-button' onClick={() => void refreshTimeline()}>重试</Button>
        </>
      )}
      {!loading && loaded && !error && timeline.length === 0 && (
        <View className='person-memory-status'>还没有关联记忆。</View>
      )}

      {!loading && !error && timeline.map((row) => (
        <View className='person-memory-row' key={row.id}>
          <View className='person-memory-row-head'>
            <Text className='person-memory-time'>{formatPersonMemoryTime(row.occurred_at)}</Text>
            <Text className='person-memory-relation'>{personMemoryRelationLabel(row.relation_kind)}</Text>
          </View>
          {row.memory_title && <View className='person-memory-title'>{row.memory_title}</View>}
          <View className='person-memory-preview'>{personMemoryPreview(row.memory_content)}</View>
          <View className='muted'>类型：{personMemoryTypeLabel(row.memory_type)}</View>
          <View className='person-memory-actions'>
            <Button
              className='secondary-button compact-button'
              disabled={Boolean(mutationKey)}
              onClick={() => void changeRelation(row, row.relation_kind === 'RELATED' ? 'MET' : 'RELATED')}
            >
              {row.relation_kind === 'RELATED' ? '改为见过 / 互动过' : '改为相关'}
            </Button>
            <Button
              className='danger-button compact-button'
              disabled={Boolean(mutationKey)}
              onClick={() => void unlink(row)}
            >
              取消关联
            </Button>
          </View>
        </View>
      ))}

      <Button
        className='primary-button'
        disabled={Boolean(mutationKey)}
        onClick={() => {
          if (pickerOpen) closePicker()
          else void openPicker()
        }}
      >
        {pickerOpen ? '收起记忆选择' : '关联已有记忆'}
      </Button>

      {pickerOpen && (
        <View className='person-memory-picker'>
          <View className='card-title'>选择一条已有记忆</View>
          {pickerLoading && <View className='person-memory-status'>正在加载最近记忆…</View>}
          {!pickerLoading && pickerError && (
            <>
              <View className='error'>{pickerError}</View>
              <Button className='secondary-button' onClick={() => void openPicker()}>重试</Button>
            </>
          )}
          {!pickerLoading && !pickerError && pickerRows.length === 0 && (
            <View className='person-memory-status'>当前没有可选择的记忆。</View>
          )}
          {!pickerLoading && !pickerError && pickerRows.map((memory) => (
            <View
              className={selectedMemoryId === memory.id ? 'memory-picker-row selected' : 'memory-picker-row'}
              key={memory.id}
            >
              <View className='person-memory-row-head'>
                <Text>{formatPersonMemoryTime(memory.occurred_at)}</Text>
                <Text className='muted'>{personMemoryTypeLabel(memory.memory_type)}</Text>
              </View>
              {memory.title && <View className='person-memory-title'>{memory.title}</View>}
              <View className='person-memory-preview'>{personMemoryPreview(memory.content)}</View>
              <Button
                className='secondary-button compact-button'
                onClick={() => {
                  setSelectedMemoryId(memory.id)
                  setSelectedRelation(null)
                  setStatus('')
                }}
              >
                {selectedMemoryId === memory.id ? '已选择' : '选择这条记忆'}
              </Button>
            </View>
          ))}

          {selectedMemoryId && (
            <View className='relation-picker'>
              <View className='muted'>明确选择这次关联的含义：</View>
              <View className='relation-picker-actions'>
                <Button
                  className={selectedRelation === 'RELATED' ? 'primary-button compact-button' : 'secondary-button compact-button'}
                  onClick={() => setSelectedRelation('RELATED')}
                >
                  相关
                </Button>
                <Button
                  className={selectedRelation === 'MET' ? 'primary-button compact-button' : 'secondary-button compact-button'}
                  onClick={() => setSelectedRelation('MET')}
                >
                  见过 / 互动过
                </Button>
              </View>
              <Button
                className='primary-button'
                disabled={!selectedRelation || Boolean(mutationKey)}
                onClick={() => void submitLink()}
              >
                确认关联
              </Button>
            </View>
          )}
        </View>
      )}

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
