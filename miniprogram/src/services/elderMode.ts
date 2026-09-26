export type ElderUserProfile = {
  id: string
  nickname: string
  email?: string | null
  timezone: string
  locale: string
  elder_mode_enabled: boolean
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('个人资料格式异常')
  }
  return value as Record<string, unknown>
}

function requiredString(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error('个人资料格式异常')
  return value
}

export function parseElderUserProfile(value: unknown): ElderUserProfile {
  const raw = record(value)
  const elder = typeof raw.elder_mode_enabled === 'boolean'
    ? raw.elder_mode_enabled
    : false
  const email = raw.email
  if (email !== undefined && email !== null && typeof email !== 'string') {
    throw new Error('个人资料格式异常')
  }
  return {
    id: requiredString(raw.id),
    nickname: requiredString(raw.nickname),
    email: email as string | null | undefined,
    timezone: requiredString(raw.timezone),
    locale: requiredString(raw.locale),
    elder_mode_enabled: elder,
  }
}

export function elderClassName(enabled: boolean, base = 'page'): string {
  return enabled ? `${base} elder-mode` : base
}


export type ElderProjectionListener = (enabled: boolean) => void

export class ElderProjectionStore {
  private owner: string | null = null
  private enabled = false
  private listeners = new Set<ElderProjectionListener>()

  current(currentOwner: string | null): boolean {
    return Boolean(currentOwner)
      && this.owner === currentOwner
      && this.enabled
  }

  publish(owner: string, enabled: boolean): void {
    this.owner = owner
    this.enabled = enabled
    this.emit()
  }

  reset(): void {
    this.owner = null
    this.enabled = false
    this.emit()
  }

  subscribe(
    currentOwner: () => string | null,
    listener: ElderProjectionListener,
  ): () => void {
    this.listeners.add(listener)
    listener(this.current(currentOwner()))
    return () => {
      this.listeners.delete(listener)
    }
  }

  private emit(): void {
    for (const listener of this.listeners) {
      listener(this.enabled)
    }
  }
}
