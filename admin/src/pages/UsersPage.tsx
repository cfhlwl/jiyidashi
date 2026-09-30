import { Button, Input, Select, Space, Tag, Typography, type TableColumnsType } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
  familyRoleLabel,
  formatBytes,
  formatDateTime,
  planLabel,
  safeLabel,
} from '../productLanguage'
import type { UserListItem, UserPage } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

export function UsersPage() {
  const navigate = useNavigate()
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [plan, setPlan] = useState<string | undefined>()
  const [registeredFrom, setRegisteredFrom] = useState('')
  const [registeredTo, setRegisteredTo] = useState('')
  const [operationalState, setOperationalState] = useState<string | undefined>()
  const [cursor, setCursor] = useState<string | null>(null)
  const [pageNumber, setPageNumber] = useState(1)

  const resetPage = () => {
    setCursor(null)
    setPageNumber(1)
  }

  const query = new URLSearchParams()
  if (search) query.set('search', search)
  if (plan) query.set('plan', plan)
  if (registeredFrom) query.set('registered_from', registeredFrom)
  if (registeredTo) query.set('registered_to', registeredTo)
  if (operationalState) query.set('operational_state', operationalState)
  if (cursor) query.set('cursor', cursor)
  const path = `/users${query.size ? `?${query.toString()}` : ''}`

  const state = useAdminData(() => adminRequest<UserPage>(path), [path])

  const columns = useMemo<TableColumnsType<UserListItem>>(
    () => [
      {
        title: '用户',
        key: 'user',
        fixed: 'left',
        width: 240,
        render: (_, row) => (
          <div className="table-primary">
            <Text strong>{row.display_name}</Text>
            <Text type="secondary">{row.email ?? '未绑定邮箱'}</Text>
          </div>
        ),
      },
      {
        title: '会员方案',
        dataIndex: 'plan_code',
        width: 130,
        render: (value: string) => <Tag>{safeLabel(planLabel, value, '兼容方案')}</Tag>,
      },
      {
        title: '家庭状态',
        dataIndex: 'family_role',
        width: 130,
        render: (value: string | null) =>
          value ? safeLabel(familyRoleLabel, value) : '未加入家庭',
      },
      {
        title: '设备',
        dataIndex: 'device_count',
        width: 90,
        align: 'right',
      },
      {
        title: '存储使用',
        dataIndex: 'storage_used_bytes',
        width: 130,
        render: (value: number) => formatBytes(value),
      },
      {
        title: '最近活跃',
        dataIndex: 'last_active_at',
        width: 180,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: '运营状态',
        key: 'state',
        width: 190,
        render: (_, row) => (
          <Space wrap>
            {row.account_deletion_in_progress && (
              <StatusBadge status="warning" label="账号注销处理中" />
            )}
            {row.data_deletion_in_progress && (
              <StatusBadge status="warning" label="数据删除处理中" />
            )}
            {!row.account_deletion_in_progress && !row.data_deletion_in_progress && (
              <StatusBadge status="success" label="正常" />
            )}
          </Space>
        ),
      },
      {
        title: '注册时间',
        dataIndex: 'created_at',
        width: 180,
        render: (value: string) => formatDateTime(value),
      },
    ],
    [],
  )

  return (
    <>
      <PageHeader
        eyebrow="用户与关系"
        title="用户"
        description="只展示账号与运营元数据。这里不能浏览用户记忆正文、照片内容或精确位置。"
      />
      <FilterBar>
        <SearchField
          value={searchDraft}
          onChange={setSearchDraft}
          onSearch={(value) => {
            resetPage()
            setSearch(value.trim())
          }}
          placeholder="搜索昵称或邮箱"
        />
        <Select
          allowClear
          placeholder="全部会员方案"
          value={plan}
          onChange={(value) => {
            resetPage()
            setPlan(value)
          }}
          options={[
            { value: 'FREE', label: '免费版' },
            { value: 'PERSONAL', label: '个人版' },
            { value: 'FAMILY', label: '家庭版' },
            { value: 'PREMIUM', label: '高级版' },
            { value: 'LEGACY_FULL', label: '历史兼容方案' },
          ]}
          style={{ minWidth: 180 }}
          aria-label="按会员方案筛选"
        />
        <Input
          type="date"
          value={registeredFrom}
          onChange={(event) => {
            resetPage()
            setRegisteredFrom(event.target.value)
          }}
          aria-label="注册开始日期"
          style={{ width: 150 }}
        />
        <Input
          type="date"
          value={registeredTo}
          onChange={(event) => {
            resetPage()
            setRegisteredTo(event.target.value)
          }}
          aria-label="注册结束日期"
          style={{ width: 150 }}
        />
        <Select
          allowClear
          placeholder="全部运营状态"
          value={operationalState}
          onChange={(value) => {
            resetPage()
            setOperationalState(value)
          }}
          options={[
            { value: 'NORMAL', label: '正常' },
            { value: 'DATA_DELETION', label: '数据删除处理中' },
            { value: 'ACCOUNT_DELETION', label: '账号注销处理中' },
          ]}
          style={{ minWidth: 180 }}
          aria-label="按运营状态筛选"
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
            onRowClick={(row) => navigate(`/users/${row.id}`)}
            emptyText="没有符合条件的用户"
          />
          <div className="admin-pagination">
            <Text type="secondary">第 {pageNumber} 页</Text>
            <Button
              disabled={!state.data.next_cursor}
              onClick={() => {
                if (!state.data?.next_cursor) return
                setCursor(state.data.next_cursor)
                setPageNumber((value) => value + 1)
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
