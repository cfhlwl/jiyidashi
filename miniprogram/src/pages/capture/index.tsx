import { Button, Input, Textarea, View } from '@tarojs/components'
import { useState } from 'react'
import { createTextMemory, isAuthenticated, rememberObjectLocation } from '../../services/api'
import './index.scss'

export default function Page() {
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [objectName, setObjectName] = useState('')
  const [locationText, setLocationText] = useState('')
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)

  const ensureLogin = () => {
    if (isAuthenticated()) return true
    setStatus('请先到“我的”页面登录正式账号')
    return false
  }

  const saveMemory = async () => {
    if (!ensureLogin()) return
    if (!content.trim()) {
      setStatus('请先写下需要记住的内容')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      const memory = await createTextMemory(content, title)
      setContent('')
      setTitle('')
      setStatus(`✓ 已经帮你记住 · ${memory.id}`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '保存失败')
    } finally {
      setLoading(false)
    }
  }

  const saveObject = async () => {
    if (!ensureLogin()) return
    if (!objectName.trim() || !locationText.trim()) {
      setStatus('请填写物品名称和位置')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      // [人工注释][S1-009] 物品位置记录直接走服务端 ObjectLocation 可信链，不在小程序本地伪造当前位置。
      await rememberObjectLocation(objectName, locationText)
      setStatus(`✓ 已记录：${objectName.trim()} 在 ${locationText.trim()}`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '保存失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <View className='page'>
      <View className='title'>记一下</View>
      <View className='subtitle'>Stage 1 第一批先支持文字和“东西在哪”。</View>

      <View className='card'>
        <View className='card-title'>写一句</View>
        <Input className='field' type='text' placeholder='标题（可选）' value={title} onInput={(e) => setTitle(e.detail.value)} />
        <Textarea className='field textarea' placeholder='例如：老张周五下午来公司取合同。' value={content} onInput={(e) => setContent(e.detail.value)} />
        <Button className='primary-button' disabled={loading} onClick={saveMemory}>帮我记住</Button>
      </View>

      <View className='card'>
        <View className='card-title'>东西在哪</View>
        <Input className='field' type='text' placeholder='物品，例如：护照' value={objectName} onInput={(e) => setObjectName(e.detail.value)} />
        <Input className='field' type='text' placeholder='位置，例如：书房左侧柜子第二层' value={locationText} onInput={(e) => setLocationText(e.detail.value)} />
        <Button className='secondary-button' disabled={loading} onClick={saveObject}>记录当前位置</Button>
      </View>

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
