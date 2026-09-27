import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  listPersonInteractions,
  subscribeAuthSession,
} from '../../services/api'
import {
  formatPersonMemoryTime,
  PersonMemoryUiAuthority,
  personMemoryRelationLabel,
  type PersonInteractionRow,
} from '../../services/personMemories'
import { personDetailRoute } from '../../services/people'
import './index.scss'

type Props = { refreshKey: number }

export default function RecentPersonInteractions({ refreshKey }: Props) {
  const [rows, setRows] = useState<PersonInteractionRow[]>([])
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const authority = useRef(new PersonMemoryUiAuthority())
  const authSubscriptionReady = useRef(false)

  const identity = () => ({
    owner: currentAuthenticatedUserId(),
    sessionEpoch: currentAuthSessionEpoch(),
    personId: null,
    action: 'interactions',
  })

  const refresh = async () => {
    authority.current.invalidate()
    let snapshot
    try {
      snapshot = authority.current.capture(identity())
    } catch {
      setRows([])
      setLoading(false)
      setLoaded(true)
      setError('')
      return
    }
    setLoading(true)
    setLoaded(false)
    setError('')
    try {
      const next = await listPersonInteractions(20)
      if (!authority.current.isCurrent(snapshot, identity())) return
      setRows(next)
      setLoaded(true)
    } catch {
      if (!authority.current.isCurrent(snapshot, identity())) return
      setRows([])
      setLoaded(true)
      setError('最近互动加载失败，请重试')
    } finally {
      if (authority.current.isCurrent(snapshot, identity())) setLoading(false)
    }
  }

  useEffect(() => subscribeAuthSession((owner) => {
    if (!authSubscriptionReady.current) {
      authSubscriptionReady.current = true
      return
    }
    authority.current.invalidate()
    setRows([])
    setLoading(false)
    setLoaded(false)
    setError('')
    if (owner) void refresh()
  }), [])

  useEffect(() => {
    void refresh()
    return () => authority.current.invalidate()
  }, [refreshKey])

  return (
    <View className='card recent-interactions'>
      <View className='card-title'>最近互动</View>
      <Text className='muted'>只显示你明确标记为“见过 / 互动过”的人物记忆，由服务端按时间顺序返回。</Text>

      {loading && <View className='person-memory-status'>正在加载最近互动…</View>}
      {!loading && loaded && error && (
        <>
          <View className='error'>{error}</View>
          <Button className='secondary-button' onClick={() => void refresh()}>重试</Button>
        </>
      )}
      {!loading && loaded && !error && rows.length === 0 && (
        <View className='person-memory-status'>还没有明确标记的互动记录。</View>
      )}
      {!loading && !error && rows.map((row) => (
        <View className='interaction-row' key={row.id}>
          <View>
            <View className='interaction-name'>{row.person_display_name}</View>
            <View className='muted'>
              {formatPersonMemoryTime(row.occurred_at)} · {personMemoryRelationLabel(row.relation_kind)}
            </View>
          </View>
          <Button
            className='secondary-button compact-button'
            onClick={() => void Taro.navigateTo({ url: personDetailRoute(row.person_id) })}
          >
            查看人物
          </Button>
        </View>
      ))}
    </View>
  )
}
