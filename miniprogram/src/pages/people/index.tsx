import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Input, Text, Textarea, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  createPerson,
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  currentElderModeEnabled,
  isAuthenticated,
  listPeople,
  subscribeAuthSession,
  subscribeElderMode,
} from '../../services/api'
import { elderClassName } from '../../services/elderMode'
import {
  boundedAliasSummary,
  buildPersonCreatePayload,
  PeopleUiAuthority,
  personDetailRoute,
  personErrorMessage,
  type PersonFormDraft,
  type PersonRead,
} from '../../services/people'
import './index.scss'

type PagePhase = 'signed-out' | 'loading' | 'ready' | 'error'

const EMPTY_DRAFT: PersonFormDraft = {
  displayName: '',
  relationshipLabel: '',
  note: '',
  aliases: [],
}

export default function Page() {
  const [phase, setPhase] = useState<PagePhase>('loading')
  const [people, setPeople] = useState<PersonRead[]>([])
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [draft, setDraft] = useState<PersonFormDraft>({ ...EMPTY_DRAFT })
  const [aliasInput, setAliasInput] = useState('')
  const [creating, setCreating] = useState(false)
  const [elderMode, setElderMode] = useState(currentElderModeEnabled)
  const authority = useRef(new PeopleUiAuthority())
  const authSubscriptionReady = useRef(false)

  const isCurrent = (snapshot: ReturnType<PeopleUiAuthority['capture']>, identity: string) => (
    authority.current.isCurrent(
      snapshot,
      currentAuthenticatedUserId(),
      currentAuthSessionEpoch(),
      identity,
    )
  )

  const clearOwnerState = (nextPhase: PagePhase) => {
    setPeople([])
    setError('')
    setStatus('')
    setCreateOpen(false)
    setDraft({ ...EMPTY_DRAFT })
    setAliasInput('')
    setCreating(false)
    setPhase(nextPhase)
  }

  const loadPeople = async () => {
    authority.current.invalidate()
    const owner = currentAuthenticatedUserId()
    if (!isAuthenticated() || !owner) {
      clearOwnerState('signed-out')
      return
    }

    const identity = 'people:list'
    const snapshot = authority.current.capture(owner, currentAuthSessionEpoch(), identity)
    setPeople([])
    setError('')
    setStatus('')
    setPhase('loading')

    try {
      const rows = await listPeople(100)
      if (!isCurrent(snapshot, identity)) return
      setPeople(rows)
      setPhase('ready')
    } catch {
      if (!isCurrent(snapshot, identity)) return
      setPeople([])
      setError('人物列表加载失败，请重试')
      setPhase('error')
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

  useDidShow(() => {
    void loadPeople()
  })

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

  const submitCreate = async () => {
    let payload
    try {
      payload = buildPersonCreatePayload(draft)
    } catch (validationError) {
      setStatus(validationError instanceof Error ? validationError.message : '请检查人物信息')
      return
    }

    authority.current.invalidate()
    const owner = currentAuthenticatedUserId()
    if (!owner) {
      clearOwnerState('signed-out')
      return
    }
    const identity = 'people:create'
    const snapshot = authority.current.capture(owner, currentAuthSessionEpoch(), identity)
    setCreating(true)
    setStatus('')

    try {
      const created = await createPerson(payload)
      if (!isCurrent(snapshot, identity)) return
      setDraft({ ...EMPTY_DRAFT })
      setAliasInput('')
      setCreateOpen(false)
      setStatus('人物已创建')
      await Taro.navigateTo({ url: personDetailRoute(created.id) })
    } catch (createError) {
      if (!isCurrent(snapshot, identity)) return
      setStatus(personErrorMessage(createError instanceof Error ? null : null) || '创建人物失败，请重试')
    } finally {
      if (isCurrent(snapshot, identity)) setCreating(false)
    }
  }

  const openDetail = async (personId: string) => {
    await Taro.navigateTo({ url: personDetailRoute(personId) })
  }

  return (
    <View className={elderClassName(elderMode)}>
      <View className='title'>人物</View>
      <View className='subtitle'>只管理你明确创建的人物，不会从照片、联系人、家庭或 AI 自动添加。</View>

      {phase === 'signed-out' && (
        <View className='card'>
          <View className='card-title'>请先登录</View>
          <View className='muted'>登录后才能查看和管理你自己的人物。</View>
        </View>
      )}

      {phase === 'loading' && (
        <View className='card'>
          <Text className='muted'>正在加载人物…</Text>
        </View>
      )}

      {phase === 'error' && (
        <View className='card'>
          <View className='error'>{error}</View>
          <Button className='secondary-button' onClick={() => void loadPeople()}>重试</Button>
        </View>
      )}

      {phase === 'ready' && (
        <>
          <View className='people-actions'>
            <Button
              className='primary-button'
              disabled={creating}
              onClick={() => {
                setCreateOpen((open) => !open)
                setStatus('')
              }}
            >
              {createOpen ? '收起新增' : '新增人物'}
            </Button>
          </View>

          {createOpen && (
            <View className='card'>
              <View className='card-title'>新增人物</View>
              <Input
                className='field'
                type='text'
                maxlength={200}
                placeholder='姓名（必填）'
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
                placeholder='关系备注，例如：邻居（可选）'
                value={draft.relationshipLabel}
                onInput={(event) => setDraft((current) => ({
                  ...current,
                  relationshipLabel: event.detail.value,
                }))}
              />
              <Textarea
                className='field textarea'
                maxlength={5000}
                placeholder='备注（可选）'
                value={draft.note}
                onInput={(event) => setDraft((current) => ({
                  ...current,
                  note: event.detail.value,
                }))}
              />

              <View className='alias-editor'>
                <View className='muted'>别名（可选，最多 100 个）</View>
                {draft.aliases.map((alias, index) => (
                  <View className='alias-row' key={`${alias}-${index}`}>
                    <Text>{alias}</Text>
                    <Button
                      className='secondary-button compact-button'
                      disabled={creating}
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
                <Button className='secondary-button' disabled={creating} onClick={addAlias}>
                  添加别名
                </Button>
              </View>

              <Button className='primary-button' disabled={creating} onClick={() => void submitCreate()}>
                {creating ? '正在创建…' : '确认创建人物'}
              </Button>
            </View>
          )}

          {people.length === 0 ? (
            <View className='card'>
              <View className='card-title'>还没有人物</View>
              <View className='muted'>只有你主动点击“新增人物”并提交后，人物才会出现在这里。</View>
            </View>
          ) : (
            people.map((person) => {
              const aliasSummary = boundedAliasSummary(person)
              return (
                <View className='card person-card' key={person.id}>
                  <View className='card-title'>{person.display_name}</View>
                  {person.relationship_label && (
                    <View className='muted'>{person.relationship_label}</View>
                  )}
                  {aliasSummary && <View className='muted'>别名：{aliasSummary}</View>}
                  <Button
                    className='secondary-button'
                    onClick={() => void openDetail(person.id)}
                  >
                    查看人物
                  </Button>
                </View>
              )
            })
          )}
        </>
      )}

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
