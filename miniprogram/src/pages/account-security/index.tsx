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

export type AccountSecurityViewState = {
  identities: AuthIdentityRead[] | null
  loading: boolean
  error: string
}

export type AccountSecurityController = {
  getState: () => AccountSecurityViewState
  subscribe: (listener: (state: AccountSecurityViewState) => void) => () => void
  start: () => void
  refresh: () => Promise<void>
  dispose: () => void
}

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

export function createAccountSecurityController(
  load: () => Promise<AuthIdentityRead[]> = getAuthIdentities,
): AccountSecurityController {
  let state: AccountSecurityViewState = { identities: null, loading: true, error: '' }
  let generation = 0
  let started = false
  let disposed = false
  let unsubscribeSession: () => void = () => {}
  const listeners = new Set<(next: AccountSecurityViewState) => void>()

  const emit = () => {
    for (const listener of listeners) listener(state)
  }
  const setState = (next: AccountSecurityViewState) => {
    if (disposed) return
    state = next
    emit()
  }
  const current = (attempt: number, snapshot: ReturnType<typeof captureAuthSession>) =>
    !disposed && attempt === generation && isAuthSessionCurrent(snapshot)

  const refresh = async () => {
    const attempt = ++generation
    let snapshot: ReturnType<typeof captureAuthSession>
    try {
      snapshot = captureAuthSession()
    } catch {
      setState({ identities: null, loading: false, error: '请先登录后再管理账号安全' })
      return
    }
    setState({ identities: null, loading: true, error: '' })
    try {
      const identities = await load()
      if (!current(attempt, snapshot)) return
      setState({ identities, loading: false, error: '' })
    } catch (value) {
      if (!current(attempt, snapshot)) return
      setState({ identities: [], loading: false, error: safeIdentityError(value) })
    }
  }

  const start = () => {
    if (started || disposed) return
    started = true
    unsubscribeSession = subscribeAuthSession(() => {
      ++generation
      setState({ identities: null, loading: true, error: '' })
      void refresh()
    })
  }

  return {
    getState: () => state,
    subscribe: (listener) => {
      listeners.add(listener)
      listener(state)
      return () => listeners.delete(listener)
    },
    start,
    refresh,
    dispose: () => {
      if (disposed) return
      disposed = true
      ++generation
      unsubscribeSession()
      listeners.clear()
    },
  }
}

export default function Page() {
  const controllerRef = useRef<AccountSecurityController | null>(null)
  if (!controllerRef.current) controllerRef.current = createAccountSecurityController()
  const controller = controllerRef.current
  const [viewState, setViewState] = useState<AccountSecurityViewState>(controller.getState())

  useEffect(() => {
    const unsubscribe = controller.subscribe(setViewState)
    controller.start()
    return () => {
      unsubscribe()
      controller.dispose()
    }
  }, [controller])

  const manageDisabled = true
  const { identities, loading, error } = viewState

  return (
    <View className='account-security-page'>
      <View className='page-title'>账号与安全</View>
      <View className='page-subtitle'>只展示服务器确认的登录身份，不从个人资料推断绑定关系。</View>
      <Button className='secondary-button' loading={loading} onClick={() => void controller.refresh()}>刷新登录身份</Button>

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
