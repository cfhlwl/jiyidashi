import { Button, Select, Typography, type TableColumnsType } from 'antd'
import { useMemo, useState } from 'react'
import { adminRequest, postJson } from '../api'
import {
  ConfirmDialog,
  DataTable,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  StatusBadge,
} from '../components/AdminUi'
import {
  deliveryStatusLabel,
  formatDateTime,
  safeLabel,
  securityCategoryLabel,
  securitySeverityLabel,
} from '../productLanguage'
import { useAdminSession } from '../session'
import type { SecurityAlert } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography
type AlertPage = { items: SecurityAlert[]; next_cursor?: string | null }

export function SecurityCenterPage() {
  const { session } = useAdminSession()
  const [severity, setSeverity] = useState<string | undefined>()
  const [category, setCategory] = useState<string | undefined>()
  const [deliveryStatus, setDeliveryStatus] = useState<string | undefined>()
  const [cursor, setCursor] = useState<string | null>(null)

  const path = useMemo(() => {
    const query = new URLSearchParams()
    if (severity) query.set('severity', severity)
    if (category) query.set('category', category)
    if (deliveryStatus) query.set('delivery_status', deliveryStatus)
    if (cursor) query.set('cursor', cursor)
    return '/security/alerts' + (query.size ? '?' + query.toString() : '')
  }, [severity, category, deliveryStatus, cursor])

  const state = useAdminData(
    () => adminRequest<AlertPage>(path),
    [path],
  )
  const [selected, setSelected] = useState<SecurityAlert | null>(null)
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const changeFilter = (setter: (value: string | undefined) => void, value: string | undefined) => {
    setCursor(null)
    setter(value)
  }

  const retry = async () => {
    if (!selected) return
    setSaving(true)
    setActionError(null)
    try {
      await postJson('/security/alerts/' + selected.id + '/retry')
      setSelected(null)
      await state.reload()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '本次没有完成发送')
    } finally {
      setSaving(false)
    }
  }

  const columns: TableColumnsType<SecurityAlert> = [
    {
      title: '级别',
      dataIndex: 'severity',
      width: 100,
      render: (value: string) => (
        <StatusBadge
          status={value === 'CRITICAL' || value === 'HIGH' ? 'error' : value === 'MEDIUM' ? 'warning' : 'info'}
          label={safeLabel(securitySeverityLabel, value)}
        />
      ),
    },
    {
      title: '类别',
      dataIndex: 'category',
      width: 160,
      render: (value: string) => safeLabel(securityCategoryLabel, value, '系统安全'),
    },
    {
      title: '事件',
      dataIndex: 'safe_message',
      width: 300,
    },
    {
      title: '出现次数',
      dataIndex: 'signal_count',
      width: 100,
      align: 'right',
    },
    {
      title: '通知状态',
      dataIndex: 'delivery_status',
      width: 140,
      render: (value: string) => safeLabel(deliveryStatusLabel, value),
    },
    {
      title: '最近出现',
      dataIndex: 'latest_seen_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      fixed: 'right',
      render: (_, row) => {
        const retryable =
          row.delivery_status === 'PENDING' ||
          row.delivery_status === 'RETRYABLE_FAILURE'
        return retryable && session?.role !== 'SUPPORT_READONLY' ? (
          <Button size="small" onClick={() => setSelected(row)}>
            重新发送
          </Button>
        ) : (
          <Text type="secondary">—</Text>
        )
      },
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="安全与运营"
        title="安全中心"
        description="汇总现有安全告警的运营信息；只展示有界上下文，不暴露原始敏感输入。"
      />
      <FilterBar>
        <Select
          allowClear
          placeholder="全部级别"
          value={severity}
          onChange={(value) => changeFilter(setSeverity, value)}
          options={Object.entries(securitySeverityLabel).map(([value, label]) => ({ value, label }))}
          style={{ minWidth: 140 }}
          aria-label="按安全级别筛选"
        />
        <Select
          allowClear
          placeholder="全部类别"
          value={category}
          onChange={(value) => changeFilter(setCategory, value)}
          options={Object.entries(securityCategoryLabel).map(([value, label]) => ({ value, label }))}
          style={{ minWidth: 180 }}
          aria-label="按安全类别筛选"
        />
        <Select
          allowClear
          placeholder="全部通知状态"
          value={deliveryStatus}
          onChange={(value) => changeFilter(setDeliveryStatus, value)}
          options={Object.entries(deliveryStatusLabel).map(([value, label]) => ({ value, label }))}
          style={{ minWidth: 170 }}
          aria-label="按通知状态筛选"
        />
        <Button onClick={() => void state.reload()}>刷新</Button>
      </FilterBar>
      {actionError && <div className="admin-form-error" role="alert">{actionError}</div>}
      {state.loading && !state.data ? (
        <Loading />
      ) : state.error || !state.data ? (
        <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
      ) : (
        <>
          <DataTable
            rowKey="id"
            columns={columns}
            dataSource={state.data.items}
            emptyText="暂无安全事件"
          />
          <div className="admin-pagination">
            <Button
              disabled={!state.data.next_cursor}
              onClick={() => {
                if (state.data?.next_cursor) setCursor(state.data.next_cursor)
              }}
            >
              下一页
            </Button>
          </div>
        </>
      )}
      <ConfirmDialog
        open={Boolean(selected)}
        title="重新发送安全通知"
        description="系统会调用现有安全通知投递逻辑，并继续遵守既有重试次数和等待策略。"
        confirmText="重新发送"
        loading={saving}
        onCancel={() => setSelected(null)}
        onConfirm={() => void retry()}
      />
    </>
  )
}
