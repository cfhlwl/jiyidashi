import {
  Alert,
  Button,
  Checkbox,
  Col,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useState } from 'react'
import { adminRequest, postJson, putJson } from '../api'
import {
  DescriptionList,
  DetailSection,
  ErrorState,
  Loading,
  PageHeader,
  SecretConfiguredState,
  StatusCard,
} from '../components/AdminUi'
import { formatDateTime, formatNumber } from '../productLanguage'
import {
  canMutateProviderConfiguration,
  providerDraftFromConfig,
  providerWritePayload,
  type ProviderDraft,
} from '../providerConfig'
import { useAdminSession } from '../session'
import type {
  EmbeddingBackfill,
  HealthPayload,
  ProviderConfig,
  ProviderConfigList,
  ProviderService,
} from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

const stateCopy: Record<ProviderConfig['state'], string> = {
  DISABLED: '未启用',
  CONFIGURED_UNVERIFIED: '已配置 / 未启用',
  ENABLED_UNVERIFIED: '已启用 / 待运行验证',
  NORMAL: '正常',
  WARNING: '需要关注',
}

function statusTone(
  state: ProviderConfig['state'],
): 'success' | 'warning' | 'info' | 'default' {
  if (state === 'NORMAL') return 'success'
  if (state === 'WARNING') return 'warning'
  if (state === 'ENABLED_UNVERIFIED') return 'info'
  return 'default'
}

function serviceHelp(service: ProviderService) {
  if (service === 'AI') {
    return '当前适配器使用 OpenAI Responses API：POST <Base URL>/responses。保存配置不会自动调用模型。'
  }
  if (service === 'ASR') {
    return '当前转写适配器要求 /audio/transcriptions 返回 logprobs，最低可信度由服务端门禁。'
  }
  return '这里只管理语义向量检索。日期、地点、足迹等结构化检索不依赖 Embedding。模型与 1536 维策略保持锁定。'
}

function ProviderEditor({
  config,
  readOnly,
  onSaved,
}: {
  config: ProviderConfig
  readOnly: boolean
  onSaved: () => Promise<void>
}) {
  const [draft, setDraft] = useState<ProviderDraft>(() => providerDraftFromConfig(config))
  const [newKey, setNewKey] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setDraft(providerDraftFromConfig(config))
    setNewKey('')
    setClearKey(false)
  }, [config])

  const set = <K extends keyof ProviderDraft>(key: K, value: ProviderDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }))
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    setResult(null)
    try {
      const payload = providerWritePayload(config, draft, newKey, clearKey)
      await putJson<ProviderConfig>(
        '/settings/providers/' + config.service.toLowerCase(),
        payload,
      )
      setNewKey('')
      setClearKey(false)
      setResult('配置已保存。新配置将在运行时缓存窗口内被所有服务进程读取。')
      await onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : '配置没有保存')
    } finally {
      setSaving(false)
    }
  }

  const embedding = config.service === 'EMBEDDING'
  return (
    <DetailSection
      title={config.label}
      description={serviceHelp(config.service)}
      extra={
        <Space>
          <Tag>{stateCopy[config.state]}</Tag>
          <SecretConfiguredState configured={config.configured} />
        </Space>
      }
    >
      {error && <Alert type="error" showIcon message={error} className="provider-alert" />}
      {result && <Alert type="success" showIcon message={result} className="provider-alert" />}
      {readOnly && (
        <Alert
          type="info"
          showIcon
          message="当前账号为只读"
          description="只有超级管理员可以修改服务配置。"
          className="provider-alert"
        />
      )}
      <div className="provider-config-grid">
        <label className="provider-field provider-toggle">
          <span>启用服务</span>
          <Switch
            checked={draft.enabled}
            disabled={readOnly}
            onChange={(value) => {
              set('enabled', value)
              if (value) setClearKey(false)
            }}
          />
        </label>

        <label className="provider-field">
          <span>服务类型</span>
          <Select
            value={draft.provider_type}
            disabled={readOnly}
            onChange={(value) => set('provider_type', value)}
            options={[{ value: 'openai', label: 'OpenAI API contract' }]}
          />
        </label>

        <label className="provider-field provider-field-wide">
          <span>服务地址</span>
          <Input
            value={draft.base_url}
            disabled={readOnly}
            onChange={(event) => set('base_url', event.target.value)}
            placeholder="https://api.openai.com/v1"
          />
        </label>

        <label className="provider-field">
          <span>模型</span>
          <Input
            value={draft.model}
            disabled={readOnly || embedding}
            onChange={(event) => set('model', event.target.value)}
          />
        </label>

        <label className="provider-field">
          <span>请求超时（秒）</span>
          <InputNumber
            min={1}
            max={120}
            value={draft.timeout_seconds}
            disabled={readOnly}
            onChange={(value) => set('timeout_seconds', Number(value ?? 30))}
          />
        </label>

        {config.service === 'AI' && (
          <>
            <label className="provider-field">
              <span>单次输入上限（字符）</span>
              <InputNumber
                min={1}
                max={1000000}
                value={draft.max_input_chars}
                disabled={readOnly}
                onChange={(value) => set('max_input_chars', value === null ? null : Number(value))}
              />
            </label>
            <label className="provider-field">
              <span>单次输出上限（tokens）</span>
              <InputNumber
                min={1}
                max={65536}
                value={draft.max_output_tokens}
                disabled={readOnly}
                onChange={(value) => set('max_output_tokens', value === null ? null : Number(value))}
              />
            </label>
          </>
        )}

        {config.service === 'ASR' && (
          <label className="provider-field">
            <span>最低识别可信度</span>
            <InputNumber
              min={0}
              max={1}
              step={0.05}
              value={draft.min_confidence}
              disabled={readOnly}
              onChange={(value) => set('min_confidence', value === null ? null : Number(value))}
            />
          </label>
        )}

        {embedding && (
          <>
            <label className="provider-field">
              <span>向量维度（策略锁定）</span>
              <Input value={String(config.dimensions ?? 1536)} disabled />
            </label>
            <label className="provider-field">
              <span>单次输入上限（策略锁定）</span>
              <Input value={String(draft.max_input_chars ?? 12000)} disabled />
            </label>
          </>
        )}

        <label className="provider-field provider-field-wide">
          <span>新的 API Key（留空即保留现有凭证）</span>
          <Input.Password
            value={newKey}
            disabled={readOnly || clearKey}
            autoComplete="new-password"
            placeholder={config.configured ? '已配置；如需轮换请输入新 Key' : '未配置'}
            onChange={(event) => setNewKey(event.target.value)}
          />
        </label>

        {!readOnly && (
          <label className="provider-field provider-field-wide provider-clear-secret">
            <Checkbox
              checked={clearKey}
              disabled={draft.enabled}
              onChange={(event) => {
                setClearKey(event.target.checked)
                if (event.target.checked) setNewKey('')
              }}
            >
              明确清除已保存的服务凭证（仅在服务关闭时允许）
            </Checkbox>
          </label>
        )}
      </div>

      <DescriptionList
        columns={3}
        items={[
          { label: '配置来源', value: config.source === 'DATABASE' ? '在线配置' : '服务器启动配置' },
          { label: '配置版本', value: config.revision === null ? '启动配置' : String(config.revision) },
          { label: '更新时间', value: formatDateTime(config.updated_at) },
        ]}
      />

      {!readOnly && (
        <div className="provider-actions">
          <Button type="primary" loading={saving} onClick={() => void save()}>
            保存配置
          </Button>
          <Text type="secondary">保存不会发送测试提示词、录音或用户记忆到服务商。</Text>
        </div>
      )}
    </DetailSection>
  )
}

export function AiServicesPage() {
  const { session } = useAdminSession()
  const providers = useAdminData(
    () => adminRequest<ProviderConfigList>('/settings/providers'),
    [],
  )
  const health = useAdminData(
    () => adminRequest<HealthPayload>('/system/health'),
    [],
  )
  const backfill = useAdminData(
    () => adminRequest<EmbeddingBackfill>('/settings/providers/embedding/backfill'),
    [],
  )
  const [backfillBusy, setBackfillBusy] = useState(false)
  const [backfillError, setBackfillError] = useState<string | null>(null)
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null)

  const loading =
    (providers.loading && !providers.data) ||
    (health.loading && !health.data) ||
    (backfill.loading && !backfill.data)
  if (loading) return <Loading />

  if (
    providers.error ||
    health.error ||
    backfill.error ||
    !providers.data ||
    !health.data ||
    !backfill.data
  ) {
    return (
      <ErrorState
        message={providers.error ?? health.error ?? backfill.error ?? undefined}
        onRetry={() => {
          void providers.reload()
          void health.reload()
          void backfill.reload()
        }}
      />
    )
  }

  const readOnly = !canMutateProviderConfiguration(session?.role)
  const embedding = providers.data.services.find((item) => item.service === 'EMBEDDING')
  const refresh = async () => {
    await Promise.all([providers.reload(), health.reload(), backfill.reload()])
  }

  const runBackfill = async () => {
    if (!embedding) return
    setBackfillBusy(true)
    setBackfillError(null)
    setBackfillMessage(null)
    try {
      const result = await postJson<EmbeddingBackfill>(
        '/settings/providers/embedding/backfill',
        {
          expected_provider_revision: embedding.revision,
          batch_size: 20,
        },
      )
      if (result.last_error === 'PROVIDER_REVISION_CHANGED') {
        setBackfillError('服务配置已变化，本批已安全停止；请按当前配置重新继续。')
      } else if (result.last_error) {
        setBackfillError('本批处理提前停止，请检查服务状态后重试。')
      } else {
        setBackfillMessage(
          result.processed === 0
            ? '当前没有需要补齐的记忆向量。'
            : `本批处理 ${result.processed} 条，更新 ${result.refreshed} 条。`,
        )
      }
      await refresh()
    } catch (err) {
      setBackfillError(err instanceof Error ? err.message : '回填没有完成')
    } finally {
      setBackfillBusy(false)
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="基础服务"
        title="AI 与语义服务"
        description="配置 AI 整理、语音识别与语义记忆检索。打开页面或保存配置都不会自动调用付费模型服务。"
      />

      <Row gutter={[16, 16]} className="admin-summary-row">
        {providers.data.services.map((item) => (
          <Col xs={24} md={8} key={item.service}>
            <StatusCard
              title={item.label}
              status={statusTone(item.state)}
              detail={stateCopy[item.state]}
            />
          </Col>
        ))}
      </Row>

      <DetailSection
        title="本月 AI 聚合用量"
        description="仅展示现有配额账本的全站聚合数字，不读取用户提示词、回答、录音或记忆正文。"
      >
        <DescriptionList
          columns={3}
          items={[
            { label: 'AI 请求', value: formatNumber(health.data.ai_requests_current_month) },
            { label: '输入计量', value: formatNumber(health.data.ai_input_tokens_current_month) },
            { label: '输出计量', value: formatNumber(health.data.ai_output_tokens_current_month) },
          ]}
        />
      </DetailSection>

      <div className="admin-section-stack">
        {providers.data.services.map((item) => (
          <ProviderEditor
            key={item.service}
            config={item}
            readOnly={readOnly}
            onSaved={refresh}
          />
        ))}
      </div>

      <DetailSection
        title="语义记忆检索回填"
        description="只处理当前缺失或过期的派生向量。每次最多处理 20 条；启用 Embedding 本身不会自动扫描全部历史记忆。"
      >
        {backfillError && <Alert type="error" showIcon message={backfillError} className="provider-alert" />}
        {backfillMessage && <Alert type="success" showIcon message={backfillMessage} className="provider-alert" />}
        <DescriptionList
          columns={3}
          items={[
            {
              label: '向量数据库',
              value: backfill.data.vector_database_capable ? '可用' : '不可用',
            },
            { label: '模型策略', value: backfill.data.policy_model },
            { label: '向量维度', value: String(backfill.data.policy_dimensions) },
            { label: '可生成记忆', value: formatNumber(backfill.data.eligible_memories) },
            { label: '已有向量', value: formatNumber(backfill.data.vector_rows) },
            { label: '待补齐', value: formatNumber(backfill.data.remaining_memories) },
          ]}
        />
        {!readOnly && (
          <div className="provider-actions">
            <Button
              type="primary"
              loading={backfillBusy}
              disabled={
                !embedding?.enabled ||
                !backfill.data.vector_database_capable ||
                backfill.data.remaining_memories === 0
              }
              onClick={() => void runBackfill()}
            >
              处理下一批（最多 20 条）
            </Button>
            <Text type="secondary">
              服务暂时失败不会修改原始记忆；可以稍后继续处理，直到“待补齐”为 0。
            </Text>
          </div>
        )}
      </DetailSection>
    </>
  )
}
