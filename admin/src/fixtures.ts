import type {
  AccountDeletionTask,
  AdminAccount,
  AdminSession,
  AuditEvent,
  Dashboard,
  DeletionTask,
  FamilyDetail,
  FamilyPage,
  HealthPayload,
  QuotaCatalog,
  SecurityAlert,
  SettingsPayload,
  UserDetail,
  UserPage,
} from './types'

const now = '2026-09-30T08:00:00Z'
const userA = '11111111-1111-4111-8111-111111111111'
const userB = '22222222-2222-4222-8222-222222222222'
const familyId = '33333333-3333-4333-8333-333333333333'

export const fixtureSession: AdminSession = {
  admin_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  email: 'admin@example.com',
  display_name: '生产运营管理员',
  role: 'SUPER_ADMIN',
  expires_at: '2026-09-30T08:30:00Z',
}

export const fixtureDashboard: Dashboard = {
  overview: {
    registered_users: 12842,
    new_users_today: 126,
    active_users_today: 3894,
    memories_created_today: 6821,
    successful_retrievals_today: 4217,
    active_account_deletions: 2,
    pending_data_deletions: 7,
    security_alerts_needing_attention: 3,
  },
  services: [
    { key: 'core', label: '核心服务', status: 'NORMAL', detail: '服务运行正常' },
    { key: 'database', label: '数据库', status: 'NORMAL', detail: '数据库连接正常' },
    { key: 'storage', label: '文件存储', status: 'NORMAL', detail: '私有存储已配置' },
    { key: 'ai', label: 'AI 整理', status: 'NORMAL', detail: '服务配置完整' },
    { key: 'asr', label: '语音识别', status: 'NORMAL', detail: '服务配置完整' },
    { key: 'embedding', label: '记忆检索', status: 'NORMAL', detail: '服务配置完整' },
  ],
  trend: [
    { day: '2026-09-24', active_users: 3120, successful_retrievals: 3510 },
    { day: '2026-09-25', active_users: 3274, successful_retrievals: 3662 },
    { day: '2026-09-26', active_users: 3188, successful_retrievals: 3591 },
    { day: '2026-09-27', active_users: 3420, successful_retrievals: 3812 },
    { day: '2026-09-28', active_users: 3561, successful_retrievals: 3950 },
    { day: '2026-09-29', active_users: 3712, successful_retrievals: 4088 },
    { day: '2026-09-30', active_users: 3894, successful_retrievals: 4217 },
  ],
}

export const fixtureUsers: UserPage = {
  items: [
    {
      id: userA,
      display_name: '林先生',
      email: 'lin@example.com',
      created_at: '2026-09-12T04:20:00Z',
      last_active_at: '2026-09-30T07:42:00Z',
      device_count: 3,
      plan_code: 'PREMIUM',
      family_role: 'OWNER',
      storage_used_bytes: 2483021234,
      account_deletion_in_progress: false,
      data_deletion_in_progress: false,
    },
    {
      id: userB,
      display_name: '周女士',
      email: 'zhou@example.com',
      created_at: '2026-09-18T11:30:00Z',
      last_active_at: '2026-09-29T21:12:00Z',
      device_count: 2,
      plan_code: 'FAMILY',
      family_role: 'MEMBER',
      storage_used_bytes: 984023122,
      account_deletion_in_progress: false,
      data_deletion_in_progress: true,
    },
  ],
  next_cursor: null,
}

export const fixtureUserDetail: UserDetail = {
  user: fixtureUsers.items[0],
  entitlement: {
    plan_code: 'PREMIUM',
    revision: 4,
    effective_at: '2026-09-20T00:00:00Z',
    expires_at: '2027-09-20T00:00:00Z',
    storage_used_bytes: 2483021234,
    storage_limit_bytes: 107374182400,
    ai_requests_used: 384,
    ai_requests_limit: 5000,
  },
  family_id: familyId,
  data_deletion_status: null,
  account_deletion_started_at: null,
}

export const fixtureFamilies: FamilyPage = {
  items: [
    {
      id: familyId,
      owner_user_id: userA,
      owner_display_name: '林先生',
      owner_email: 'lin@example.com',
      member_count: 4,
      grant_count: 9,
      created_at: '2026-09-20T04:00:00Z',
    },
  ],
  next_cursor: null,
}

export const fixtureFamilyDetail: FamilyDetail = {
  family: fixtureFamilies.items[0],
  members: [
    { user_id: userA, display_name: '林先生', email: 'lin@example.com', role: 'OWNER', joined_at: now },
    { user_id: userB, display_name: '周女士', email: 'zhou@example.com', role: 'MEMBER', joined_at: now },
  ],
  grants: [
    { permission_code: 'VIEW_MEMORY', grant_count: 3 },
    { permission_code: 'VIEW_PHOTOS', grant_count: 2 },
    { permission_code: 'VIEW_FOOTPRINT', grant_count: 2 },
    { permission_code: 'VIEW_CURRENT_LOCATION', grant_count: 2 },
  ],
}

export const fixtureDeletionTasks: { items: DeletionTask[]; next_cursor: null } = {
  items: [
    {
      id: '44444444-4444-4444-8444-444444444444',
      user_id: userB,
      user_display_name: '周女士',
      user_email: 'zhou@example.com',
      status: 'WAITING_STORAGE_QUIET',
      created_at: '2026-09-30T06:20:00Z',
      updated_at: '2026-09-30T07:52:00Z',
      completed_at: null,
      storage_wait_until: '2026-09-30T08:05:00Z',
      retryable: false,
      safe_message: '正在确认文件清理完成',
      deleted_counts: { memories: 182, media: 47 },
    },
  ],
  next_cursor: null,
}

export const fixtureAccountTasks: { items: AccountDeletionTask[]; next_cursor: null } = {
  items: [
    {
      id: '55555555-5555-4555-8555-555555555555',
      user_id: '66666666-6666-4666-8666-666666666666',
      user_display_name: '陈先生',
      user_email: 'chen@example.com',
      created_at: '2026-09-30T07:11:00Z',
      updated_at: '2026-09-30T07:44:00Z',
      safe_phase: 'IN_PROGRESS',
      safe_message: '账号注销正在处理中；完成后不会保留可关联用户身份的永久注销记录',
    },
  ],
  next_cursor: null,
}

export const fixtureAlerts: { items: SecurityAlert[]; next_cursor: null } = {
  items: [
    {
      id: '77777777-7777-4777-8777-777777777777',
      severity: 'HIGH',
      category: 'LOGIN_PROTECTION',
      delivery_status: 'RETRYABLE_FAILURE',
      signal_count: 18,
      first_seen_at: '2026-09-30T07:02:00Z',
      latest_seen_at: '2026-09-30T07:48:00Z',
      next_retry_at: '2026-09-30T08:05:00Z',
      safe_message: '登录保护检测到异常访问',
    },
  ],
  next_cursor: null,
}

export const fixtureSettings: SettingsPayload = {
  sections: [
    {
      key: 'ai',
      title: 'AI 服务',
      items: [
        { key: 'ai_enabled', label: 'AI 整理服务', classification: '需要重新部署', value: true },
        { key: 'ai_model', label: '当前模型', classification: '需要重新部署', value: 'gpt-5-mini' },
        { key: 'ai_credential', label: '访问凭证', classification: '敏感配置', value: null, configured: true, help_text: '配置来源：服务器安全配置' },
      ],
    },
    {
      key: 'storage',
      title: '文件存储',
      items: [
        { key: 'storage_backend', label: '存储服务', classification: '需要重新部署', value: '已启用' },
        { key: 'storage_region', label: '区域', classification: '只读', value: 'ap-beijing' },
        { key: 'storage_credential', label: '访问凭证', classification: '敏感配置', value: null, configured: true, help_text: '配置来源：服务器安全配置' },
      ],
    },
  ],
}

export const fixtureHealth: HealthPayload = {
  environment: 'production',
  api_status: '正常',
  database_status: '正常',
  database_schema_status: '正常',
  database_schema_version: '0028_admin_console',
  storage_status: '正常',
  storage_alerts_needing_attention: 2,
  ai_status: '正常',
  asr_status: '正常',
  embedding_status: '正常',
  ai_requests_current_month: 18420,
  ai_input_tokens_current_month: 48203100,
  ai_output_tokens_current_month: 9348200,
  app_version: '1.0.0',
  git_sha: 'abcdef123456',
  build_time: '2026-09-30T07:00:00Z',
  total_storage_used_bytes: 42949672960,
}

export const fixtureQuota: QuotaCatalog = {
  initialized: true,
  plans: ['FREE', 'PERSONAL', 'FAMILY', 'PREMIUM'].map((plan_code, index) => ({
    plan_code,
    revision: 3,
    storage_bytes: [1073741824, 21474836480, 53687091200, 107374182400][index],
    ai_provider_requests: [50, 1000, 2500, 5000][index],
    ai_input_tokens: [200000, 4000000, 10000000, 20000000][index],
    ai_output_tokens: [50000, 1000000, 2500000, 5000000][index],
    updated_at: now,
  })),
}

export const fixtureAdmins: AdminAccount[] = [
  {
    id: fixtureSession.admin_id,
    email: fixtureSession.email,
    display_name: fixtureSession.display_name,
    role: 'SUPER_ADMIN',
    disabled: false,
    revision: 5,
    last_login_at: now,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: now,
  },
  {
    id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    email: 'support@example.com',
    display_name: '客户支持',
    role: 'SUPPORT_READONLY',
    disabled: false,
    revision: 1,
    last_login_at: '2026-09-30T06:00:00Z',
    created_at: '2026-09-10T00:00:00Z',
    updated_at: now,
  },
]

export const fixtureAudit: { items: AuditEvent[]; next_cursor: null } = {
  items: [
    {
      id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
      actor: '生产运营管理员',
      role: 'SUPER_ADMIN',
      action: 'ENTITLEMENT_QUOTA_CATALOG_UPDATE',
      target_type: 'RUNTIME_POLICY',
      target: 'entitlement-quota',
      result: 'SUCCESS',
      request_ref: '任务-20260930-001',
      metadata: {},
      created_at: now,
    },
  ],
  next_cursor: null,
}
