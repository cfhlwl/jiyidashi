export type ElderFindThingsState =
  | 'IDLE'
  | 'QUERYING'
  | 'FOUND'
  | 'NOT_ENOUGH_EVIDENCE'
  | 'FAILED'

export class ElderFindQueryEpoch {
  private generation = 0

  capture(): number {
    this.generation += 1
    return this.generation
  }

  invalidate(): void {
    this.generation += 1
  }

  isCurrent(captured: number): boolean {
    return captured === this.generation
  }
}

export class ElderFindSingleFlight {
  private pending = false

  tryBegin(): boolean {
    if (this.pending) return false
    this.pending = true
    return true
  }

  end(): void {
    this.pending = false
  }

  get busy(): boolean {
    return this.pending
  }
}

export function elderFindState(input: {
  loading: boolean
  canAnswer: boolean | null
  failed: boolean
}): ElderFindThingsState {
  if (input.loading) return 'QUERYING'
  if (input.failed) return 'FAILED'
  if (input.canAnswer === true) return 'FOUND'
  if (input.canAnswer === false) return 'NOT_ENOUGH_EVIDENCE'
  return 'IDLE'
}

export function elderFindStateLabel(state: ElderFindThingsState): string {
  switch (state) {
    case 'IDLE':
      return '告诉我你要找什么'
    case 'QUERYING':
      return '正在从你的记录里查找'
    case 'FOUND':
      return '找到了可信记录'
    case 'NOT_ENOUGH_EVIDENCE':
      return '我还不知道它在哪里'
    case 'FAILED':
      return '这次没有查找成功'
  }
}
