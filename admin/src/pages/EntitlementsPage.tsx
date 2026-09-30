import {
  Button,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { adminRequest, putJson } from '../api'
import {
  DangerConfirmDialog,
  DetailSection,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  SectionAlert,
} from '../components/AdminUi'
import { formatBytes, formatNumber, planLabel, safeLabel } from '../productLanguage'
import { useAdminSession } from '../session'
import type { QuotaCatalog } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography
type EditableQuota = {
  plan_code: string
  expected_revision: number | null
  storage_bytes?: number
  ai_provider_requests?: number
  ai_input_tokens?: number
  ai_output_tokens?: number
}

const commercialPlans = ['FREE', 'PERSONAL', 'FAMILY', 'PREMIUM']

export function EntitlementsPage() {
  const { session } = useAdminSession()
  const state = useAdminData(
    () => adminRequest<QuotaCatalog>('/settings/quota-catalog'),
    [],
  )
  const [draft, setDraft] = useState<EditableQuota[]>([])
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    if (!state.data) return
    if (state.data.initialized) {
      setDraft(
        state.data.plans.map((row) => ({
          plan_code: row.plan_code,
          expected_revision: row.revision,
          storage_bytes: row.storage_bytes,
          ai_provider_requests: row.ai_provider_requests,
          ai_input_tokens: row.ai_input_tokens,
          ai_output_tokens: row.ai_output_tokens,
        })),
      )
    } else {
      setDraft(
        commercialPlans.map((plan_code) => ({
          plan_code,
          expected_revision: null,
        })),
      )
    }
  }, [state.data])

  const complete = draft.length === 4 && draft.every((row) =>
    [row.storage_bytes, row.ai_provider_requests, row.ai_input_tokens, row.ai_output_tokens]
      .every((value) => typeof value === 'number' && Number.isInteger(value) && value >= 0),
  )

  const update = (plan: string, key: keyof EditableQuota, value: number | null) => {
    setDraft((rows) =>
      rows.map((row) =>
        row.plan_code === plan ? { ...row, [key]: value ?? undefined } : row,
      ),
    )
  }

  const save = async () => {
    if (!complete) return
    setSaving(true)
    setActionError(null)
    try {
      await putJson<QuotaCatalog>('/settings/quota-catalog', {
        plans: draft.map((row) => ({
          plan_code: row.plan_code,
          expected_revision: row.expected_revision,
          storage_bytes: row.storage_bytes,
          ai_provider_requests: row.ai_provider_requests,
          ai_input_tokens: row.ai_input_tokens,
          ai_output_tokens: row.ai_output_tokens,
        })),
        confirmation: '保存额度配置',
      })
      setConfirmOpen(false)
      await state.reload()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '额度配置没有保存')
    } finally {
      setSaving(false)
    }
  }

  const columns = useMemo(
    () => [
      {
        title: '会员方案',
        dataIndex: 'plan_code',
        width: 140,
        render: (value: string) => <Tag>{safeLabel(planLabel, value)}</Tag>,
      },
      {
        title: '存储空间（字节）',
        dataIndex: 'storage_bytes',
        render: (value: number | undefined, row: EditableQuota) =>
          session?.role === 'SUPER_ADMIN' ? (
            <InputNumber
              min={0}
              precision={0}
              value={value}
              onChange={(next) => update(row.plan_code, 'storage_bytes', next)}
              aria-label={`${safeLabel(planLabel, row.plan_code)}存储空间`}
              style={{ width: '100%' }}
            />
          ) : formatBytes(value),
      },
      {
        title: 'AI 请求',
        dataIndex: 'ai_provider_requests',
        render: (value: number | undefined, row: EditableQuota) =>
          session?.role === 'SUPER_ADMIN' ? (
            <InputNumber
              min={0}
              precision={0}
              value={value}
              onChange={(next) => update(row.plan_code, 'ai_provider_requests', next)}
              aria-label={`${safeLabel(planLabel, row.plan_code)}AI 请求额度`}
              style={{ width: '100%' }}
            />
          ) : formatNumber(value),
      },
      {
        title: 'AI 输入计量',
        dataIndex: 'ai_input_tokens',
        render: (value: number | undefined, row: EditableQuota) =>
          session?.role === 'SUPER_ADMIN' ? (
            <InputNumber
              min={0}
              precision={0}
              value={value}
              onChange={(next) => update(row.plan_code, 'ai_input_tokens', next)}
              style={{ width: '100%' }}
              aria-label={`${safeLabel(planLabel, row.plan_code)}AI 输入计量`}
            />
          ) : formatNumber(value),
      },
      {
        title: 'AI 输出计量',
        dataIndex: 'ai_output_tokens',
        render: (value: number | undefined, row: EditableQuota) =>
          session?.role === 'SUPER_ADMIN' ? (
            <InputNumber
              min={0}
              precision={0}
              value={value}
              onChange={(next) => update(row.plan_code, 'ai_output_tokens', next)}
              style={{ width: '100%' }}
              aria-label={`${safeLabel(planLabel, row.plan_code)}AI 输出计量`}
            />
          ) : formatNumber(value),
      },
    ],
    [session?.role, draft],
  )

  return (
    <>
      <PageHeader
        eyebrow="会员与额度"
        title="会员与额度"
        description="商业方案额度由生产数据库统一生效，修改使用版本校验并记录审计。"
        extra={
          session?.role === 'SUPER_ADMIN' ? (
            <Button type="primary" disabled={!complete} onClick={() => setConfirmOpen(true)}>
              保存额度配置
            </Button>
          ) : undefined
        }
      />
      {actionError && <div className="admin-form-error" role="alert">{actionError}</div>}
      <SectionAlert
        type="info"
        message="历史兼容方案保持不限额语义"
        description="该方案只用于迁移兼容，不在这里配置，也不会作为新的商业方案分配。"
      />
      {state.loading && !state.data ? (
        <Loading />
      ) : state.error || !state.data ? (
        <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
      ) : (
        <DetailSection
          title="方案额度目录"
          description={
            state.data.initialized
              ? '当前值已经由生产数据库管理。'
              : '尚未初始化。请明确填写全部四个方案的额度后一次性启用；系统不会代填商业默认值。'
          }
        >
          {draft.length ? (
            <Table<EditableQuota>
              rowKey="plan_code"
              dataSource={draft}
              columns={columns}
              pagination={false}
              scroll={{ x: 'max-content' }}
            />
          ) : (
            <EmptyState title="尚未配置会员额度" />
          )}
        </DetailSection>
      )}
      <DangerConfirmDialog
        open={confirmOpen}
        title="保存会员额度配置"
        impact={
          <Space direction="vertical">
            <Text>保存后，这组额度会立即成为商业会员方案的运行时权威配置。</Text>
            <Text>系统会再次验证当前管理员权限和每个方案的状态版本。</Text>
          </Space>
        }
        phrase="保存额度配置"
        confirmText="保存并生效"
        loading={saving}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => void save()}
      />
    </>
  )
}
