import { Button, Input, Text, View } from '@tarojs/components'
import { useEffect, useState } from 'react'
import {
  getApiBaseUrl,
  getProfile,
  isAuthenticated,
  loginAccount,
  logout,
  registerAccount,
  setApiBaseUrl,
} from '../../services/api'
import './index.scss'

export default function Page() {
  const [registerMode, setRegisterMode] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [apiBase, setApiBase] = useState(getApiBaseUrl())
  const [profile, setProfile] = useState<Awaited<ReturnType<typeof getProfile>> | null>(null)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)

  const refreshProfile = async () => {
    if (!isAuthenticated()) {
      setProfile(null)
      return
    }
    try {
      setProfile(await getProfile())
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '读取资料失败')
    }
  }

  useEffect(() => {
    void refreshProfile()
  }, [])

  const submit = async () => {
    if (!email.trim() || !password) {
      setStatus('请输入邮箱和密码')
      return
    }
    if (registerMode && !nickname.trim()) {
      setStatus('请输入昵称')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      // [人工注释][S1-001] 登录/注册成功后才允许进入个人记忆 API，Token 保存在微信本地存储。
      if (registerMode) {
        await registerAccount({ email, password, nickname })
      } else {
        await loginAccount(email, password)
      }
      await refreshProfile()
      setStatus(registerMode ? '账号创建成功' : '登录成功')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '认证失败')
    } finally {
      setLoading(false)
    }
  }

  const saveApiBase = () => {
    setApiBaseUrl(apiBase)
    setStatus('开发环境 API 地址已保存')
  }

  if (profile) {
    return (
      <View className='page'>
        <View className='title'>我的</View>
        <View className='subtitle'>你的记忆由你控制。</View>
        <View className='card'>
          <View className='card-title'>{profile.nickname}</View>
          <Text>{profile.email || ''}</Text>
          <View className='muted'>时区：{profile.timezone}</View>
          <View className='muted'>语言：{profile.locale}</View>
        </View>
        <Button
          className='secondary-button'
          onClick={() => {
            logout()
            setProfile(null)
            setStatus('已退出登录')
          }}
        >
          退出登录
        </Button>
        {status && <View className='status'>{status}</View>}
      </View>
    )
  }

  return (
    <View className='page'>
      <View className='title'>我的</View>
      <View className='subtitle'>先登录正式账号，再开始保存个人记忆。</View>
      <View className='card'>
        <View className='card-title'>{registerMode ? '创建账号' : '登录'}</View>
        <Input className='field' type='text' placeholder='邮箱' value={email} onInput={(e) => setEmail(e.detail.value)} />
        <Input className='field' password placeholder='密码（至少 10 位）' value={password} onInput={(e) => setPassword(e.detail.value)} />
        {registerMode && (
          <Input className='field' type='text' placeholder='昵称' value={nickname} onInput={(e) => setNickname(e.detail.value)} />
        )}
        <Button className='primary-button' disabled={loading} onClick={submit}>
          {loading ? '请稍候…' : registerMode ? '创建账号' : '登录'}
        </Button>
        <Button className='secondary-button' onClick={() => setRegisterMode(!registerMode)}>
          {registerMode ? '已有账号？登录' : '第一次使用？创建账号'}
        </Button>
      </View>
      <View className='card'>
        <View className='card-title'>开发环境 API</View>
        <Input className='field' type='text' value={apiBase} onInput={(e) => setApiBase(e.detail.value)} />
        <Button className='secondary-button' onClick={saveApiBase}>保存 API 地址</Button>
      </View>
      {status && <View className='status'>{status}</View>}
    </View>
  )
}
