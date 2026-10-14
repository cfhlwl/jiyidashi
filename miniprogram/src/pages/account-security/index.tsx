import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { useEffect, useRef, useState } from 'react'
import {
  apiErrorCode,
  ApiRequestError,
  captureAuthSession,
  getAuthIdentities,
  isAuthSessionCurrent,
  type AuthIdentityRead,
  subscribeAuthSession,
} from '../../services/api'
import './index.scss'

function providerName(provider: string): string {
  switch (provider) {
    case 'EMAIL_PASSWORD': return '邮箱密码'
    case 'PHONE': return '手机号'
    case 'WECHAT': return '微信'
    case 'WECHAT_MINIPROGRAM': return '微信小程序'
    default: return '其他登录方式'
  }
}

function safeIdentityError(error: unknown): string {
  const code = apiErrorCode(error)
  if (error instanceof ApiRequestError) {
    if (error.statusCode === 401 || code === 'AUTH_SESSION_INVALID') return '登录状态已失效，请重新登录'
    if (error.statusCode === 403) return '当前账号没有管理身份的权限'
    if (error.statusCode === 423) return '账号注销进行中，暂不能管理登录方式'
    if (error.statusCode === 429) return '操作过于频繁，请稍后再试'
    if (error.statusCode >= 500) return '服务暂不可用，请稍后重试'
  }
  if (code === 'AUTH_IDENTITY_OPERATION_IN_PROGRESS' || code === 'AUTH_IDENTITY_OPERATION_UNKNOWN') return '身份操作状态未确认，请刷新后再试'
  if (code === 'AUTH_IDENTITY_CONFLICT') return '此方式无法绑定，请确认身份或联系客服'
  return '暂时无法读取登录身份，请稍后重试'
}

export default function Page() {
  const [identities, setIdentities] = useState<AuthIdentityRead[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const generation = useRef(0)

  const refresh = async () => {
    const currentGeneration = ++generation.current
    let snapshot
    try {
      snapshot = captureAuthSession()
    } catch {
      setIdentities(null)
      setLoading(false)
      setError('请先登录后再管理账号安全')
      return
    }
    setLoading(true)
    setError('')
    try {
      const next = await getAuthIdentities()
      if (currentGeneration !== generation.current || !isAuthSessionCurrent(snapshot)) return
      setIdentities(next)
    } catch (value) {
      if (currentGeneration !== generation.current || !isAuthSessionCurrent(snapshot)) return
      setIdentities([])
      setError(safeIdentityError(value))
    } finally {
      if (currentGeneration === generation.current && isAuthSessionCurrent(snapshot)) setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    const unsubscribe = subscribeAuthSession(() => {
      generation.current += 1
      setIdentities(null)
      void refresh()
    })
    return () => {
      generation.current += 1
      unsubscribe()
    }
  }, [])

  const manageDisabled = true

  return (
    <View className='account-security-page'>
      <View className='page-title'>账号与安全</View>
      <View className='page-subtitle'>只展示服务器确认的登录身份，不从个人资料推断绑定关系。</View>
      <Button className='secondary-button' loading={loading} onClick={() => void refresh()}>刷新登录身份</Button>

      {loading && <View className='state-card'>正在读取登录身份…</View>}
      {!loading && error && <View className='state-card error'>{error}</View>}
      {!loading && !error && identities?.length === 0 && <View className='state-card'>当前没有可展示的登录身份。</View>}
      {!loading && !error && identities?.map((identity) => (
        <IdentityCard key={identity.identity_id} identity={identity} disabled={manageDisabled} />
      ))}

      <View className='card provider-off-card'>
        <View className='card-title'>绑定与解绑</View>
        <Text className='muted'>当前未配置可用的身份绑定服务。需要真实 provider 和近期重新认证后，操作才会开放。</Text>
        <Button className='secondary-button' disabled={manageDisabled} onClick={() => undefined}>绑定新的登录方式</Button>
      </View>
      <View className='card'>
        <View className='card-title'>安全提示</View>
        <Text className='muted'>身份冲突、账号注销中和重新认证不足均由服务端最终裁决；本页面不会展示完整手机号、openid、unionid 或认证凭证。</Text>
      </View>
      <Button className='secondary-button' onClick={() => Taro.navigateBack()}>返回</Button>
    </View>
  )
}

function IdentityCard({ identity, disabled }: { identity: AuthIdentityRead; disabled: boolean }) {
  return (
    <View className='card identity-card'>
      <View className='card-title'>{providerName(identity.provider)}</View>
      <View className='subject-hint'>{identity.subject_hint}</View>
      <View className='muted'>{identity.verified_at ? '已验证' : '未验证'} · 绑定时间 {identity.linked_at}</View>
      <Button className='danger-button' disabled={disabled} onClick={() => undefined}>解绑</Button>
    </View>
  )
}
