import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Input, Switch, Text, View } from '@tarojs/components'
import { useRef, useState } from 'react'
import {
  acceptFamilyInvite,
  apiErrorCode,
  createFamily,
  createFamilyInvite,
  getFamily,
  getFamilyCurrentLocation,
  getFamilyMemories,
  getFamilyPermissions,
  getFamilyTodayFootprint,
  getProfile,
  isAuthenticated,
  removeFamilyMember,
  replaceFamilyPermissions,
  revokeFamilyInvite,
} from '../../services/api'
import {
  assertCurrentFamilyMember,
  FAMILY_PERMISSION,
  familyErrorMessage,
  familyMemberActions,
  FamilyPermissionMutationGate,
  FamilySensitiveReadEpoch,
  INTERACTIVE_FAMILY_PERMISSIONS,
  permissionLabel,
  replaceVisiblePermission,
  shortMemberId,
  type FamilyCurrentLocation,
  type FamilyInvite,
  type FamilyMemory,
  type FamilyPermissionGrant,
  type FamilyResponse,
  type InteractiveFamilyPermissionCode,
} from '../../services/family'
import { toTodayFootprintRow, type TodayFootprintResponse } from '../../services/todayFootprint'
import './index.scss'

type ReadyState = {
  phase: 'family-ready'
  family: FamilyResponse
  currentUserId: string
  permissions: FamilyPermissionGrant[]
}

type PageState =
  | { phase: 'signed-out' }
  | { phase: 'loading' }
  | { phase: 'no-family' }
  | ReadyState
  | { phase: 'error'; message: string }

type AsyncRead<T> =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'ready'; data: T }
  | { state: 'error'; message: string }

type MemberReads = Record<string, {
  location?: AsyncRead<FamilyCurrentLocation>
  footprint?: AsyncRead<TodayFootprintResponse>
  memory?: AsyncRead<FamilyMemory[]>
}>

function fallbackError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function mappedError(error: unknown, context: Parameters<typeof familyErrorMessage>[1], fallback: string): string {
  // Family UX only exposes deliberately mapped server codes. Unknown API/parser/network
  // failures stay generic and retryable instead of leaking backend detail strings.
  return familyErrorMessage(apiErrorCode(error), context) || fallback
}

export default function Page() {
  const [pageState, setPageState] = useState<PageState>({ phase: 'loading' })
  const [status, setStatus] = useState('')
  const [joinToken, setJoinToken] = useState('')
  const [invite, setInvite] = useState<FamilyInvite | null>(null)
  const [creatingFamily, setCreatingFamily] = useState(false)
  const [joiningFamily, setJoiningFamily] = useState(false)
  const [inviteBusy, setInviteBusy] = useState(false)
  const [memberBusy, setMemberBusy] = useState<Record<string, boolean>>({})
  const [permissionBusy, setPermissionBusy] = useState<Record<string, boolean>>({})
  const [memberReads, setMemberReads] = useState<MemberReads>({})
  const permissionGate = useRef(new FamilyPermissionMutationGate())
  const sensitiveReadEpoch = useRef(new FamilySensitiveReadEpoch())

  const clearFamilyTransientState = () => {
    setInvite(null)
    setMemberReads({})
    setMemberBusy({})
    setPermissionBusy({})
  }

  const refresh = async (clearTransient = false) => {
    // Every authoritative tab/page refresh invalidates earlier explicit sensitive reads.
    // A response that was started before this point can no longer repopulate disclosure UI.
    sensitiveReadEpoch.current.invalidate()

    if (!isAuthenticated()) {
      clearFamilyTransientState()
      setStatus('')
      setPageState({ phase: 'signed-out' })
      return
    }

    setPageState({ phase: 'loading' })
    setStatus('')
    // Sensitive family reads are disclosure snapshots, not tab state. Clear them on
    // every authoritative refresh so returning to this tab requires another explicit tap.
    setMemberReads({})
    if (clearTransient) clearFamilyTransientState()

    try {
      // [人工注释][S4-010][S4-006] tab 激活只读取 Family 自身与“我授权给别人”的 outbound grants。
      // 任何家人位置/足迹/个人记忆都不在这里探测，必须由用户点击对应按钮后再读取。
      const family = await getFamily()
      const profile = await getProfile()
      assertCurrentFamilyMember(family, profile.id)
      const permissions = await getFamilyPermissions()
      setPageState({
        phase: 'family-ready',
        family,
        currentUserId: profile.id,
        permissions,
      })
    } catch (error) {
      if (apiErrorCode(error) === 'FAMILY_NOT_FOUND') {
        clearFamilyTransientState()
        setPageState({ phase: 'no-family' })
        return
      }
      setPageState({
        phase: 'error',
        message: mappedError(error, 'load', '家庭信息加载失败，请重试'),
      })
    }
  }

  useDidShow(() => {
    void refresh()
  })

  const create = async () => {
    if (creatingFamily) return
    setCreatingFamily(true)
    setStatus('')
    try {
      await createFamily()
      await refresh(true)
      setStatus('家庭已创建')
    } catch (error) {
      setStatus(mappedError(error, 'create', '创建家庭失败'))
    } finally {
      setCreatingFamily(false)
    }
  }

  const join = async () => {
    if (joiningFamily) return
    const token = joinToken.trim()
    if (!token) {
      setStatus('请输入邀请口令')
      return
    }
    setJoiningFamily(true)
    setStatus('')
    try {
      await acceptFamilyInvite(token)
      setJoinToken('')
      await refresh(true)
      setStatus('已加入家庭')
    } catch (error) {
      setStatus(mappedError(error, 'join', '加入家庭失败'))
    } finally {
      setJoiningFamily(false)
    }
  }

  const createInvite = async () => {
    if (inviteBusy) return
    setInviteBusy(true)
    setStatus('')
    try {
      setInvite(await createFamilyInvite())
      setStatus('邀请已创建，请将口令安全地发给家人')
    } catch (error) {
      setStatus(mappedError(error, 'invite-create', '创建邀请失败'))
    } finally {
      setInviteBusy(false)
    }
  }

  const revokeInvite = async () => {
    if (!invite || inviteBusy) return
    setInviteBusy(true)
    setStatus('')
    try {
      await revokeFamilyInvite(invite.invite_id)
      setInvite(null)
      setStatus('邀请已撤销')
    } catch (error) {
      setStatus(mappedError(error, 'invite-revoke', '撤销邀请失败'))
    } finally {
      setInviteBusy(false)
    }
  }

  const copyInvite = async () => {
    if (!invite) return
    try {
      await Taro.setClipboardData({ data: invite.token })
      setStatus('邀请口令已复制')
    } catch (error) {
      setStatus(fallbackError(error, '复制失败，请手动复制口令'))
    }
  }

  const mutateMember = async (targetUserId: string, mode: 'remove' | 'leave') => {
    if (memberBusy[targetUserId]) return
    const confirm = await Taro.showModal({
      title: mode === 'leave' ? '退出家庭？' : '移除成员？',
      content: mode === 'leave'
        ? '退出后，你与家庭成员之间现有的共享授权会由服务端清理。'
        : '移除后，与该成员相关的家庭共享授权会由服务端清理。',
      confirmText: mode === 'leave' ? '确认退出' : '确认移除',
      confirmColor: '#b3261e',
    })
    if (!confirm.confirm) return

    setMemberBusy((current) => ({ ...current, [targetUserId]: true }))
    setStatus('')
    try {
      await removeFamilyMember(targetUserId)
      await refresh(true)
      setStatus(mode === 'leave' ? '已退出家庭' : '成员已移除')
    } catch (error) {
      setStatus(mappedError(error, mode, mode === 'leave' ? '退出家庭失败' : '移除成员失败'))
    } finally {
      setMemberBusy((current) => ({ ...current, [targetUserId]: false }))
    }
  }

  const updatePermission = async (
    granteeUserId: string,
    code: InteractiveFamilyPermissionCode,
    enabled: boolean,
  ) => {
    if (pageState.phase !== 'family-ready') return
    if (!permissionGate.current.begin(granteeUserId)) return

    setPermissionBusy((current) => ({ ...current, [granteeUserId]: true }))
    setStatus('')
    const currentGrant = pageState.permissions.find(
      (item) => item.grantee_user_id.toLowerCase() === granteeUserId.toLowerCase(),
    )
    const nextPermissions = replaceVisiblePermission(currentGrant?.permissions || [], code, enabled)

    try {
      // [人工注释][S4-010] PUT 是完整 replacement。只在服务端成功响应后更新 UI，
      // 并保留当前响应中尚不认识的 future permission code，避免 visible toggle 抹掉它们。
      const authoritative = await replaceFamilyPermissions(granteeUserId, nextPermissions)
      setPageState((current) => {
        if (current.phase !== 'family-ready') return current
        return {
          ...current,
          permissions: [
            ...current.permissions.filter(
              (item) => item.grantee_user_id.toLowerCase() !== granteeUserId.toLowerCase(),
            ),
            authoritative,
          ],
        }
      })
    } catch (error) {
      setStatus(mappedError(error, 'permission', '权限更新失败，已重新读取服务端状态'))
      try {
        const authoritative = await getFamilyPermissions()
        setPageState((current) => current.phase === 'family-ready'
          ? { ...current, permissions: authoritative }
          : current)
      } catch {
        // Keep the visible failure. A subsequent tab show will reload authority.
      }
    } finally {
      permissionGate.current.end(granteeUserId)
      setPermissionBusy((current) => ({ ...current, [granteeUserId]: false }))
    }
  }

  const readLocation = async (resourceOwnerUserId: string) => {
    const readEpoch = sensitiveReadEpoch.current.capture()
    setMemberReads((current) => ({
      ...current,
      [resourceOwnerUserId]: {
        ...current[resourceOwnerUserId],
        location: { state: 'loading' },
      },
    }))
    try {
      const data = await getFamilyCurrentLocation(resourceOwnerUserId)
      if (!sensitiveReadEpoch.current.isCurrent(readEpoch)) return
      setMemberReads((current) => ({
        ...current,
        [resourceOwnerUserId]: {
          ...current[resourceOwnerUserId],
          location: { state: 'ready', data },
        },
      }))
    } catch (error) {
      if (!sensitiveReadEpoch.current.isCurrent(readEpoch)) return
      setMemberReads((current) => ({
        ...current,
        [resourceOwnerUserId]: {
          ...current[resourceOwnerUserId],
          location: {
            state: 'error',
            message: mappedError(error, 'current-location', '当前位置读取失败'),
          },
        },
      }))
    }
  }

  const readFootprint = async (resourceOwnerUserId: string) => {
    const readEpoch = sensitiveReadEpoch.current.capture()
    setMemberReads((current) => ({
      ...current,
      [resourceOwnerUserId]: {
        ...current[resourceOwnerUserId],
        footprint: { state: 'loading' },
      },
    }))
    try {
      const data = await getFamilyTodayFootprint(resourceOwnerUserId)
      if (!sensitiveReadEpoch.current.isCurrent(readEpoch)) return
      setMemberReads((current) => ({
        ...current,
        [resourceOwnerUserId]: {
          ...current[resourceOwnerUserId],
          footprint: { state: 'ready', data },
        },
      }))
    } catch (error) {
      if (!sensitiveReadEpoch.current.isCurrent(readEpoch)) return
      setMemberReads((current) => ({
        ...current,
        [resourceOwnerUserId]: {
          ...current[resourceOwnerUserId],
          footprint: {
            state: 'error',
            message: mappedError(error, 'footprint', '今日足迹读取失败'),
          },
        },
      }))
    }
  }

  const readMemory = async (resourceOwnerUserId: string) => {
    const readEpoch = sensitiveReadEpoch.current.capture()
    setMemberReads((current) => ({
      ...current,
      [resourceOwnerUserId]: {
        ...current[resourceOwnerUserId],
        memory: { state: 'loading' },
      },
    }))
    try {
      const data = await getFamilyMemories(resourceOwnerUserId)
      if (!sensitiveReadEpoch.current.isCurrent(readEpoch)) return
      setMemberReads((current) => ({
        ...current,
        [resourceOwnerUserId]: {
          ...current[resourceOwnerUserId],
          memory: { state: 'ready', data },
        },
      }))
    } catch (error) {
      if (!sensitiveReadEpoch.current.isCurrent(readEpoch)) return
      setMemberReads((current) => ({
        ...current,
        [resourceOwnerUserId]: {
          ...current[resourceOwnerUserId],
          memory: {
            state: 'error',
            message: mappedError(error, 'memory', '个人记忆读取失败'),
          },
        },
      }))
    }
  }

  const renderLocation = (read: AsyncRead<FamilyCurrentLocation> | undefined) => {
    if (!read || read.state === 'idle') return null
    if (read.state === 'loading') return <View className='muted read-state'>正在读取当前位置…</View>
    if (read.state === 'error') return <View className='error read-state'>{read.message}</View>
    return (
      <View className='sensitive-result'>
        <View>纬度：{read.data.latitude}</View>
        <View>经度：{read.data.longitude}</View>
        <View>精度：{read.data.accuracy === null ? '未知' : `${read.data.accuracy} 米`}</View>
        <View className='muted'>记录时间：{read.data.recorded_at}</View>
        <View className='muted'>有效至：{read.data.fresh_until}</View>
      </View>
    )
  }

  const renderFootprint = (read: AsyncRead<TodayFootprintResponse> | undefined) => {
    if (!read || read.state === 'idle') return null
    if (read.state === 'loading') return <View className='muted read-state'>正在读取今日足迹…</View>
    if (read.state === 'error') return <View className='error read-state'>{read.message}</View>
    const rows = read.data.visits.map(toTodayFootprintRow)
    return (
      <View className='sensitive-result'>
        <View className='muted'>{read.data.day} · {read.data.timezone}</View>
        {rows.length === 0 && <View className='read-state'>今日暂无足迹</View>}
        {rows.map((row) => (
          <View className='footprint-row' key={row.id}>
            <View className='footprint-place'>{row.placeName}</View>
            <View>{row.timeRange}</View>
            <View className='muted'>{row.stateLabel} · {row.source}</View>
          </View>
        ))}
      </View>
    )
  }

  const renderMemory = (read: AsyncRead<FamilyMemory[]> | undefined) => {
    if (!read || read.state === 'idle') return null
    if (read.state === 'loading') return <View className='muted read-state'>正在读取个人记忆…</View>
    if (read.state === 'error') return <View className='error read-state'>{read.message}</View>
    return (
      <View className='sensitive-result'>
        {read.data.length === 0 && (
          <View className='read-state'>对方当前没有可显示的记忆</View>
        )}
        {read.data.map((memory) => (
          <View className='memory-row' key={memory.memory_id}>
            <View className='memory-title'>{memory.title || '未命名记忆'}</View>
            <View className='memory-content'>{memory.content}</View>
            <View className='muted'>{memory.occurred_at}</View>
            <View className='muted'>
              {memory.memory_type} · {memory.source_type} · {memory.is_confirmed ? '已确认' : '待确认'}
            </View>
          </View>
        ))}
      </View>
    )
  }

  if (pageState.phase === 'signed-out') {
    return (
      <View className='page'>
        <View className='title'>家庭</View>
        <View className='subtitle'>共享必须逐项授权。</View>
        <View className='card empty-card'>
          <View className='card-title'>请先登录后使用家庭功能</View>
          <Text className='muted'>登录后才能创建或加入家庭，加入同一个家庭也不会自动共享任何数据。</Text>
          <Button className='primary-button' onClick={() => Taro.switchTab({ url: '/pages/profile/index' })}>
            前往“我的”
          </Button>
        </View>
      </View>
    )
  }

  if (pageState.phase === 'loading') {
    return (
      <View className='page'>
        <View className='title'>家庭</View>
        <View className='subtitle'>共享必须逐项授权。</View>
        <View className='card'><Text className='muted'>正在加载家庭状态…</Text></View>
      </View>
    )
  }

  if (pageState.phase === 'error') {
    return (
      <View className='page'>
        <View className='title'>家庭</View>
        <View className='subtitle'>共享必须逐项授权。</View>
        <View className='card'>
          <View className='error'>{pageState.message}</View>
          <Button className='secondary-button' onClick={() => refresh()}>重新加载</Button>
        </View>
      </View>
    )
  }

  if (pageState.phase === 'no-family') {
    return (
      <View className='page'>
        <View className='title'>家庭</View>
        <View className='subtitle'>共享必须逐项授权。</View>
        <View className='privacy-note'>加入同一个家庭 ≠ 自动共享数据。共享必须由本人逐项授权。</View>
        <View className='card'>
          <View className='card-title'>创建家庭</View>
          <Text className='muted'>由你成为 OWNER，再创建一次性邀请口令给家人。</Text>
          <Button className='primary-button' disabled={creatingFamily || joiningFamily} onClick={create}>
            {creatingFamily ? '正在创建…' : '创建家庭'}
          </Button>
        </View>
        <View className='card'>
          <View className='card-title'>加入家庭</View>
          <Text className='muted'>粘贴家人发给你的邀请口令。口令只按原样提交给服务端判断。</Text>
          <Input
            className='field'
            type='text'
            placeholder='输入邀请口令'
            value={joinToken}
            onInput={(event: { detail: { value: string } }) => setJoinToken(event.detail.value)}
          />
          <Button className='secondary-button' disabled={joiningFamily || creatingFamily} onClick={join}>
            {joiningFamily ? '正在加入…' : '加入家庭'}
          </Button>
        </View>
        {status && <View className='status'>{status}</View>}
      </View>
    )
  }

  const { family, currentUserId, permissions } = pageState

  return (
    <View className='page'>
      <View className='title'>家庭</View>
      <View className='subtitle'>共享必须逐项授权。</View>
      <View className='privacy-note'>加入同一个家庭 ≠ 自动共享数据。共享必须由本人逐项授权。</View>

      <View className='card family-summary'>
        <View className='summary-item'>
          <View className='summary-value'>{family.members.length}</View>
          <View className='muted'>家庭成员</View>
        </View>
        <View className='summary-item'>
          <View className='summary-value'>{family.current_user_role}</View>
          <View className='muted'>我的身份</View>
        </View>
      </View>

      {family.current_user_role === 'OWNER' && (
        <View className='card'>
          <View className='card-title'>邀请家人</View>
          <Text className='muted'>邀请口令仅保留在当前页面状态，不写入本地缓存。</Text>
          {!invite && (
            <Button className='primary-button' disabled={inviteBusy} onClick={createInvite}>
              {inviteBusy ? '正在创建…' : '创建邀请'}
            </Button>
          )}
          {invite && (
            <View className='invite-box'>
              <View className='invite-token'>{invite.token}</View>
              <View className='muted'>有效期至：{invite.expires_at}</View>
              <View className='button-row'>
                <Button className='secondary-button compact-button' disabled={inviteBusy} onClick={copyInvite}>复制口令</Button>
                <Button className='danger-button compact-button' disabled={inviteBusy} onClick={revokeInvite}>撤销邀请</Button>
              </View>
            </View>
          )}
        </View>
      )}

      <View className='section-title'>家庭成员</View>
      {family.members.map((member) => {
        const actions = familyMemberActions(currentUserId, family.current_user_role, member)
        const grant = permissions.find(
          (item) => item.grantee_user_id.toLowerCase() === member.user_id.toLowerCase(),
        )
        const granted = grant?.permissions || []
        const busy = Boolean(permissionBusy[member.user_id])
        const reads = memberReads[member.user_id]

        return (
          <View className='card member-card' key={member.user_id}>
            <View className='member-header'>
              <View>
                <View className='card-title member-title'>
                  {member.role} · 成员 {shortMemberId(member.user_id)} {actions.isSelf ? '（我）' : ''}
                </View>
                <View className='muted'>加入时间：{member.created_at}</View>
              </View>
            </View>

            {actions.showPermissionControls && (
              <View className='member-section'>
                <View className='member-section-title'>我允许 TA 查看：</View>
                {INTERACTIVE_FAMILY_PERMISSIONS.map((code) => (
                  <View className='permission-row' key={code}>
                    <Text>{permissionLabel(code)}</Text>
                    <Switch
                      checked={granted.includes(code)}
                      disabled={busy}
                      onChange={(event: { detail: { value: boolean } }) => updatePermission(member.user_id, code, event.detail.value)}
                    />
                  </View>
                ))}
                <View className='future-permission'>照片 <Text className='muted'>暂未开放</Text></View>
                {busy && <View className='muted'>正在保存授权…</View>}
              </View>
            )}

            {actions.showSensitiveReads && (
              <View className='member-section'>
                <View className='member-section-title'>我查看 TA：</View>
                <Text className='muted'>是否可查看只由对方给你的精确授权决定，不从上面的开关推断。</Text>
                <Button
                  className='secondary-button'
                  disabled={reads?.location?.state === 'loading'}
                  onClick={() => readLocation(member.user_id)}
                >
                  查看当前位置
                </Button>
                {renderLocation(reads?.location)}
                <Button
                  className='secondary-button'
                  disabled={reads?.footprint?.state === 'loading'}
                  onClick={() => readFootprint(member.user_id)}
                >
                  查看今日足迹
                </Button>
                {renderFootprint(reads?.footprint)}
                <Button
                  className='secondary-button'
                  disabled={reads?.memory?.state === 'loading'}
                  onClick={() => readMemory(member.user_id)}
                >
                  查看个人记忆
                </Button>
                {renderMemory(reads?.memory)}
              </View>
            )}

            {actions.showOwnerRemove && (
              <Button
                className='danger-button'
                disabled={Boolean(memberBusy[member.user_id])}
                onClick={() => mutateMember(member.user_id, 'remove')}
              >
                {memberBusy[member.user_id] ? '正在移除…' : '移除成员'}
              </Button>
            )}

            {actions.showMemberLeave && (
              <Button
                className='danger-button'
                disabled={Boolean(memberBusy[member.user_id])}
                onClick={() => mutateMember(member.user_id, 'leave')}
              >
                {memberBusy[member.user_id] ? '正在退出…' : '退出家庭'}
              </Button>
            )}
          </View>
        )
      })}

      {status && <View className='status'>{status}</View>}
    </View>
  )
}
