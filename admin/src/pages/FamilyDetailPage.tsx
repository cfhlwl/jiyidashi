import { Button, Tag, Typography, type TableColumnsType } from 'antd'
import { Link, useParams } from 'react-router-dom'
import { adminRequest } from '../api'
import {
  DataTable,
  DescriptionList,
  DetailSection,
  ErrorState,
  Loading,
  PageHeader,
  TechnicalDetails,
} from '../components/AdminUi'
import {
  familyRoleLabel,
  formatDateTime,
  permissionLabel,
  safeLabel,
} from '../productLanguage'
import type { FamilyDetail } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

export function FamilyDetailPage() {
  const { id } = useParams<{ id: string }>()
  const state = useAdminData(
    () => adminRequest<FamilyDetail>(`/families/${id}`),
    [id],
  )
  if (!id) return <ErrorState title="家庭地址无效" />
  if (state.loading && !state.data) return <Loading />
  if (state.error || !state.data) {
    return <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
  }
  const detail = state.data

  const memberColumns: TableColumnsType<FamilyDetail['members'][number]> = [
    {
      title: '成员',
      key: 'member',
      width: 260,
      render: (_, row) => (
        <div className="table-primary">
          <Text strong>{row.display_name}</Text>
          <Text type="secondary">{row.email ?? '未绑定邮箱'}</Text>
        </div>
      ),
    },
    {
      title: '家庭身份',
      dataIndex: 'role',
      width: 140,
      render: (value: string) => <Tag>{safeLabel(familyRoleLabel, value)}</Tag>,
    },
    {
      title: '加入时间',
      dataIndex: 'joined_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ]

  const grantColumns: TableColumnsType<FamilyDetail['grants'][number]> = [
    {
      title: '授权类别',
      dataIndex: 'permission_code',
      render: (value: string) => safeLabel(permissionLabel, value, '其他授权'),
    },
    {
      title: '当前授权关系',
      dataIndex: 'grant_count',
      width: 140,
      align: 'right',
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="家庭详情"
        title={detail.family.owner_display_name + ' 的家庭'}
        description="管理员只能查看运营结构，不能代替用户授予或撤销隐私权限。"
        extra={<Link to="/families"><Button>返回家庭列表</Button></Link>}
      />
      <DetailSection title="家庭概况">
        <DescriptionList
          items={[
            { label: '创建者', value: detail.family.owner_display_name },
            { label: '创建者邮箱', value: detail.family.owner_email ?? '未绑定' },
            { label: '成员数量', value: detail.family.member_count },
            { label: '授权关系数量', value: detail.family.grant_count },
            { label: '创建时间', value: formatDateTime(detail.family.created_at) },
          ]}
        />
      </DetailSection>
      <div className="admin-two-column">
        <DetailSection title="成员结构">
          <DataTable
            rowKey="user_id"
            columns={memberColumns}
            dataSource={detail.members}
          />
        </DetailSection>
        <DetailSection
          title="授权类别汇总"
          description="只显示授权类别和数量，不展示被授权的私有内容。"
        >
          <DataTable
            rowKey="permission_code"
            columns={grantColumns}
            dataSource={detail.grants}
          />
        </DetailSection>
      </div>
      <TechnicalDetails
        items={[
          { label: '家庭标识', value: detail.family.id },
          { label: '创建者标识', value: detail.family.owner_user_id },
        ]}
      />
    </>
  )
}
