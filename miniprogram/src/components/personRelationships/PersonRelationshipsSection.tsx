import Taro from '@tarojs/taro'
import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  apiErrorCode,
  createPersonRelationship,
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  deletePersonRelationship,
  listPeople,
  listPersonRelationships,
  patchPersonRelationship,
  subscribeAuthSession,
} from '../../services/api'
import {
  buildPersonRelationshipCreatePayload,
  buildPersonRelationshipPatchPayload,
  candidatePeopleForRelationship,
  PersonRelationshipUiAuthority,
  personRelationshipErrorMessage,
  rebasePersonRelationshipDraft,
  relationshipConflictFieldLabel,
  relationshipDraftFromProjection,
  relationshipKindLabel,
  type PersonRelationshipCreateDraft,
  type PersonRelationshipDraft,
  type PersonRelationshipKind,
  type PersonRelationshipProjection,
} from '../../services/personRelationships'
import type { PersonRead } from '../../services/people'
import './index.scss'

type Props = { personId: string }

const KINDS: PersonRelationshipKind[] = [
  'FAMILY',
  'FRIEND',
  'COLLEAGUE',
  'CLASSMATE',
  'OTHER',
]

const EMPTY_CREATE_DRAFT: PersonRelationshipCreateDraft = {
  relationshipKind: null,
  customLabel: '',
  note: '',
}

const EMPTY_EDIT_DRAFT: PersonRelationshipDraft = {
  relationshipKind: 'FAMILY',
  customLabel: '',
  note: '',
}

export default function PersonRelationshipsSection({ personId }: Props) {
  const [rows, setRows] = useState<PersonRelationshipProjection[]>([])
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [candidates, setCandidates] = useState<PersonRead[]>([])
  const [candidateLoading, setCandidateLoading] = useState(false)
  const [candidateError, setCandidateError] = useState('')
  const [selectedOtherId, setSelectedOtherId] = useState<string | null>(null)
  const [createDraft, setCreateDraft] = useState<PersonRelationshipCreateDraft>({ ...EMPTY_CREATE_DRAFT })
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editBase, setEditBase] = useState<PersonRelationshipProjection | null>(null)
  const [editDraft, setEditDraft] = useState<PersonRelationshipDraft>({ ...EMPTY_EDIT_DRAFT })
  const [mutationKey, setMutationKey] = useState('')
  const authority = useRef(new PersonRelationshipUiAuthority())
  const authSubscriptionReady = useRef(false)

  const identity = (
    action: string,
    relationshipId: string | null = null,
    revision: number | null = null,
    otherPersonId: string | null = null,
  ) => ({
    owner: currentAuthenticatedUserId(),
    sessionEpoch: currentAuthSessionEpoch(),
    personId,
    action,
    relationshipId,
    revision,
    otherPersonId,
  })

  const clear = () => {
    setRows([])
    setLoading(false)
    setLoaded(false)
    setError('')
    setStatus('')
    setCreateOpen(false)
    setCandidates([])
    setCandidateLoading(false)
    setCandidateError('')
    setSelectedOtherId(null)
    setCreateDraft({ ...EMPTY_CREATE_DRAFT })
    setEditingId(null)
    setEditBase(null)
    setEditDraft({ ...EMPTY_EDIT_DRAFT })
    setMutationKey('')
  }

  const refreshRelationships = async (preserveStatus = false) => {
    authority.current.invalidate()
    const action = 'list'
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
      const next = await listPersonRelationships(personId, 100)
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setRows(next)
      setLoaded(true)
    } catch (loadError) {
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setRows([])
      setLoaded(true)
      setError(personRelationshipErrorMessage(apiErrorCode(loadError)) || '人物关系加载失败，请重试')
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
    if (owner) void refreshRelationships()
  }), [personId])

  useEffect(() => {
    void refreshRelationships()
    return () => authority.current.invalidate()
  }, [personId])

  const openCreate = async () => {
    authority.current.invalidate()
    const action = 'candidates'
    let snapshot
    try {
      snapshot = authority.current.capture(identity(action))
    } catch {
      clear()
      return
    }
    setCreateOpen(true)
    setCandidates([])
    setCandidateLoading(true)
    setCandidateError('')
    setSelectedOtherId(null)
    setCreateDraft({ ...EMPTY_CREATE_DRAFT })
    setStatus('')
    setEditingId(null)
    setEditBase(null)
    try {
      const people = await listPeople(100)
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setCandidates(candidatePeopleForRelationship(people, personId))
    } catch {
      if (!authority.current.isCurrent(snapshot, identity(action))) return
      setCandidates([])
      setCandidateError('可关联人物加载失败，请重试')
    } finally {
      if (authority.current.isCurrent(snapshot, identity(action))) setCandidateLoading(false)
    }
  }

  const closeCreate = () => {
    authority.current.invalidate()
    setCreateOpen(false)
    setCandidates([])
    setCandidateError('')
    setSelectedOtherId(null)
    setCreateDraft({ ...EMPTY_CREATE_DRAFT })
  }

  const submitCreate = async () => {
    if (!selectedOtherId || mutationKey) return

    let payload
    try {
      payload = buildPersonRelationshipCreatePayload(personId, selectedOtherId, createDraft)
    } catch (validationError) {
      setStatus(validationError instanceof Error ? validationError.message : '请检查人物关系')
      return
    }

    authority.current.invalidate()
    const action = 'create'
    const selectedId = selectedOtherId
    const snapshot = authority.current.capture(identity(action, null, null, selectedId))
    setMutationKey('create:' + selectedId)
    setStatus('')

    try {
      await createPersonRelationship(payload, personId, selectedId)
      if (!authority.current.isCurrent(snapshot, identity(action, null, null, selectedId))) return
      setMutationKey('')
      setCreateOpen(false)
      setCandidates([])
      setSelectedOtherId(null)
      setCreateDraft({ ...EMPTY_CREATE_DRAFT })
      setStatus('人物关系已保存')
      await refreshRelationships(true)
    } catch (createError) {
      if (!authority.current.isCurrent(snapshot, identity(action, null, null, selectedId))) return
      setMutationKey('')
      const code = apiErrorCode(createError)
      if (code === 'PERSON_RELATIONSHIP_CONFLICT') {
        setCreateOpen(false)
        setCandidates([])
        setSelectedOtherId(null)
        setCreateDraft({ ...EMPTY_CREATE_DRAFT })
        setStatus(personRelationshipErrorMessage(code) || '人物关系已变化，请刷新后重试')
        await refreshRelationships(true)
        return
      }
      setStatus(personRelationshipErrorMessage(code) || '创建人物关系失败，请重试')
    }
  }

  const beginEdit = (row: PersonRelationshipProjection) => {
    if (mutationKey) return
    authority.current.invalidate()
    setCreateOpen(false)
    setEditingId(row.relationship_id)
    setEditBase(row)
    setEditDraft(relationshipDraftFromProjection(row))
    setStatus('')
  }

  const recoverEditConflict = async (
    base: PersonRelationshipProjection,
    userDraft: PersonRelationshipDraft,
  ) => {
    authority.current.invalidate()
    const action = 'conflict-reload'
    const snapshot = authority.current.capture(
      identity(action, base.relationship_id, base.revision, base.other_person.id),
    )
    try {
      const latestRows = await listPersonRelationships(personId, 100)
      if (!authority.current.isCurrent(
        snapshot,
        identity(action, base.relationship_id, base.revision, base.other_person.id),
      )) return

      const latest = latestRows.find(
        (row) => row.relationship_id.toLowerCase() === base.relationship_id.toLowerCase(),
      )
      if (!latest) {
        setRows(latestRows)
        setEditingId(null)
        setEditBase(null)
        setStatus('这条人物关系已经不存在，请重新操作')
        return
      }

      const rebased = rebasePersonRelationshipDraft(base, userDraft, latest)
      let nextDraft = rebased.keepUserDraft
      let message = '服务器已有新版本；未编辑字段已采用服务器最新值，请核对后重新保存'

      if (rebased.conflicts.length > 0) {
        const fields = rebased.conflicts.map(relationshipConflictFieldLabel).join('、')
        const modal = await Taro.showModal({
          title: '人物关系同时被修改',
          content: fields + '在你编辑期间也被其他客户端修改。是否保留你的修改？',
          confirmText: '保留我的修改',
          cancelText: '使用服务器值',
          confirmColor: '#446a57',
        })
        if (!authority.current.isCurrent(
          snapshot,
          identity(action, base.relationship_id, base.revision, base.other_person.id),
        )) return
        nextDraft = modal.confirm ? rebased.keepUserDraft : rebased.keepServerDraft
        message = modal.confirm
          ? '已保留你的冲突字段修改；请核对后重新保存'
          : '已采用服务器的冲突字段；你的其他编辑仍保留'
      }

      setRows(latestRows)
      setEditingId(latest.relationship_id)
      setEditBase(latest)
      setEditDraft(nextDraft)
      setStatus(message)
    } catch (loadError) {
      if (!authority.current.isCurrent(
        snapshot,
        identity(action, base.relationship_id, base.revision, base.other_person.id),
      )) return
      setStatus(personRelationshipErrorMessage(apiErrorCode(loadError)) || '最新人物关系加载失败，请重试')
    } finally {
      if (authority.current.isCurrent(
        snapshot,
        identity(action, base.relationship_id, base.revision, base.other_person.id),
      )) {
        setMutationKey('')
      }
    }
  }

  const saveEdit = async () => {
    const base = editBase
    if (!base || !editingId || mutationKey) return

    let payload
    try {
      payload = buildPersonRelationshipPatchPayload(base, editDraft)
    } catch (validationError) {
      setStatus(validationError instanceof Error ? validationError.message : '请检查人物关系')
      return
    }
    if (!payload) {
      setStatus('内容没有变化')
      return
    }

    authority.current.invalidate()
    const action = 'patch'
    const snapshot = authority.current.capture(
      identity(action, base.relationship_id, base.revision, base.other_person.id),
    )
    setMutationKey('patch:' + base.relationship_id)
    setStatus('')

    try {
      await patchPersonRelationship(
        base.relationship_id,
        payload,
        personId,
        base.other_person.id,
      )
      if (!authority.current.isCurrent(
        snapshot,
        identity(action, base.relationship_id, base.revision, base.other_person.id),
      )) return
      setMutationKey('')
      setEditingId(null)
      setEditBase(null)
      setStatus('人物关系已更新')
      await refreshRelationships(true)
    } catch (patchError) {
      if (!authority.current.isCurrent(
        snapshot,
        identity(action, base.relationship_id, base.revision, base.other_person.id),
      )) return
      if (apiErrorCode(patchError) === 'PERSON_RELATIONSHIP_REVISION_CONFLICT') {
        // Keep mutationKey set while canonical reload/rebase is in flight. All edit
        // controls remain disabled so a newer local draft cannot be overwritten.
        await recoverEditConflict(base, editDraft)
        return
      }
      setMutationKey('')
      setStatus(personRelationshipErrorMessage(apiErrorCode(patchError)) || '人物关系保存失败，请重试')
    }
  }

  const confirmDelete = async (row: PersonRelationshipProjection) => {
    if (mutationKey) return
    const confirmAction = 'delete-confirm'
    const confirmSnapshot = authority.current.capture(
      identity(confirmAction, row.relationship_id, row.revision, row.other_person.id),
    )
    const modal = await Taro.showModal({
      title: '删除人物关系？',
      content: '这只会删除两个人之间的关系记录，不会删除任何人物或记忆。',
      confirmText: '删除关系',
      confirmColor: '#b3261e',
    })
    if (
      !modal.confirm
      || !authority.current.isCurrent(
        confirmSnapshot,
        identity(confirmAction, row.relationship_id, row.revision, row.other_person.id),
      )
    ) return

    authority.current.invalidate()
    const action = 'delete'
    const snapshot = authority.current.capture(
      identity(action, row.relationship_id, row.revision, row.other_person.id),
    )
    setMutationKey('delete:' + row.relationship_id)
    setStatus('')
    try {
      await deletePersonRelationship(row.relationship_id)
      if (!authority.current.isCurrent(
        snapshot,
        identity(action, row.relationship_id, row.revision, row.other_person.id),
      )) return
      setMutationKey('')
      if (editingId === row.relationship_id) {
        setEditingId(null)
        setEditBase(null)
      }
      setStatus('人物关系已删除，人物和记忆都仍然保留')
      await refreshRelationships(true)
    } catch (deleteError) {
      if (!authority.current.isCurrent(
        snapshot,
        identity(action, row.relationship_id, row.revision, row.other_person.id),
      )) return
      setMutationKey('')
      setStatus(personRelationshipErrorMessage(apiErrorCode(deleteError)) || '删除关系失败，当前关系仍然保留')
    }
  }

  const kindButtons = <T extends PersonRelationshipDraft | PersonRelationshipCreateDraft>(
    draft: T,
    setDraft: (next: T) => void,
  ) => (
    <View className='relationship-kind-grid'>
      {KINDS.map((kind) => (
        <Button
          key={kind}
          className={draft.relationshipKind === kind ? 'primary-button compact-button' : 'secondary-button compact-button'}
          disabled={Boolean(mutationKey)}
          onClick={() => {
            authority.current.invalidate()
            setDraft({
              ...draft,
              relationshipKind: kind,
              customLabel: kind === 'OTHER' ? draft.customLabel : '',
            } as T)
          }}
        >
          {relationshipKindLabel(kind)}
        </Button>
      ))}
    </View>
  )

  return (
    <View className='card person-relationships-section'>
      <View className='card-title'>人物关系</View>
      <Text className='muted'>这里只管理你明确维护的两个人之间的直接关系，不会从记忆、别名、家庭、地点、照片或 AI 自动推断。</Text>

      {loading && <View className='relationship-status'>正在加载人物关系…</View>}
      {!loading && loaded && error && (
        <>
          <View className='error'>{error}</View>
          <Button className='secondary-button' onClick={() => void refreshRelationships()}>重试</Button>
        </>
      )}
      {!loading && loaded && !error && rows.length === 0 && (
        <View className='relationship-status'>还没有直接人物关系。</View>
      )}

      {!loading && !error && rows.map((row) => (
        <View className='relationship-row' key={row.relationship_id}>
          <View className='relationship-name'>{row.other_person.display_name}</View>
          {editingId !== row.relationship_id ? (
            <>
              <View className='relationship-kind'>{relationshipKindLabel(row.relationship_kind)}</View>
              {row.relationship_kind === 'OTHER' && row.custom_label && (
                <View className='muted'>自定义关系：{row.custom_label}</View>
              )}
              {row.note && <View className='relationship-note'>{row.note}</View>}
              <View className='relationship-actions'>
                <Button
                  className='secondary-button compact-button'
                  disabled={Boolean(mutationKey)}
                  onClick={() => beginEdit(row)}
                >
                  编辑关系
                </Button>
                <Button
                  className='danger-button compact-button'
                  disabled={Boolean(mutationKey)}
                  onClick={() => void confirmDelete(row)}
                >
                  删除关系
                </Button>
              </View>
            </>
          ) : (
            <View className='relationship-editor'>
              {kindButtons(editDraft, setEditDraft)}
              {editDraft.relationshipKind === 'OTHER' && (
                <Input
                  className='field'
                  type='text'
                  maxlength={120}
                  disabled={Boolean(mutationKey)}
                  placeholder='自定义关系（必填）'
                  value={editDraft.customLabel}
                  onInput={(event) => setEditDraft((current) => ({
                    ...current,
                    customLabel: event.detail.value,
                  }))}
                />
              )}
              <Textarea
                className='field textarea'
                maxlength={5000}
                disabled={Boolean(mutationKey)}
                placeholder='关系备注；留空会清除'
                value={editDraft.note}
                onInput={(event) => setEditDraft((current) => ({
                  ...current,
                  note: event.detail.value,
                }))}
              />
              <View className='relationship-actions'>
                <Button
                  className='secondary-button compact-button'
                  disabled={Boolean(mutationKey)}
                  onClick={() => {
                    authority.current.invalidate()
                    setEditingId(null)
                    setEditBase(null)
                    setStatus('')
                  }}
                >
                  取消编辑
                </Button>
                <Button
                  className='primary-button compact-button'
                  disabled={Boolean(mutationKey)}
                  onClick={() => void saveEdit()}
                >
                  保存关系
                </Button>
              </View>
            </View>
          )}
        </View>
      ))}

      <Button
        className='primary-button'
        disabled={Boolean(mutationKey)}
        onClick={() => {
          if (createOpen) closeCreate()
          else void openCreate()
        }}
      >
        {createOpen ? '收起添加关系' : '添加人物关系'}
      </Button>

      {createOpen && (
        <View className='relationship-create'>
          <View className='card-title'>选择另一个人物</View>
          {candidateLoading && <View className='relationship-status'>正在加载人物…</View>}
          {!candidateLoading && candidateError && (
            <>
              <View className='error'>{candidateError}</View>
              <Button className='secondary-button' onClick={() => void openCreate()}>重试</Button>
            </>
          )}
          {!candidateLoading && !candidateError && candidates.length === 0 && (
            <View className='relationship-status'>没有其他可关联人物。</View>
          )}
          {!candidateLoading && !candidateError && candidates.map((person) => (
            <View className='relationship-candidate' key={person.id}>
              <Text>{person.display_name}</Text>
              <Button
                className='secondary-button compact-button'
                disabled={Boolean(mutationKey)}
                onClick={() => {
                  authority.current.invalidate()
                  setSelectedOtherId(person.id)
                  setStatus('')
                }}
              >
                {selectedOtherId === person.id ? '已选择' : '选择'}
              </Button>
            </View>
          ))}

          {selectedOtherId && (
            <View className='relationship-create-form'>
              <View className='muted'>明确选择关系类型：</View>
              {kindButtons(createDraft, setCreateDraft)}
              {createDraft.relationshipKind === 'OTHER' && (
                <Input
                  className='field'
                  type='text'
                  maxlength={120}
                  placeholder='自定义关系（必填）'
                  value={createDraft.customLabel}
                  onInput={(event) => setCreateDraft((current) => ({
                    ...current,
                    customLabel: event.detail.value,
                  }))}
                />
              )}
              <Textarea
                className='field textarea'
                maxlength={5000}
                placeholder='关系备注（可选）'
                value={createDraft.note}
                onInput={(event) => setCreateDraft((current) => ({
                  ...current,
                  note: event.detail.value,
                }))}
              />
              <Button
                className='primary-button'
                disabled={createDraft.relationshipKind === null || Boolean(mutationKey)}
                onClick={() => void submitCreate()}
              >
                确认添加关系
              </Button>
            </View>
          )}
        </View>
      )}

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
