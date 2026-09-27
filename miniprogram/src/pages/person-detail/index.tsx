import Taro from '@tarojs/taro'
import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  apiErrorCode,
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  currentElderModeEnabled,
  deletePerson,
  getPerson,
  isAuthenticated,
  patchPerson,
  subscribeAuthSession,
  subscribeElderMode,
} from '../../services/api'
import { elderClassName } from '../../services/elderMode'
import { graphNeighborhoodRoute } from '../../services/unifiedGraph'
import PersonMemorySection from '../../components/personMemories/PersonMemorySection'
import PersonRelationshipsSection from '../../components/personRelationships/PersonRelationshipsSection'
import {
  buildPersonPatchPayload,
  hasPersonPatchChanges,
  isPersonRevisionConflict,
  PeopleUiAuthority,
  personConflictFieldLabel,
  personErrorMessage,
  rebasePersonDraft,
  type PersonFormDraft,
  type PersonRead,
} from '../../services/people'
import './index.scss'

type PagePhase = 'signed-out' | 'loading' | 'ready' | 'error'

function routePersonId(): string {
  return String(Taro.getCurrentInstance().router?.params?.personId || '').trim()
}

function draftFromPerson(person: PersonRead): PersonFormDraft {
  return {
    displayName: person.display_name,
    relationshipLabel: person.relationship_label || '',
    note: person.note || '',
    aliases: [...person.aliases],
  }
}

export default function Page() {
  const personId = routePersonId()
  const [phase, setPhase] = useState<PagePhase>('loading')
  const [detail, setDetail] = useState<PersonRead | null>(null)
  const [editBase, setEditBase] = useState<PersonRead | null>(null)
  const [status, setStatus] = useState('')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<PersonFormDraft>({
    displayName: '',
    relationshipLabel: '',
    note: '',
    aliases: [],
  })
  const [aliasInput, setAliasInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [elderMode, setElderMode] = useState(currentElderModeEnabled)
  const authority = useRef(new PeopleUiAuthority())
  const authSubscriptionReady = useRef(false)

  const isCurrent = (snapshot: ReturnType<PeopleUiAuthority['capture']>) => (
    authority.current.isCurrent(
      snapshot,
      currentAuthenticatedUserId(),
      currentAuthSessionEpoch(),
      routePersonId(),
    )
  )

  const clearOwnerState = (nextPhase: PagePhase) => {
    setDetail(null)
    setEditBase(null)
    setStatus('')
    setEditing(false)
    setAliasInput('')
    setSaving(false)
    setDeleting(false)
    setPhase(nextPhase)
  }

  const loadInitial = async () => {
    authority.current.invalidate()
    const owner = currentAuthenticatedUserId()
    if (!isAuthenticated() || !owner) {
      clearOwnerState('signed-out')
      return
    }
    if (!personId) {
      setDetail(null)
      setPhase('error')
      setStatus('人物参数无效')
      return
    }

    const snapshot = authority.current.capture(owner, currentAuthSessionEpoch(), personId)
    setDetail(null)
    setStatus('')
    setEditing(false)
    setPhase('loading')

    try {
      const person = await getPerson(personId)
      if (!isCurrent(snapshot)) return
      setDetail(person)
      setEditBase(null)
      setDraft(draftFromPerson(person))
      setPhase('ready')
    } catch (loadError) {
      if (!isCurrent(snapshot)) return
      setDetail(null)
      setPhase('error')
      setStatus(personErrorMessage(apiErrorCode(loadError)) || '人物详情加载失败，请重试')
    }
  }

  const refreshAfterConflict = async (
    base: PersonRead,
    userDraft: PersonFormDraft,
  ) => {
    authority.current.invalidate()
    const owner = currentAuthenticatedUserId()
    if (!owner) {
      clearOwnerState('signed-out')
      return
    }
    const snapshot = authority.current.capture(owner, currentAuthSessionEpoch(), personId)
    try {
      const latest = await getPerson(personId)
      if (!isCurrent(snapshot)) return

      const rebased = rebasePersonDraft(base, userDraft, latest)
      let nextDraft = rebased.keepUserDraft
      let resolutionMessage = '服务器已有新版本；未编辑字段已采用服务器最新值，你的修改已保留'

      if (rebased.conflicts.length > 0) {
        const fields = rebased.conflicts.map(personConflictFieldLabel).join('、')
        const modal = await Taro.showModal({
          title: '人物信息同时被修改',
          content: `${fields}在你编辑期间也被其他客户端修改。是否保留你对这些字段的修改？`,
          confirmText: '保留我的修改',
          cancelText: '使用服务器值',
          confirmColor: '#446a57',
        })
        if (!isCurrent(snapshot)) return
        nextDraft = modal.confirm ? rebased.keepUserDraft : rebased.keepServerDraft
        resolutionMessage = modal.confirm
          ? `已保留你对${fields}的修改；请核对后重新保存`
          : `已采用服务器对${fields}的修改；你的其他编辑仍保留`
      }

      // From this point the next PATCH is based on latest.revision, never the stale edit base.
      setDetail(latest)
      setEditBase(latest)
      setDraft(nextDraft)
      setPhase('ready')
      setEditing(true)
      setStatus(resolutionMessage)
    } catch (loadError) {
      if (!isCurrent(snapshot)) return
      setStatus(personErrorMessage(apiErrorCode(loadError)) || '人物已发生变化，但最新内容加载失败，请重试')
    }
  }

  useEffect(() => subscribeElderMode(setElderMode), [])

  useEffect(() => subscribeAuthSession((owner) => {
    if (!authSubscriptionReady.current) {
      authSubscriptionReady.current = true
      return
    }
    authority.current.invalidate()
    clearOwnerState(owner ? 'loading' : 'signed-out')
  }), [])

  useEffect(() => {
    void loadInitial()
    return () => authority.current.invalidate()
  }, [personId])

  const beginEdit = () => {
    if (!detail || saving || deleting) return
    authority.current.invalidate()
    setEditBase(detail)
    setDraft(draftFromPerson(detail))
    setAliasInput('')
    setStatus('')
    setEditing(true)
  }

  const addAlias = () => {
    const alias = aliasInput.trim()
    if (!alias) {
      setStatus('别名不能为空')
      return
    }
    if (alias.length > 200) {
      setStatus('别名不能超过 200 个字符')
      return
    }
    if (draft.aliases.length >= 100) {
      setStatus('别名最多 100 个')
      return
    }
    if (draft.aliases.includes(alias)) {
      setStatus('这个别名已经在列表中')
      return
    }
    setDraft((current) => ({ ...current, aliases: [...current.aliases, alias] }))
    setAliasInput('')
    setStatus('')
  }

  const removeAlias = (index: number) => {
    setDraft((current) => ({
      ...current,
      aliases: current.aliases.filter((_alias, aliasIndex) => aliasIndex !== index),
    }))
  }

  const saveEdit = async () => {
    const base = editBase
    if (!detail || !base || saving || deleting) return

    let payload
    try {
      payload = buildPersonPatchPayload(base, draft)
    } catch (validationError) {
      setStatus(validationError instanceof Error ? validationError.message : '请检查人物信息')
      return
    }
    if (!hasPersonPatchChanges(payload)) {
      setStatus('内容没有变化')
      return
    }

    authority.current.invalidate()
    const owner = currentAuthenticatedUserId()
    if (!owner) {
      clearOwnerState('signed-out')
      return
    }
    const snapshot = authority.current.capture(owner, currentAuthSessionEpoch(), personId)
    setSaving(true)
    setStatus('')

    try {
      const updated = await patchPerson(personId, payload)
      if (!isCurrent(snapshot)) return
      setDetail(updated)
      setEditBase(null)
      setDraft(draftFromPerson(updated))
      setEditing(false)
      setStatus('人物信息已更新')
    } catch (saveError) {
      if (!isCurrent(snapshot)) return
      if (isPersonRevisionConflict(apiErrorCode(saveError))) {
        setSaving(false)
        await refreshAfterConflict(base, draft)
        return
      }
      setStatus(personErrorMessage(apiErrorCode(saveError)) || '保存失败，请重试')
    } finally {
      if (isCurrent(snapshot)) setSaving(false)
    }
  }

  const confirmDelete = async () => {
    if (!detail || saving || deleting) return
    const owner = currentAuthenticatedUserId()
    if (!owner) {
      clearOwnerState('signed-out')
      return
    }

    const modalSnapshot = authority.current.capture(
      owner,
      currentAuthSessionEpoch(),
      personId,
    )
    const modal = await Taro.showModal({
      title: '删除人物？',
      content: `确认删除“${detail.display_name}”吗？删除后无法在人物中心恢复。`,
      confirmText: '删除人物',
      confirmColor: '#b3261e',
    })
    if (!modal.confirm || !isCurrent(modalSnapshot)) return

    authority.current.invalidate()
    const snapshot = authority.current.capture(
      currentAuthenticatedUserId(),
      currentAuthSessionEpoch(),
      personId,
    )
    setDeleting(true)
    setStatus('')

    try {
      await deletePerson(personId)
      if (!isCurrent(snapshot)) return
      await Taro.navigateBack()
    } catch (deleteError) {
      if (!isCurrent(snapshot)) return
      // Keep the canonical Person visible on failure; never simulate a local delete.
      setStatus(personErrorMessage(apiErrorCode(deleteError)) || '删除失败，人物仍然保留')
    } finally {
      if (isCurrent(snapshot)) setDeleting(false)
    }
  }

  if (phase === 'signed-out') {
    return (
      <View className={elderClassName(elderMode)}>
        <View className='title'>人物</View>
        <View className='card'>
          <View className='card-title'>请先登录</View>
          <View className='muted'>登录后才能查看这个人物。</View>
        </View>
      </View>
    )
  }

  return (
    <View className={elderClassName(elderMode)}>
      <View className='title'>人物</View>

      {phase === 'loading' && (
        <View className='card'>
          <Text className='muted'>正在加载人物详情…</Text>
        </View>
      )}

      {phase === 'error' && (
        <View className='card'>
          <View className='error'>{status || '人物详情加载失败'}</View>
          <Button className='secondary-button' onClick={() => void loadInitial()}>重试</Button>
        </View>
      )}

      {phase === 'ready' && detail && !editing && (
        <>
          <View className='card'>
            <View className='card-title'>{detail.display_name}</View>
            <View className='detail-row'>
              <Text className='detail-label'>关系备注</Text>
              <Text>{detail.relationship_label || '未填写'}</Text>
            </View>
            <View className='detail-row'>
              <Text className='detail-label'>别名</Text>
              <Text>{detail.aliases.length ? detail.aliases.join('、') : '未填写'}</Text>
            </View>
            <View className='detail-row detail-note'>
              <Text className='detail-label'>备注</Text>
              <Text>{detail.note || '未填写'}</Text>
            </View>
          </View>

          <View className='detail-actions'>
            <Button className='primary-button' disabled={saving || deleting} onClick={beginEdit}>
              编辑
            </Button>
            <Button
              className='secondary-button'
              disabled={saving || deleting}
              onClick={() => void Taro.navigateTo({
                url: graphNeighborhoodRoute('PERSON', detail.id),
              })}
            >
              查看一跳关系
            </Button>
            <Button className='danger-button' disabled={saving || deleting} onClick={() => void confirmDelete()}>
              {deleting ? '正在删除…' : '删除人物'}
            </Button>
          </View>
        </>
      )}

      {phase === 'ready' && detail && editing && (
        <View className='card'>
          <View className='card-title'>编辑人物</View>
          <Input
            className='field'
            type='text'
            maxlength={200}
            placeholder='姓名'
            value={draft.displayName}
            onInput={(event) => setDraft((current) => ({
              ...current,
              displayName: event.detail.value,
            }))}
          />
          <Input
            className='field'
            type='text'
            maxlength={120}
            placeholder='关系备注；留空会清除'
            value={draft.relationshipLabel}
            onInput={(event) => setDraft((current) => ({
              ...current,
              relationshipLabel: event.detail.value,
            }))}
          />
          <Textarea
            className='field textarea'
            maxlength={5000}
            placeholder='备注；留空会清除'
            value={draft.note}
            onInput={(event) => setDraft((current) => ({
              ...current,
              note: event.detail.value,
            }))}
          />

          <View className='alias-editor'>
            <View className='muted'>别名</View>
            {draft.aliases.map((alias, index) => (
              <View className='alias-row' key={`${alias}-${index}`}>
                <Text>{alias}</Text>
                <Button
                  className='secondary-button compact-button'
                  disabled={saving}
                  onClick={() => removeAlias(index)}
                >
                  移除
                </Button>
              </View>
            ))}
            <Input
              className='field'
              type='text'
              maxlength={200}
              placeholder='输入一个别名'
              value={aliasInput}
              onInput={(event) => setAliasInput(event.detail.value)}
            />
            <Button className='secondary-button' disabled={saving} onClick={addAlias}>
              添加别名
            </Button>
          </View>

          <View className='edit-actions'>
            <Button
              className='secondary-button'
              disabled={saving}
              onClick={() => {
                authority.current.invalidate()
                setEditBase(null)
                setDraft(draftFromPerson(detail))
                setEditing(false)
                setStatus('')
              }}
            >
              取消
            </Button>
            <Button className='primary-button' disabled={saving} onClick={() => void saveEdit()}>
              {saving ? '正在保存…' : '保存修改'}
            </Button>
          </View>
        </View>
      )}

      {phase === 'ready' && detail && !editing && <PersonRelationshipsSection personId={personId} />}

      {phase === 'ready' && detail && !editing && <PersonMemorySection personId={personId} />}

      {status && phase !== 'error' && <View className='status'>{status}</View>}
    </View>
  )
}
