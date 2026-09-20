import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect, useState } from 'react'
import { getPlaceDetail } from '../../services/api'
import {
  mergePlaceDetailPages,
  type PlaceDetailPage,
  type PlaceDetailVisit,
} from '../../services/placeDetail'
import './index.scss'

function formatTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '时长仍在更新'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`
}

function VisitRow({ visit }: { visit: PlaceDetailVisit }) {
  return (
    <View className='visit-row'>
      <View className='visit-head'>
        <Text>{formatTimestamp(visit.arrived_at)}</Text>
        <Text className={visit.visit_finalized ? 'visit-finalized' : 'visit-mutable'}>
          {visit.visit_finalized ? '已稳定' : '仍在更新'}
        </Text>
      </View>
      <View className='muted'>
        {visit.left_at ? `离开：${formatTimestamp(visit.left_at)}` : '尚未记录离开时间'}
      </View>
      <View className='muted'>停留：{formatDuration(visit.duration_seconds)}</View>
    </View>
  )
}

export default function Page() {
  const placeId = String(Taro.getCurrentInstance().router?.params?.placeId || '').trim()
  const [detail, setDetail] = useState<PlaceDetailPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const [pageError, setPageError] = useState('')

  const loadInitial = async () => {
    setLoading(true)
    setError('')
    setPageError('')
    setDetail(null)
    if (!placeId) {
      setError('地点参数无效')
      setLoading(false)
      return
    }
    try {
      // [人工注释][S2-013] 详情页只消费服务端权威 Place/Visit read model；
      // unknown/cross-owner 与任何 malformed response 都不会留下可展示的半可信状态。
      setDetail(await getPlaceDetail(placeId, { limit: 20 }))
    } catch (loadError) {
      setDetail(null)
      setError(loadError instanceof Error ? loadError.message : '无法读取地点详情')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadInitial()
  }, [placeId])

  const loadMore = async () => {
    if (!detail?.next_cursor || loadingMore) return
    setLoadingMore(true)
    setPageError('')
    try {
      const next = await getPlaceDetail(placeId, { limit: 20, cursor: detail.next_cursor })
      // [人工注释][S2-013] next page 完整 parser + Place identity 都成功后再一次性替换；
      // cursor/Visit 任一协议错误都不能先 append 一半记录。
      setDetail(mergePlaceDetailPages(detail, next))
    } catch (loadError) {
      setPageError(loadError instanceof Error ? loadError.message : '部分到访记录加载失败')
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <View className='page'>
      <View className='title'>地点详情</View>

      {loading && (
        <View className='card'>
          <Text className='muted'>正在加载地点详情…</Text>
        </View>
      )}

      {!loading && error && (
        <View className='card'>
          <View className='error'>{error}</View>
          <Button className='secondary-button' onClick={loadInitial}>重试</Button>
        </View>
      )}

      {!loading && detail && (
        <>
          <View className='card'>
            <View className='card-title'>{detail.place.name}</View>
            <View className='muted'>{detail.place.address || detail.place.category || '暂无地点说明'}</View>
            <View className='place-summary'>共 {detail.place.visit_count} 次到访记录</View>
          </View>

          <View className='card'>
            <View className='card-title'>到访记录</View>
            {detail.visits.length === 0 ? (
              <View className='muted'>还没有到访记录</View>
            ) : (
              detail.visits.map((visit) => <VisitRow key={visit.id} visit={visit} />)
            )}

            {pageError && <View className='error'>{pageError}</View>}
            {detail.next_cursor && (
              <Button className='secondary-button' disabled={loadingMore} onClick={loadMore}>
                {loadingMore ? '加载中…' : '加载更多'}
              </Button>
            )}
          </View>
        </>
      )}
    </View>
  )
}
