import { Button, Select, Typography, type TableColumnsType } from 'antd'
import { useMemo, useState } from 'react'
import { adminRequest } from '../api'
import {
  DataTable,
  ErrorState,
  FilterBar,
  Loading,
  PageHeader,
  SearchField,
  StatusBadge,
} from '../components/AdminUi'
import {
  auditActionLabel,
  auditTargetLabel,
  formatDateTime,
  roleLabel,
  safeLabel,
} from '../productLanguage'
import type { AdminRole, AuditEvent } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography
type AuditPagePayload = { items: AuditEvent[]; next_cursor?: string | null }

export function AuditPage() {
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [action, setAction] = useState<string | undefined>()
  const [cursor, setCursor] = useState<string | null>(null)

  const path = useMemo(() => {
    const query = new URLSearchParams()
    if (search) query.set('search', search)
    if (action) query.set('action', action)
    if (cursor) query.set('cursor', cursor)
    return '/audit' + (query.size ? '?' + query.toString() : '')
  }, [search, action, cursor])

  const state = useAdminData(
    () => adminRequest<AuditPagePayload>(path),
    [path],
  )

  const columns: TableColumnsType<AuditEvent> = [
    {
      title: '操作人',
      key: 'actor',
      width: 220,
      render: (_, row) => (
        <div className="table-primary">
          <Text strong>{row.actor}</Text>
          <Text type="secondary">
            {safeLabel(roleLabel, row.role as AdminRole, '历史职责')}
          </Text>
        </div>
      ),
    },
    {
      title: '操作',
      dataIndex: 'action',
      width: 190,
      render: (value: string) => safeLabel(auditActionLabel, value, '管理操作'),
    },
    {
      title: '对象',
      dataIndex: 'target_type',
      width: 150,
      render: (value: string) => safeLabel(auditTargetLabel, value, '系统对象'),
    },
    {
      title: '结果',
      dataIndex: 'result',
      width: 110,
      render: (value: string) => (
        <StatusBadge
          status={value === 'SUCCESS' ? 'success' : 'warning'}
          label={value === 'SUCCESS' ? '已完成' : '未完成'}
        />
      ),
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="治理"
        title="审计日志"
        description="管理员变更会形成只读操作记录。记录只包含有界安全元数据，不保存密码、访问凭证或用户私有内容。"
      />
      <FilterBar>
        <SearchField
          value={searchDraft}
          onChange={setSearchDraft}
          onSearch={(value) => {
            setCursor(null)
            setSearch(value.trim())
          }}
          placeholder="搜索管理员姓名或邮箱"
        />
        <Select
          allowClear
          placeholder="全部操作"
          value={action}
          onChange={(value) => {
            setCursor(null)
            setAction(value)
          }}
          options={Object.entries(auditActionLabel).map(([value, label]) => ({ value, label }))}
          style={{ minWidth: 210 }}
          aria-label="按操作类型筛选"
        />
        <Button onClick={() => void state.reload()}>刷新</Button>
      </FilterBar>
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
            emptyText="暂无操作记录"
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
    </>
  )
}
