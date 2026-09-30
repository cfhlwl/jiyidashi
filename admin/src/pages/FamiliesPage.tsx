import { Typography, type TableColumnsType } from 'antd'
import { useNavigate } from 'react-router-dom'
import { adminRequest } from '../api'
import {
  DataTable,
  ErrorState,
  Loading,
  PageHeader,
} from '../components/AdminUi'
import { formatDateTime } from '../productLanguage'
import type { FamilyListItem, FamilyPage } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

export function FamiliesPage() {
  const navigate = useNavigate()
  const state = useAdminData(() => adminRequest<FamilyPage>('/families'), [])

  const columns: TableColumnsType<FamilyListItem> = [
    {
      title: '家庭创建者',
      key: 'owner',
      width: 260,
      render: (_, row) => (
        <div className="table-primary">
          <Text strong>{row.owner_display_name}</Text>
          <Text type="secondary">{row.owner_email ?? '未绑定邮箱'}</Text>
        </div>
      ),
    },
    { title: '成员', dataIndex: 'member_count', width: 100, align: 'right' },
    { title: '授权关系', dataIndex: 'grant_count', width: 120, align: 'right' },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="用户与关系"
        title="家庭"
        description="展示家庭成员结构与授权类别汇总，不读取任何家庭成员的私有记忆、照片或位置内容。"
      />
      {state.loading && !state.data ? (
        <Loading />
      ) : state.error || !state.data ? (
        <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
      ) : (
        <DataTable
          rowKey="id"
          columns={columns}
          dataSource={state.data.items}
          emptyText="暂无家庭"
          onRowClick={(row) => navigate(`/families/${row.id}`)}
        />
      )}
    </>
  )
}
