export type ProfileAuthState = {
  owner: string | null
  epoch: number
  sessionId: string | null
}

export type ProfileAsyncOperation = ProfileAuthState & {
  generation: number
}

export function beginProfileAsyncOperation(
  generation: { current: number },
  state: ProfileAuthState,
): ProfileAsyncOperation {
  generation.current += 1
  return { ...state, generation: generation.current }
}

export function isProfileAsyncOperationCurrent(
  operation: ProfileAsyncOperation,
  currentGeneration: number,
  currentState: ProfileAuthState,
): boolean {
  return operation.generation === currentGeneration
    && operation.owner === currentState.owner
    && operation.epoch === currentState.epoch
    && operation.sessionId === currentState.sessionId
}
