import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  apiErrorCode,
  currentAuthenticatedUserId,
  currentAuthSessionEpoch,
  currentElderModeEnabled,
  getGraphNeighborhood,
  subscribeAuthSession,
  subscribeElderMode,
} from '../../services/api'
import { elderClassName } from '../../services/elderMode'
import {
  formatGraphTimestamp,
  graphEdgeLabel,
  graphErrorMessage,
  graphNeighborhoodRoute,
  graphNodeForEdge,
  graphNodeKindLabel,
  parseGraphRouteIdentity,
  UnifiedGraphUiAuthority,
  type GraphNeighborhood,
  type GraphNodeKind,
} from '../../services/unifiedGraph'
import './index.scss'

type Phase = 'signed-out' | 'loading' | 'ready' | 'error'

function routeIdentity(): { kind: GraphNodeKind; entityId: string } {
  const params = Taro.getCurrentInstance().router?.params
  return parseGraphRouteIdentity(
    String(params?.kind || '').trim(),
    String(params?.id || '').trim(),
  )
}

export default function Page() {
  const rawKind = String(Taro.getCurrentInstance().router?.params?.kind || '').trim()
  const rawId = String(Taro.getCurrentInstance().router?.params?.id || '').trim()
  const [phase, setPhase] = useState<Phase>('loading')
  const [neighborhood, setNeighborhood] = useState<GraphNeighborhood | null>(null)
  const [error, setError] = useState('')
  const [elderMode, setElderMode] = useState(currentElderModeEnabled)
  const authority = useRef(new UnifiedGraphUiAuthority())
  const authSubscriptionReady = useRef(false)

  const clear = (nextPhase: Phase) => {
    setNeighborhood(null)
    setError('')
    setPhase(nextPhase)
  }

  const load = async () => {
    authority.current.invalidate()

    let identity
    try {
      identity = routeIdentity()
    } catch {
      setNeighborhood(null)
      setError('一跳关系参数无效')
      setPhase('error')
      return
    }

    const owner = currentAuthenticatedUserId()
    if (!owner) {
      clear('signed-out')
      return
    }

    const snapshot = authority.current.capture(
      owner,
      currentAuthSessionEpoch(),
      identity.kind,
      identity.entityId,
    )
    setNeighborhood(null)
    setError('')
    setPhase('loading')

    try {
      const next = await getGraphNeighborhood(identity.kind, identity.entityId, 50)
      if (!authority.current.isCurrent(
        snapshot,
        currentAuthenticatedUserId(),
        currentAuthSessionEpoch(),
        routeIdentity().kind,
        routeIdentity().entityId,
      )) return
      setNeighborhood(next)
      setPhase('ready')
    } catch (loadError) {
      let current
      try {
        current = routeIdentity()
      } catch {
        return
      }
      if (!authority.current.isCurrent(
        snapshot,
        currentAuthenticatedUserId(),
        currentAuthSessionEpoch(),
        current.kind,
        current.entityId,
      )) return
      setNeighborhood(null)
      setError(graphErrorMessage(apiErrorCode(loadError)) || '关联内容加载失败，请重试')
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
    clear(owner ? 'loading' : 'signed-out')
    if (owner) void load()
  }), [rawKind, rawId])

  useEffect(() => {
    void load()
    return () => authority.current.invalidate()
  }, [rawKind, rawId])

  const openNeighbor = async (kind: GraphNodeKind, entityId: string) => {
    authority.current.invalidate()
    await Taro.redirectTo({ url: graphNeighborhoodRoute(kind, entityId) })
  }

  if (phase === 'signed-out') {
    return (
      <View className={elderClassName(elderMode)}>
        <View className='title'>相关的人和事</View>
        <View className='card'>
          <View className='card-title'>请先登录</View>
          <View className='muted'>登录后才能查看你的直接关系。</View>
        </View>
      </View>
    )
  }

  return (
    <View className={elderClassName(elderMode)}>
      <View className='title'>相关的人和事</View>
      <View className='subtitle'>查看与当前内容直接相关的人、地点和经历。</View>

      {phase === 'loading' && (
        <View className='card'>
          <Text className='muted'>正在加载直接关系…</Text>
        </View>
      )}

      {phase === 'error' && (
        <View className='card'>
          <View className='error'>{error || '关联内容加载失败'}</View>
          <Button className='secondary-button' onClick={() => void load()}>重试</Button>
        </View>
      )}

      {phase === 'ready' && neighborhood && (
        <>
          <View className='card'>
            <View className='graph-center-type'>
              {graphNodeKindLabel(neighborhood.center.kind)}
            </View>
            <View className='card-title'>{neighborhood.center.label}</View>
            {neighborhood.center.kind === 'EVENT' && neighborhood.center.occurred_at && (
              <View className='muted'>
                {formatGraphTimestamp(neighborhood.center.occurred_at)}
              </View>
            )}
          </View>

          {neighborhood.truncated && (
            <View className='graph-truncated'>这里只显示部分相关内容</View>
          )}

          <View className='card'>
            <View className='card-title'>相关内容</View>
            {neighborhood.edges.length === 0 ? (
              <View className='muted'>当前还没有可展示的相关内容。</View>
            ) : (
              neighborhood.edges.map((edge) => {
                const neighbor = graphNodeForEdge(edge, neighborhood.center)
                return (
                  <View
                    className='graph-neighbor-card'
                    key={edge.edge_kind + ':' + edge.authority_ref}
                  >
                    <View className='graph-neighbor-head'>
                      <Text className='graph-node-type'>{graphNodeKindLabel(neighbor.kind)}</Text>
                      <Text className='graph-edge-label'>{graphEdgeLabel(edge)}</Text>
                    </View>
                    <View className='graph-neighbor-label'>{neighbor.label}</View>
                    {neighbor.kind === 'EVENT' && neighbor.occurred_at && (
                      <View className='muted'>{formatGraphTimestamp(neighbor.occurred_at)}</View>
                    )}
                    {edge.edge_kind === 'OBJECT_PLACE' && edge.metadata.recorded_at && (
                      <View className='muted'>
                        记录时间：{formatGraphTimestamp(edge.metadata.recorded_at)}
                      </View>
                    )}
                    <Button
                      className='secondary-button'
                      onClick={() => void openNeighbor(neighbor.kind, neighbor.id)}
                    >
                      查看相关内容
                    </Button>
                  </View>
                )
              })
            )}
          </View>
        </>
      )}
    </View>
  )
}
