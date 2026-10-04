export type AdminRole = 'SUPER_ADMIN' | 'OPERATOR' | 'SUPPORT_READONLY'

export type AdminSession = {
  admin_id: string
  email: string
  display_name: string
  role: AdminRole
  expires_at: string
}

export type Dashboard = {
  overview: {
    registered_users: number
    new_users_today: number
    active_users_today: number
    memories_created_today: number
    successful_retrievals_today: number
    active_account_deletions: number
    pending_data_deletions: number
    security_alerts_needing_attention: number
  }
  services: Array<{ key: string; label: string; status: string; detail: string }>
  trend: Array<{ day: string; active_users: number; successful_retrievals: number }>
}

export type UserListItem = {
  id: string
  display_name: string
  email: string | null
  created_at: string
  last_active_at: string | null
  device_count: number
  plan_code: string
  family_role: string | null
  storage_used_bytes: number
  account_deletion_in_progress: boolean
  data_deletion_in_progress: boolean
}

export type UserPage = { items: UserListItem[]; next_cursor?: string | null }

export type UserDetail = {
  user: UserListItem
  entitlement: {
    plan_code: string
    revision: number
    effective_at: string
    expires_at: string | null
    storage_used_bytes: number
    storage_limit_bytes: number | null
    ai_requests_used: number
    ai_requests_limit: number | null
  }
  family_id: string | null
  data_deletion_status: string | null
  account_deletion_started_at: string | null
}

export type FamilyListItem = {
  id: string
  owner_user_id: string
  owner_display_name: string
  owner_email: string | null
  member_count: number
  grant_count: number
  created_at: string
}

export type FamilyPage = { items: FamilyListItem[]; next_cursor?: string | null }

export type FamilyDetail = {
  family: FamilyListItem
  members: Array<{
    user_id: string
    display_name: string
    email: string | null
    role: string
    joined_at: string
  }>
  grants: Array<{ permission_code: string; grant_count: number }>
}

export type DeletionTask = {
  id: string
  user_id: string
  user_display_name: string
  user_email: string | null
  status: string
  created_at: string
  updated_at: string
  completed_at: string | null
  storage_wait_until: string | null
  retryable: boolean
  safe_message: string
  deleted_counts: Record<string, number>
}

export type AccountDeletionTask = {
  id: string
  user_id: string
  user_display_name: string
  user_email: string | null
  created_at: string
  updated_at: string
  safe_phase: string
  safe_message: string
}

export type SecurityAlert = {
  id: string
  severity: string
  category: string
  delivery_status: string
  signal_count: number
  first_seen_at: string
  latest_seen_at: string
  next_retry_at: string | null
  safe_message: string
}

export type ProviderService = 'AI' | 'ASR' | 'EMBEDDING'

export type ProviderConfig = {
  service: ProviderService
  label: string
  state: 'DISABLED' | 'CONFIGURED_UNVERIFIED' | 'ENABLED_UNVERIFIED' | 'NORMAL' | 'WARNING'
  enabled: boolean
  provider_type: string
  base_url: string
  endpoint_host: string
  model: string
  timeout_seconds: number
  max_input_chars: number | null
  max_output_tokens: number | null
  min_confidence: number | null
  configured: boolean
  revision: number | null
  updated_at: string | null
  source: 'BOOTSTRAP' | 'DATABASE'
  dimensions: number | null
}

export type ProviderConfigList = {
  services: ProviderConfig[]
}

export type EmbeddingBackfill = {
  vector_database_capable: boolean
  policy_model: string
  policy_dimensions: number
  eligible_memories: number
  vector_rows: number
  remaining_memories: number
  batch_size: number | null
  processed: number
  refreshed: number
  failed: number
  last_error: string | null
}

export type SettingItem = {
  key: string
  label: string
  classification: string
  value: string | number | boolean | null
  configured?: boolean | null
  help_text?: string | null
}

export type SettingsPayload = {
  sections: Array<{ key: string; title: string; items: SettingItem[] }>
}

export type HealthPayload = {
  environment: string
  api_status: string
  database_status: string
  database_schema_status: string
  database_schema_version: string | null
  storage_status: string
  storage_alerts_needing_attention: number
  ai_status: string
  asr_status: string
  embedding_status: string
  ai_requests_current_month: number
  ai_input_tokens_current_month: number
  ai_output_tokens_current_month: number
  app_version: string
  git_sha: string | null
  build_time: string | null
  total_storage_used_bytes: number
}

export type QuotaCatalog = {
  initialized: boolean
  plans: Array<{
    plan_code: string
    revision: number
    storage_bytes: number
    ai_provider_requests: number
    ai_input_tokens: number
    ai_output_tokens: number
    updated_at: string
  }>
}

export type AdminAccount = {
  id: string
  email: string
  display_name: string
  role: AdminRole
  disabled: boolean
  revision: number
  last_login_at: string | null
  created_at: string
  updated_at: string
}

export type AuditEvent = {
  id: string
  actor: string
  role: string
  action: string
  target_type: string
  target: string | null
  result: string
  request_ref: string | null
  metadata: Record<string, unknown>
  created_at: string
}
