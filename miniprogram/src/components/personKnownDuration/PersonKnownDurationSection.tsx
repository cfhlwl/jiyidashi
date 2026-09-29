import { useDidHide } from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  getPersonKnownDuration,
  isAuthenticated,
  subscribeAuthSession,
  type PersonKnownDuration,
} from '../../services/api'
import { AdvancedV2Authority } from '../../services/advancedV2'
import './index.scss'

type Props = {
  personId: string
}

export default function PersonKnownDurationSection({ personId }: Props) {
  const [value, setValue] = useState<PersonKnownDuration | null>(null)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('')
  const authority = useRef(new AdvancedV2Authority())
  const authReady = useRef(false)

  const isCurrent = (snapshot: ReturnType<AdvancedV2Authority['capture']>) => (
    authority.current.isCurrent(
      snapshot,
      currentAuthenticatedUserId(),
      currentAuthSessionEpoch(),
      personId,
    )
  )

  const load = async () => {
    const owner = currentAuthenticatedUserId()
    if (!isAuthenticated() || !owner || !personId) {
      authority.current.invalidate()
      setValue(null)
      setStatus('')
      setLoading(false)
      return
    }

    authority.current.invalidate()
    const snapshot = authority.current.capture(owner, currentAuthSessionEpoch(), personId)
    setLoading(true)
    setStatus('')
    try {
      const result = await getPersonKnownDuration(personId)
      if (!isCurrent(snapshot)) return
      setValue(result)
    } catch (error) {
      if (!isCurrent(snapshot)) return
      setValue(null)
      setStatus(error instanceof Error ? error.message : '认识时长加载失败')
    } finally {
      if (isCurrent(snapshot)) setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    return () => authority.current.invalidate()
  }, [personId])

  useEffect(() => subscribeAuthSession((owner) => {
    if (!authReady.current) {
      authReady.current = true
      return
    }
    authority.current.invalidate()
    setValue(null)
    setStatus('')
    setLoading(false)
    if (owner) void load()
  }), [personId])

  useDidHide(() => {
    authority.current.invalidate()
    setLoading(false)
  })

  const available = value?.status === 'KNOWN_SINCE_MET'

  return (
    <View className='card known-duration-card'>
      <View className='card-title'>认识时长</View>
      <Text className='muted'>只使用服务端可信的“见过”证据；不会根据人物创建时间、别名或关系记录猜测。</Text>

      {loading && <View className='known-duration-state'>正在读取可信记录…</View>}

      {!loading && value && available && (
        <View className='known-duration-ready'>
          <View className='known-duration-days'>至少 {value.elapsed_days} 天</View>
          <View>从 {value.at_least_since_at} 起有可信“见过”证据</View>
          <Text className='muted'>统计截至 {value.as_of}</Text>
          {value.evidence && (
            <View className='known-duration-evidence'>
              <View>证据关系：{value.evidence.relation_kind}</View>
              <Text className='muted'>
                {value.evidence.occurred_at} · {value.evidence.trust_state}
              </Text>
            </View>
          )}
        </View>
      )}

      {!loading && value && !available && (
        <View className='known-duration-state'>
          <View>
            {value.status === 'RELATED_EVIDENCE_ONLY'
              ? '有相关记录，但没有可信的“初次见面”证据，暂时无法计算。'
              : value.status === 'EVIDENCE_INCOMPLETE'
                ? '相关证据不完整，暂时不估算认识时长。'
                : '还没有足够可靠的“认识时间”记录。'}
          </View>
          {value.earliest_related_at && (
            <Text className='muted'>最早相关记录：{value.earliest_related_at}（不作为认识起点）</Text>
          )}
        </View>
      )}

      {!loading && status && <View className='error'>{status}</View>}
      {!loading && status && (
        <Button className='secondary-button' onClick={() => void load()}>重试</Button>
      )}
    </View>
  )
}
