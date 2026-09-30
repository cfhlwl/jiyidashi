import {
  Button,
  Progress,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminRequest, putJson } from '../api'
import {
  DangerConfirmDialog,
  DescriptionList,
  DetailSection,
  ErrorState,
  Loading,
  PageHeader,
  StatusBadge,
  TechnicalDetails,
} from '../components/AdminUi'
import {
  familyRoleLabel,
  formatBytes,
  formatDateTime,
  formatNumber,
  planLabel,
  safeLabel,
} from '../productLanguage'
import { useAdminSession } from '../session'
import type { UserDetail } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

export function UserDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { session } = useAdminSession()
  const state = useAdminData(
    () => adminRequest<UserDetail>(`/users/${id}`),
    [id],
  )
  const [planOpen, setPlanOpen] = useState(false)
  const [nextPlan, setNextPlan] = useState<string>()
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  if (!id) return <ErrorState title="用户地址无效" />
  if (state.loading && !state.data) return <Loading />
  if (state.error || !state.data) {
    return <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
  }

  const detail = state.data
  const entitlement = detail.entitlement
  const storagePercent =
    entitlement.storage_limit_bytes && entitlement.storage_limit_bytes > 0
      ? Math.min(100, Math.round((entitlement.storage_used_bytes / entitlement.storage_limit_bytes) * 100))
      : 0
  const aiPercent =
    entitlement.ai_requests_limit && entitlement.ai_requests_limit > 0
      ? Math.min(100, Math.round((entitlement.ai_requests_used / entitlement.ai_requests_limit) * 100))
      : 0

  const adjustPlan = async () => {
    if (!nextPlan) return
    setSaving(true)
    setActionError(null)
    try {
      await putJson(`/users/${id}/entitlement`, {
        expected_revision: entitlement.revision,
        plan_code: nextPlan,
        confirmation: '调整会员方案',
      })
      setPlanOpen(false)
      setNextPlan(undefined)
      await state.reload()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '会员方案没有更新')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="用户详情"
        title={detail.user.display_name}
        description={detail.user.email ?? '未绑定邮箱'}
        extra={
          <Space>
            <Link to="/users"><Button>返回用户列表</Button></Link>
            {session?.role === 'SUPER_ADMIN' && (
              <Button
                type="primary"
                onClick={() => {
                  setNextPlan(entitlement.plan_code === 'LEGACY_FULL' ? undefined : entitlement.plan_code)
                  setPlanOpen(true)
                }}
              >
                调整会员方案
              </Button>
            )}
          </Space>
        }
      />

      {actionError && <div className="admin-form-error" role="alert">{actionError}</div>}

      <div className="admin-detail-grid">
        <DetailSection title="基本信息">
          <DescriptionList
            items={[
              { label: '昵称', value: detail.user.display_name },
              { label: '邮箱', value: detail.user.email ?? '未绑定' },
              { label: '注册时间', value: formatDateTime(detail.user.created_at) },
              { label: '最近活跃', value: formatDateTime(detail.user.last_active_at) },
              { label: '设备数量', value: formatNumber(detail.user.device_count) },
              {
                label: '家庭状态',
                value: detail.user.family_role
                  ? safeLabel(familyRoleLabel, detail.user.family_role)
                  : '未加入家庭',
              },
            ]}
          />
        </DetailSection>

        <DetailSection title="会员与额度">
          <DescriptionList
            items={[
              {
                label: '当前方案',
                value: <Tag>{safeLabel(planLabel, entitlement.plan_code, '历史兼容方案')}</Tag>,
              },
              { label: '生效时间', value: formatDateTime(entitlement.effective_at) },
              { label: '到期时间', value: formatDateTime(entitlement.expires_at) },
            ]}
          />
          <div className="quota-progress">
            <div>
              <div className="quota-progress-label">
                <Text>存储空间</Text>
                <Text type="secondary">
                  {formatBytes(entitlement.storage_used_bytes)} / {formatBytes(entitlement.storage_limit_bytes)}
                </Text>
              </div>
              <Progress percent={storagePercent} showInfo={false} />
            </div>
            <div>
              <div className="quota-progress-label">
                <Text>本月 AI 请求</Text>
                <Text type="secondary">
                  {formatNumber(entitlement.ai_requests_used)} / {formatNumber(entitlement.ai_requests_limit)}
                </Text>
              </div>
              <Progress percent={aiPercent} showInfo={false} />
            </div>
          </div>
        </DetailSection>

        <DetailSection title="安全与数据任务">
          <DescriptionList
            items={[
              {
                label: '账号状态',
                value: detail.user.account_deletion_in_progress
                  ? <StatusBadge status="warning" label="账号注销处理中" />
                  : <StatusBadge status="success" label="正常" />,
              },
              {
                label: '数据任务',
                value: detail.data_deletion_status
                  ? <StatusBadge status="warning" label="存在数据删除任务" />
                  : '暂无进行中的数据删除任务',
              },
              {
                label: '账号注销开始时间',
                value: formatDateTime(detail.account_deletion_started_at),
              },
            ]}
          />
        </DetailSection>

        <DetailSection title="家庭">
          {detail.family_id ? (
            <Space>
              <Text>该用户已加入家庭。</Text>
              <Link to={`/families/${detail.family_id}`}>查看家庭运营信息</Link>
            </Space>
          ) : (
            <Text type="secondary">该用户当前未加入家庭。</Text>
          )}
        </DetailSection>
      </div>

      <TechnicalDetails
        items={[
          { label: '用户标识', value: detail.user.id },
          { label: '会员状态版本', value: String(entitlement.revision) },
        ]}
      />

      <DangerConfirmDialog
        open={planOpen}
        title="调整会员方案"
        confirmText="确认调整"
        phrase="调整会员方案"
        loading={saving}
        onCancel={() => {
          setPlanOpen(false)
          setActionError(null)
        }}
        onConfirm={() => void adjustPlan()}
        impact={
          <div className="danger-impact">
            <Text>新的会员方案会立即成为该用户的服务端权限与额度依据。</Text>
            <Select
              value={nextPlan}
              onChange={setNextPlan}
              placeholder="选择新的会员方案"
              options={[
                { value: 'FREE', label: '免费版' },
                { value: 'PERSONAL', label: '个人版' },
                { value: 'FAMILY', label: '家庭版' },
                { value: 'PREMIUM', label: '高级版' },
              ]}
              style={{ width: '100%', marginTop: 12 }}
              aria-label="新的会员方案"
            />
          </div>
        }
      />
    </>
  )
}
