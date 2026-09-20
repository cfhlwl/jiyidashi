import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useState } from 'react'
import { isAuthenticated, listPlaces } from '../../services/api'
import { placeDetailRoute, placeListPresentation, type PlaceRead } from '../../services/placeDetail'
import './index.scss'

export default function Page() {
  const [places, setPlaces] = useState<PlaceRead[]>([])
  const [loadingPlaces, setLoadingPlaces] = useState(false)
  const [placesLoaded, setPlacesLoaded] = useState(false)
  const [placeError, setPlaceError] = useState('')

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
    void refreshPlaces()
  })

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
      <View className='subtitle'>你负责生活，我帮你记住。</View>

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
