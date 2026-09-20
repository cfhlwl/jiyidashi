import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useState } from 'react'
import {
  getTodayFootprint,
  isAuthenticated,
  listPlaces,
  TodayFootprintResponse,
} from '../../services/api'
import { toTodayFootprintRow } from '../../services/todayFootprint'
import { placeDetailRoute, placeListPresentation, type PlaceRead } from '../../services/placeDetail'
import './index.scss'

export default function Page() {
  const [footprint, setFootprint] = useState<TodayFootprintResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState('')
  const [places, setPlaces] = useState<PlaceRead[]>([])
  const [loadingPlaces, setLoadingPlaces] = useState(false)
  const [placesLoaded, setPlacesLoaded] = useState(false)
  const [placeError, setPlaceError] = useState('')

  const refresh = async () => {
    if (!isAuthenticated()) {
      setFootprint(null)
      setStatus('请先到“我的”页面登录正式账号')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      setFootprint(await getTodayFootprint())
    } catch (error) {
      setFootprint(null)
      setStatus(error instanceof Error ? error.message : '读取今日足迹失败')
    } finally {
      setLoading(false)
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

  const rows = footprint?.visits.map(toTodayFootprintRow) || []

  const openPlace = (placeId: string) => {
    void Taro.navigateTo({ url: placeDetailRoute(placeId) })
  }

  const authenticated = isAuthenticated()
  const presentation = placeListPresentation({
    loading: loadingPlaces,
    loaded: placesLoaded,
    authenticated,
    placeCount: places.length,
    error: placeError,
  })

  return (
    <View className='page'>
      <View className='title'>今天</View>
      <View className='subtitle'>按账号时区回看今天真实形成的地点足迹。</View>

      <View className='card'>
        <View className='card-title'>今日足迹</View>
        {footprint && (
          <View className='muted footprint-meta'>
            {footprint.day} · {footprint.timezone} · {rows.length} 条地点记录
          </View>
        )}

        {loading && <View className='muted footprint-state'>正在整理今天的足迹…</View>}

        {!loading && footprint && rows.length === 0 && (
          <View className='footprint-state'>
            <View>今天还没有形成足迹</View>
            <Text className='muted'>这里只展示服务端已经派生出的 Visit，不用手机当前位置补记录。</Text>
          </View>
        )}

        {!loading && rows.map((row) => (
          <View className='footprint-row' key={row.id}>
            <View className='footprint-place'>{row.placeName}</View>
            <View>{row.timeRange}</View>
            <View className='muted'>{row.stateLabel} · {row.source}</View>
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
        <View className='card-title'>V1 基础能力</View>
        <Text className='muted'>APP 端负责主要自动足迹；小程序提供快速查看和记录入口。</Text>
      </View>
    </View>
  )
}
