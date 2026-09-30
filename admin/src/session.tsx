import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { adminRequest, postJson } from './api'
import type { AdminSession } from './types'

type SessionState = {
  loading: boolean
  session: AdminSession | null
  error: string | null
  refresh: () => Promise<void>
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const SessionContext = createContext<SessionState | null>(null)

export function AdminSessionProvider({ children }: PropsWithChildren) {
  const [loading, setLoading] = useState(true)
  const [session, setSession] = useState<AdminSession | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setSession(await adminRequest<AdminSession>('/auth/session'))
    } catch {
      setSession(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(async (email: string, password: string) => {
    setError(null)
    try {
      const next = await postJson<AdminSession>('/auth/login', { email, password })
      setSession(next)
    } catch (err) {
      const message = err instanceof Error ? err.message : '登录没有完成，请稍后重试'
      setError(message)
      throw err
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await postJson('/auth/logout')
    } finally {
      setSession(null)
    }
  }, [])

  const value = useMemo(
    () => ({ loading, session, error, refresh, login, logout }),
    [loading, session, error, refresh, login, logout],
  )
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useAdminSession() {
  const value = useContext(SessionContext)
  if (!value) throw new Error('AdminSessionProvider is required')
  return value
}
