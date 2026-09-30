import { Button, Select, Tabs, Typography, type TableColumnsType } from 'antd'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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
  dataDeletionStatusLabel,
  formatDateTime,
  safeLabel,
} from '../productLanguage'
import type { AccountDeletionTask, DeletionTask } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

type DeletionPage = { items: DeletionTask[]; next_cursor?: string | null }
type AccountPage = { items: AccountDeletionTask[]; next_cursor?: string | null }

function UserCell({ name, email }: { name: string; email: string | null }) {
  return (
    <div className="table-primary">
      <Text strong>{name}</Text>
      <Text type="secondary">{email ?? '未绑定邮箱'}</Text>
    </div>
  )
}

export function DataTasksPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTab] = useState(
    searchParams.get('tab') === 'account' ? 'account' : 'data',
  )
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [dataCursor, setDataCursor] = useState<string | null>(null)
  const [accountCursor, setAccountCursor] = useState<string | null>(null)

  const dataPath = useMemo(() => {
    const query = new URLSearchParams()
    if (search) query.set('search', search)
    if (statusFilter) query.set('status', statusFilter)
    if (dataCursor) query.set('cursor', dataCursor)
    return '/data-tasks/deletions' + (query.size ? '?' + query.toString() : '')
  }, [search, statusFilter, dataCursor])

  const accountPath = useMemo(() => {
    const query = new URLSearchParams()
    if (search) query.set('search', search)
    if (accountCursor) query.set('cursor', accountCursor)
    return '/data-tasks/account-deletions' + (query.size ? '?' + query.toString() : '')
  }, [search, accountCursor])

  const deletion = useAdminData(
    () => adminRequest<DeletionPage>(dataPath),
    [dataPath],
  )
  const account = useAdminData(
    () => adminRequest<AccountPage>(accountPath),
    [accountPath],
  )

  const resetPagination = () => {
    setDataCursor(null)
    setAccountCursor(null)
  }

  const deletionColumns: TableColumnsType<DeletionTask> = [
    {
      title: '用户',
      key: 'user',
      width: 240,
      render: (_, row) => (
        <UserCell name={row.user_display_name} email={row.user_email} />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 210,
      render: (value: string, row) => (
        <div className="table-primary">
          <StatusBadge
            status={value === 'COMPLETED' ? 'success' : row.retryable ? 'error' : 'warning'}
            label={safeLabel(dataDeletionStatusLabel, value, '处理中')}
          />
          <Text type="secondary">{row.safe_message}</Text>
        </div>
      ),
    },
    {
      title: '等待至',
      dataIndex: 'storage_wait_until',
      width: 180,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '完成时间',
      dataIndex: 'completed_at',
      width: 180,
      render: (value: string | null) => formatDateTime(value),
    },
  ]

  const accountColumns: TableColumnsType<AccountDeletionTask> = [
    {
      title: '用户',
      key: 'user',
      width: 260,
      render: (_, row) => (
        <UserCell name={row.user_display_name} email={row.user_email} />
      ),
    },
    {
      title: '当前状态',
      key: 'phase',
      render: (_, row) => (
        <div className="table-primary">
          <StatusBadge status="warning" label="账号注销处理中" />
          <Text type="secondary">{row.safe_message}</Text>
        </div>
      ),
    },
    {
      title: '开始时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ]

  const filters = (
    <FilterBar>
      <SearchField
        value={searchDraft}
        onChange={setSearchDraft}
        onSearch={(value) => {
          resetPagination()
          setSearch(value.trim())
        }}
        placeholder="搜索用户昵称或邮箱"
      />
      {tab === 'data' && (
        <Select
          allowClear
          placeholder="全部任务状态"
          value={statusFilter}
          onChange={(value) => {
            resetPagination()
            setStatusFilter(value)
          }}
          options={Object.entries(dataDeletionStatusLabel).map(([value, label]) => ({
            value,
            label,
          }))}
          style={{ minWidth: 220 }}
          aria-label="按数据删除状态筛选"
        />
      )}
      <Button
        onClick={() => {
          if (tab === 'data') void deletion.reload()
          else void account.reload()
        }}
      >
        刷新
      </Button>
    </FilterBar>
  )

  return (
    <>
      <PageHeader
        eyebrow="安全与运营"
        title="数据任务"
        description="只展示现有删除状态机的安全投影，不提供绕过存储等待、数据库事务或账号注销确认的快捷操作。"
      />
      <Tabs
        activeKey={tab}
        onChange={(key) => {
          const next = key === 'account' ? 'account' : 'data'
          setTab(next)
          setSearchParams(next === 'account' ? { tab: 'account' } : {})
          resetPagination()
        }}
        items={[
          {
            key: 'data',
            label: '数据删除',
            children: (
              <>
                {filters}
                {deletion.loading && !deletion.data ? (
                  <Loading />
                ) : deletion.error || !deletion.data ? (
                  <ErrorState
                    message={deletion.error ?? undefined}
                    onRetry={() => void deletion.reload()}
                  />
                ) : (
                  <>
                    <DataTable
                      rowKey="id"
                      columns={deletionColumns}
                      dataSource={deletion.data.items}
                      emptyText="暂无数据删除任务"
                    />
                    <div className="admin-pagination">
                      <Button
                        disabled={!deletion.data.next_cursor}
                        onClick={() => {
                          if (deletion.data?.next_cursor) {
                            setDataCursor(deletion.data.next_cursor)
                          }
                        }}
                      >
                        下一页
                      </Button>
                    </div>
                  </>
                )}
              </>
            ),
          },
          {
            key: 'account',
            label: '账号注销',
            children: (
              <>
                {filters}
                {account.loading && !account.data ? (
                  <Loading />
                ) : account.error || !account.data ? (
                  <ErrorState
                    message={account.error ?? undefined}
                    onRetry={() => void account.reload()}
                  />
                ) : (
                  <>
                    <DataTable
                      rowKey="id"
                      columns={accountColumns}
                      dataSource={account.data.items}
                      emptyText="暂无进行中的账号注销任务"
                    />
                    <div className="admin-pagination">
                      <Button
                        disabled={!account.data.next_cursor}
                        onClick={() => {
                          if (account.data?.next_cursor) {
                            setAccountCursor(account.data.next_cursor)
                          }
                        }}
                      >
                        下一页
                      </Button>
                    </div>
                  </>
                )}
              </>
            ),
          },
        ]}
      />
    </>
  )
}
