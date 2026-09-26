import Taro, { useDidHide, useDidShow } from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  currentAuthenticatedUserId,
  currentElderModeEnabled,
  getTodayFootprint,
  isAuthenticated,
  listPlaces,
  subscribeAuthSession,
  subscribeElderMode,
  TodayFootprintResponse,
} from '../../services/api'
import { elderClassName } from '../../services/elderMode'
import { TodayFootprintRequestEpoch, toTodayFootprintRow } from '../../services/todayFootprint'
import { placeDetailRoute, placeListPresentation, type PlaceRead } from '../../services/placeDetail'
import './index.scss'

// Today Footprint 与地点列表是两个独立的服务端权威 read model。
// 本页可以并排展示二者，但不能从 Place 列表反推“今天去过哪里”，否则会绕过账号时区与 Visit overlap 语义。
export default function Page() {
  const [footprint, setFootprint] = useState<TodayFootprintResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('')
  const [places, setPlaces] = useState<PlaceRead[]>([])
  const [loadingPlaces, setLoadingPlaces] = useState(false)
  const [placesLoaded, setPlacesLoaded] = useState(false)
  const [placeError, setPlaceError] = useState('')
  const [elderMode, setElderMode] = useState(currentElderModeEnabled)
  const footprintEpoch = useRef(new TodayFootprintRequestEpoch())
  const authOwnerRef = useRef<string | null>(currentAuthenticatedUserId())
  const authEpochRef = useRef<number | null>(null)

  useEffect(() => subscribeElderMode(setElderMode), [])

  useEffect(() => subscribeAuthSession((owner, epoch) => {
    if (authEpochRef.current === null) {
      authEpochRef.current = epoch
      authOwnerRef.current = owner
      return
    }
    if (authEpochRef.current === epoch && authOwnerRef.current === owner) return
    authEpochRef.current = epoch
    authOwnerRef.current = owner
    footprintEpoch.current.invalidate()
    setLoading(false)
    setFootprint(null)
    setStatus('')
  }), [])

  useEffect(() => () => {
    footprintEpoch.current.invalidate()
  }, [])

  const refresh = async () => {
    if (!isAuthenticated()) {
      setFootprint(null)
      setStatus('请先到“我的”页面登录正式账号')
      return
    }
    const generation = footprintEpoch.current.capture()
    const owner = authOwnerRef.current
    const authEpoch = authEpochRef.current
    setLoading(true)
    setStatus('')
    try {
      const next = await getTodayFootprint()
      if (
        !footprintEpoch.current.isCurrent(generation)
        || authOwnerRef.current !== owner
        || authEpochRef.current !== authEpoch
      ) return
      setFootprint(next)
    } catch (error) {
      if (
        !footprintEpoch.current.isCurrent(generation)
        || authOwnerRef.current !== owner
        || authEpochRef.current !== authEpoch
      ) return
      setFootprint(null)
      setStatus(error instanceof Error ? error.message : '读取今日足迹失败')
    } finally {
      if (
        footprintEpoch.current.isCurrent(generation)
        && authOwnerRef.current === owner
        && authEpochRef.current === authEpoch
      ) {
        setLoading(false)
      }
    }
  }

  const refreshPlaces = async () => {
    if (!isAuthenticated()) {
      setPlaces([])
      setPlaceError('')
      setPlacesLoaded(true)
      return
    }
    setLoadingPlaces(true)
    setPlacesLoaded(false)
    setPlaceError('')
    try {
      // 200 [] 是成功的空状态，不写入 placeError；只有请求/协议失败才允许出现“重试”。
      const result = await listPlaces(25)
      setPlaces(result)
    } catch (error) {
      setPlaces([])
      setPlaceError(error instanceof Error ? error.message : '地点加载失败')
    } finally {
      setLoadingPlaces(false)
      setPlacesLoaded(true)
    }
  }

  useDidShow(() => {
    void refresh()
    void refreshPlaces()
  })

  useDidHide(() => {
    footprintEpoch.current.invalidate()
    setLoading(false)
  })

  const rows = footprint?.visits.map(toTodayFootprintRow) || []

  const openPlace = (placeId: string) => {
    void Taro.navigateTo({ url: placeDetailRoute(placeId) })
  }

  const openSummaries = () => {
    // [人工注释][#103] Today only navigates to the product page. It never triggers AI generation.
    void Taro.navigateTo({ url: '/pages/summaries/index' })
  }

  const authenticated = isAuthenticated()
  // 展示状态集中由同一状态机决定 loading / signed-out / empty / error / ready，
  // 避免页面分支把 successful-empty 再次误当成可重试错误。
  const presentation = placeListPresentation({
    loading: loadingPlaces,
    loaded: placesLoaded,
    authenticated,
    placeCount: places.length,
    error: placeError,
  })

  return (
    <View className={elderClassName(elderMode)}>
      <View className='title'>{elderMode ? '今天去了哪里' : '今天'}</View>
      <View className='subtitle'>
        {elderMode ? '这里只显示已经形成的足迹，不会用当前位置猜测。' : '按账号时区回看今天真实形成的地点足迹。'}
      </View>

      {elderMode && (
        <View className='card elder-home-actions'>
          <View className='card-title'>常用功能</View>
          <Button className='primary-button elder-primary-action' onClick={() => Taro.switchTab({ url: '/pages/capture/index' })}>
            记一下
          </Button>
          <Button className='primary-button elder-primary-action' onClick={() => Taro.switchTab({ url: '/pages/query/index' })}>
            找东西
          </Button>
          <View className='elder-primary-action elder-status-action'>
            <View className='elder-action-title'>今天去了哪里</View>
            <Text className='muted'>下面直接显示已经形成的足迹。</Text>
          </View>
          <Button className='secondary-button elder-primary-action' onClick={() => Taro.switchTab({ url: '/pages/family/index' })}>
            家庭
          </Button>
        </View>
      )}

      <View className={elderMode ? 'card elder-footprint-card' : 'card'}>
        <View className='card-title'>{elderMode ? '今天去了哪里' : '今日足迹'}</View>
        {!elderMode && footprint && (
          <View className='muted footprint-meta'>
            {footprint.day} · {footprint.timezone} · {rows.length} 条地点记录
          </View>
        )}

        {loading && <View className='muted footprint-state'>正在整理今天的足迹…</View>}

        {!loading && footprint && rows.length === 0 && (
          <View className='footprint-state'>
            <View>今天还没有形成足迹</View>
            <Text className='muted'>{elderMode ? '这里只显示已经形成的足迹，不会用当前位置猜测。' : '这里只展示服务端已经派生出的 Visit，不用手机当前位置补记录。'}</Text>
          </View>
        )}

        {!loading && rows.map((row) => (
          <View className={elderMode ? 'footprint-row elder-footprint-row' : 'footprint-row'} key={row.id}>
            <View className='footprint-place'>{row.placeName}</View>
            <View className={elderMode ? 'elder-footprint-time' : ''}>{row.timeRange}</View>
            {!elderMode && <View className='muted'>{row.stateLabel} · {row.source}</View>}
          </View>
        ))}

        {!loading && status && <View className='error'>{status}</View>}
        {!loading && status && (
          <Button className='secondary-button' onClick={refresh}>重新加载</Button>
        )}
      </View>

      <View className='card'>
        <View className='card-title'>地点</View>
        <Text className='muted'>这里列出已保留的地点记录；进入后可查看该地点的历史到访。</Text>

        {presentation.message && (
          <View className={presentation.showRetry ? 'error' : 'place-status'}>
            {presentation.message}
          </View>
        )}

        {!loadingPlaces && places.map((place) => (
          <View className='place-row' key={place.id} onClick={() => openPlace(place.id)}>
            <View>
              <View className='place-name'>{place.name}</View>
              <View className='muted'>{place.address || place.category || '暂无地点说明'}</View>
            </View>
            <Text className='place-arrow'>›</Text>
          </View>
        ))}

        {presentation.showRetry && (
          <Button className='secondary-button' onClick={refreshPlaces}>重试</Button>
        )}
      </View>

      <View className='card'>
        <View className='card-title'>回忆总结</View>
        <Text className='muted'>按可信记录生成今天、本月或年度回忆；只有你主动点击后才会调用 AI。</Text>
        <Button className='secondary-button' onClick={openSummaries}>打开回忆总结</Button>
      </View>

      <View className='card'>
        <View className='card-title'>V1 基础能力</View>
        <Text className='muted'>APP 端负责主要自动足迹；小程序提供快速查看和记录入口。</Text>
      </View>
    </View>
  )
}
