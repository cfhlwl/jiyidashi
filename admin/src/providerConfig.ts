import type {
  AdminRole,
  ProviderConfig,
} from './types'

export type ProviderDraft = {
  enabled: boolean
  provider_type: string
  base_url: string
  model: string
  timeout_seconds: number
  max_input_chars: number | null
  max_output_tokens: number | null
  min_confidence: number | null
}

export function canMutateProviderConfiguration(role: AdminRole | null | undefined) {
  return role === 'SUPER_ADMIN'
}

export function providerDraftFromConfig(config: ProviderConfig): ProviderDraft {
  return {
    enabled: config.enabled,
    provider_type: config.provider_type,
    base_url: config.base_url,
    model: config.model,
    timeout_seconds: config.timeout_seconds,
    max_input_chars: config.max_input_chars,
    max_output_tokens: config.max_output_tokens,
    min_confidence: config.min_confidence,
  }
}

export function providerWritePayload(
  config: ProviderConfig,
  draft: ProviderDraft,
  newKey: string,
  clearKey: boolean,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    expected_revision: config.revision,
    ...draft,
    clear_api_key: clearKey,
  }
  const secret = newKey.trim()
  if (secret) payload.api_key = secret
  return payload
}
