import { describe, expect, it } from 'vitest'
import { fixtureProviders } from '../src/fixtures'
import {
  canMutateProviderConfiguration,
  providerDraftFromConfig,
  providerWritePayload,
} from '../src/providerConfig'

describe('ADMIN-002 provider form policy', () => {
  it('allows provider mutation only for SUPER_ADMIN', () => {
    expect(canMutateProviderConfiguration('SUPER_ADMIN')).toBe(true)
    expect(canMutateProviderConfiguration('OPERATOR')).toBe(false)
    expect(canMutateProviderConfiguration('SUPPORT_READONLY')).toBe(false)
    expect(canMutateProviderConfiguration(null)).toBe(false)
  })

  it('preserves the stored secret when the password input stays empty', () => {
    const config = fixtureProviders.services[0]
    const payload = providerWritePayload(
      config,
      providerDraftFromConfig(config),
      '   ',
      false,
    )
    expect(payload.expected_revision).toBe(config.revision)
    expect(payload.clear_api_key).toBe(false)
    expect(payload).not.toHaveProperty('api_key')
  })

  it('sends only an explicitly entered replacement secret', () => {
    const config = fixtureProviders.services[0]
    const payload = providerWritePayload(
      config,
      providerDraftFromConfig(config),
      '  sk-new-key  ',
      false,
    )
    expect(payload.api_key).toBe('sk-new-key')
  })

  it('uses an explicit clear flag rather than an empty-string secret', () => {
    const config = fixtureProviders.services[2]
    const draft = { ...providerDraftFromConfig(config), enabled: false }
    const payload = providerWritePayload(config, draft, '', true)
    expect(payload.clear_api_key).toBe(true)
    expect(payload).not.toHaveProperty('api_key')
  })
})
