import type { LogoutResult, RegistrationResponse } from '../../services/api'

type SubmitDeps<TOperation extends object> = {
  registerMode: boolean
  email: string
  password: string
  nickname: string
  beginOperation: () => TOperation
  operationIsCurrent: (operation: TOperation) => boolean
  registerAccount: (input: { email: string; password: string; nickname: string }) => Promise<RegistrationResponse>
  loginAccount: (email: string, password: string) => Promise<void>
  refreshProfile: () => Promise<void>
  setLoading: (value: boolean) => void
  setStatus: (value: string) => void
  setVerificationPendingEmail: (value: string | null) => void
}

export async function runProfileSubmit<TOperation extends object>(deps: SubmitDeps<TOperation>): Promise<void> {
  let operation = deps.beginOperation()
  deps.setLoading(true)
  deps.setStatus('')
  try {
    if (deps.registerMode) {
      const registration = await deps.registerAccount({
        email: deps.email,
        password: deps.password,
        nickname: deps.nickname,
      })
      if (!deps.operationIsCurrent(operation)) return
      deps.setVerificationPendingEmail(deps.email.trim())
      deps.setStatus(
        registration.verification_delivery_pending
          ? '账号已创建，验证邮件尚未送达，请稍后重试发送'
          : '账号已创建，请查收验证邮件后再登录',
      )
      return
    }

    // loginAccount advances the auth epoch before awaiting the network. Take
    // a new operation snapshot immediately after starting it so a password
    // error can still clear this submit's busy state and be retried.
    const loginPromise = deps.loginAccount(deps.email, deps.password)
    operation = deps.beginOperation()
    await loginPromise
    operation = deps.beginOperation()
    await deps.refreshProfile()
    if (!deps.operationIsCurrent(operation)) return
    deps.setVerificationPendingEmail(null)
    deps.setStatus('登录成功')
  } catch (error) {
    if (deps.operationIsCurrent(operation)) {
      deps.setStatus(error instanceof Error ? error.message : '认证失败')
    }
  } finally {
    if (deps.operationIsCurrent(operation)) deps.setLoading(false)
  }
}

type MutationDeps<TOperation extends object, TResult> = {
  beginOperation: () => TOperation
  operationIsCurrent: (operation: TOperation) => boolean
  currentViewGeneration: () => number
  isViewGenerationCurrent: (generation: number) => boolean
  action: () => Promise<TResult>
  applySuccess: (result: TResult) => void
  setLoading: (value: boolean) => void
  setStatus: (value: string) => void
  successStatus: string
  errorStatus: string
}

export async function runProfileMutation<TOperation extends object, TResult>(
  deps: MutationDeps<TOperation, TResult>,
): Promise<void> {
  const operation = deps.beginOperation()
  const viewGeneration = deps.currentViewGeneration()
  deps.setLoading(true)
  deps.setStatus('')
  try {
    const result = await deps.action()
    if (!deps.isViewGenerationCurrent(viewGeneration) || !deps.operationIsCurrent(operation)) return
    deps.applySuccess(result)
    deps.setStatus(deps.successStatus)
  } catch (error) {
    if (deps.operationIsCurrent(operation)) {
      deps.setStatus(error instanceof Error ? error.message : deps.errorStatus)
    }
  } finally {
    if (deps.operationIsCurrent(operation)) deps.setLoading(false)
  }
}

type LogoutDeps = {
  beginViewGeneration: () => number
  isViewGenerationCurrent: (generation: number) => boolean
  logout: () => Promise<LogoutResult>
  isAuthenticated: () => boolean
  setLoading: (value: boolean) => void
  setProfile: (value: null) => void
  setPrivacy: (value: null) => void
  clearForm: () => void
  setStatus: (value: string) => void
}

export async function runProfileLogout(deps: LogoutDeps): Promise<void> {
  // Fence old page work before local logout starts. logout() synchronously
  // clears the session and notifies the page, so capture a second generation
  // after that transition for the remote revoke result.
  deps.beginViewGeneration()
  const pendingLogout = deps.logout()
  const generation = deps.beginViewGeneration()
  // Logout is the current synchronous page transition: release the old
  // mutation's busy owner now, while its delayed finally remains fenced by
  // operation/auth generation and cannot clear a newer login's busy state.
  deps.setLoading(false)
  deps.setProfile(null)
  deps.setPrivacy(null)
  deps.clearForm()
  deps.setStatus('已退出登录')
  const result = await pendingLogout
  if (
    deps.isViewGenerationCurrent(generation)
    && !deps.isAuthenticated()
    && !result.serverRevoked
    && result.serverStatus !== 'NOT_ATTEMPTED'
  ) deps.setStatus('已退出登录；服务器注销未确认，请重新登录后检查账号状态')
}
