import { Button, Input, Text, View } from '@tarojs/components'
import { useState } from 'react'
import { isAuthenticated, MemoryQueryResult, queryMemory } from '../../services/api'
import './index.scss'

function sourceLabel(sourceType: string): string {
  const labels: Record<string, string> = {
    USER_TEXT: '用户文字记录',
    USER_VOICE: '用户语音记录',
    USER_PHOTO: '用户照片记录',
    GPS: 'GPS 位置证据',
    PHOTO_EXIF: '照片位置信息',
    SYSTEM_PLACE: '系统地点识别',
    AI_INFERENCE: 'AI 推测',
  }
  return labels[sourceType] || sourceType
}

export default function Page() {
  const [question, setQuestion] = useState('')
  const [result, setResult] = useState<MemoryQueryResult | null>(null)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async () => {
    if (!isAuthenticated()) {
      setStatus('请先到“我的”页面登录正式账号')
      return
    }
    if (!question.trim()) {
      setStatus('请输入你想回忆的问题')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      setResult(await queryMemory(question))
    } catch (error) {
      setResult(null)
      setStatus(error instanceof Error ? error.message : '查询失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <View className='page'>
      <View className='title'>问记忆</View>
      <View className='subtitle'>只从你的真实记忆证据里找答案。</View>
      <View className='card'>
        <Input className='field' type='text' placeholder='例如：我的护照在哪里？' value={question} onInput={(e) => setQuestion(e.detail.value)} />
        <Button className='primary-button' disabled={loading} onClick={submit}>{loading ? '查找中…' : '从我的记忆里查找'}</Button>
      </View>

      {result && (
        <View className='card'>
          <View className='card-title'>{result.can_answer ? result.answer || '' : '我没有找到相关记录。'}</View>
          <View className='muted'>可信状态：{result.certainty} · 意图：{result.intent}</View>
          {result.evidence.map((evidence) => (
            <View className='evidence' key={evidence.memory_source_id}>
              {/* [人工注释][S1-FIX-002] kind 只表示证据实体类型；UI 的“来源”必须显示真实 source_type。 */}
              <Text>{evidence.excerpt}</Text>
              <View className='muted'>来源：{sourceLabel(evidence.source_type)}</View>
              <View className='muted'>证据类型：{evidence.kind} · 时间：{evidence.occurred_at}</View>
              <View className='muted'>可信度：{evidence.confidence}</View>
            </View>
          ))}
        </View>
      )}

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
