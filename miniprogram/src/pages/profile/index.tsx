import { Button, Input, Switch, Text, View } from '@tarojs/components'
import { useEffect, useState } from 'react'
import {
  canEditApiBaseUrl,
  getApiBaseUrl,
  getPrivacyStatus,
  getProfile,
  isAuthenticated,
  loginAccount,
  logout,
  pauseMemory,
  pauseMemoryToday,
  PrivacyStatus,
  registerAccount,
  resumeMemory,
  setApiBaseUrl,
  updateElderMode,
  updateProfile,
} from '../../services/api'
import { elderClassName } from '../../services/elderMode'
import './index.scss'

export default function Page() {
  const [registerMode, setRegisterMode] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [timezone, setTimezone] = useState('Asia/Shanghai')
  const [apiBase, setApiBase] = useState(getApiBaseUrl())
  const [profile, setProfile] = useState<Awaited<ReturnType<typeof getProfile>> | null>(null)
  const [privacy, setPrivacy] = useState<PrivacyStatus | null>(null)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const allowApiEdit = canEditApiBaseUrl()

  const applyProfile = (next: Awaited<ReturnType<typeof getProfile>>) => {
    setProfile(next)
    setNickname(next.nickname)
    setTimezone(next.timezone)
  }

  const refreshProfile = async () => {
    if (!isAuthenticated()) {
      setProfile(null)
      setPrivacy(null)
      return
    }
    try {
      applyProfile(await getProfile())
      setPrivacy(await getPrivacyStatus())
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

  const toggleElderMode = async (enabled: boolean) => {
    if (!profile || loading) return
    setLoading(true)
    setStatus('')
    try {
      applyProfile(await updateElderMode(enabled))
      setStatus(enabled ? '长辈模式已开启' : '长辈模式已关闭')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '长辈模式更新失败')
    } finally {
      setLoading(false)
    }
  }

  const saveProfile = async () => {
    if (!nickname.trim() || !timezone.trim()) {
      setStatus('昵称和时区不能为空')
      return
    }
    setLoading(true)
    setStatus('')
    try {
      // [人工注释][S1-002] 用户修改 IANA 时区后以后端返回值为准，客户端不自行推断自然日边界。
      applyProfile(await updateProfile({ nickname, timezone, locale: profile?.locale }))
      setStatus('资料已更新')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '资料更新失败')
    } finally {
      setLoading(false)
    }
  }

  const applyPrivacy = async (action: () => Promise<PrivacyStatus>, success: string) => {
    setLoading(true)
    setStatus('')
    try {
      setPrivacy(await action())
      setStatus(success)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '操作失败')
    } finally {
      setLoading(false)
    }
  }

  const saveApiBase = () => {
    try {
      setApiBaseUrl(apiBase)
      setStatus('开发环境 API 地址已保存')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'API 地址保存失败')
    }
  }

  if (profile) {
    return (
      <View className={elderClassName(profile.elder_mode_enabled)}>
        <View className='title'>我的</View>
        <View className='subtitle'>你的记忆由你控制。</View>
        <View className='card'>
          <View className='card-title'>账号资料</View>
          <Text>{profile.email || ''}</Text>
          <Input className='field' type='text' placeholder='昵称' value={nickname} onInput={(e) => setNickname(e.detail.value)} />
          <Input className='field' type='text' placeholder='IANA 时区，例如 Asia/Shanghai' value={timezone} onInput={(e) => setTimezone(e.detail.value)} />
          <View className='muted'>语言：{profile.locale}</View>
          <Button className='primary-button' disabled={loading} onClick={saveProfile}>保存资料</Button>
        </View>

        <View className='card elder-setting-card'>
          <View className='card-title'>长辈模式</View>
          <View className='muted'>只调整你自己的文字大小、按钮尺寸和页面层级，不改变任何家庭、位置、记忆或隐私权限。</View>
          <View className='elder-toggle-row'>
            <Text>{profile.elder_mode_enabled ? '已开启' : '未开启'}</Text>
            <Switch
              checked={profile.elder_mode_enabled}
              disabled={loading}
              aria-label='长辈模式'
              onChange={(event) => void toggleElderMode(event.detail.value)}
            />
          </View>
        </View>

        <View className='card'>
          <View className='card-title'>记忆暂停</View>
          <View className='muted'>
            {privacy?.recording_paused
              ? `自动记录已暂停${privacy.paused_until ? `，直到 ${privacy.paused_until}` : ''}`
              : '自动记录当前开启'}
          </View>
          {/* [人工注释][S1-023] 暂停只影响自动采集；用户主动“记一下”仍然允许。 */}
          <Button className='secondary-button' disabled={loading} onClick={() => applyPrivacy(() => pauseMemory(30), '已暂停 30 分钟')}>暂停 30 分钟</Button>
          <Button className='secondary-button' disabled={loading} onClick={() => applyPrivacy(() => pauseMemory(60), '已暂停 1 小时')}>暂停 1 小时</Button>
          <Button className='secondary-button' disabled={loading} onClick={() => applyPrivacy(() => pauseMemory(180), '已暂停 3 小时')}>暂停 3 小时</Button>
          <Button className='secondary-button' disabled={loading} onClick={() => applyPrivacy(pauseMemoryToday, '今天剩余时间已暂停')}>暂停今天</Button>
          {/* [人工注释][S1-024] 恢复后历史 pause interval 仍保留，暂停期间的自动数据不能补传入库。 */}
          <Button className='primary-button' disabled={loading || !privacy?.recording_paused} onClick={() => applyPrivacy(resumeMemory, '已恢复自动记录')}>恢复记录</Button>
        </View>

        <Button
          className='secondary-button'
          onClick={() => {
            logout()
            setProfile(null)
            setPrivacy(null)
            setEmail('')
            setPassword('')
            setNickname('')
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
      {allowApiEdit && (
        <View className='card'>
          {/* [人工注释][S1-FIX-007] 生产构建通过常量完全移除此入口，普通用户不能改写 API endpoint。 */}
          <View className='card-title'>开发环境 API</View>
          <Input className='field' type='text' value={apiBase} onInput={(e) => setApiBase(e.detail.value)} />
          <Button className='secondary-button' onClick={saveApiBase}>保存 API 地址</Button>
        </View>
      )}
      {status && <View className='status'>{status}</View>}
    </View>
  )
}
