import { Badge, Card, Col, Row, Space, Typography } from 'antd'
import { adminRequest } from '../api'
import {
  DataTable,
  ErrorState,
  Loading,
  MetricCard,
  PageHeader,
  StatusBadge,
} from '../components/AdminUi'
import { useAdminData } from '../useAdminData'
import { formatNumber, safeLabel, serviceStatusLabel } from '../productLanguage'
import type { Dashboard } from '../types'

const { Text, Title } = Typography

export function DashboardPage() {
  const state = useAdminData(
    () => adminRequest<Dashboard>('/dashboard'),
    [],
  )
  if (state.loading && !state.data) return <Loading title="正在读取生产状态" />
  if (state.error || !state.data) {
    return <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
  }

  const { overview, services, trend } = state.data
  const attention = [
    {
      key: 'account',
      item: '账号注销',
      count: overview.active_account_deletions,
      guidance: overview.active_account_deletions ? '查看当前处理中的注销任务' : '无需处理',
    },
    {
      key: 'data',
      item: '数据删除',
      count: overview.pending_data_deletions,
      guidance: overview.pending_data_deletions ? '检查等待或失败任务' : '无需处理',
    },
    {
      key: 'security',
      item: '安全事件',
      count: overview.security_alerts_needing_attention,
      guidance: overview.security_alerts_needing_attention ? '查看安全中心' : '暂无待处理事件',
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="生产概览"
        title="系统现在怎么样"
        description="基于当前生产权威状态汇总，不调用付费服务，也不展示用户私有内容。"
      />
      <Row gutter={[16, 16]} className="dashboard-metrics">
        <Col xs={24} sm={12} xl={6}>
          <MetricCard title="注册用户" value={formatNumber(overview.registered_users)} hint={`今日新增 ${formatNumber(overview.new_users_today)}`} />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <MetricCard title="今日活跃用户" value={formatNumber(overview.active_users_today)} hint="按现有活跃统计口径" />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <MetricCard title="今日新增记忆" value={formatNumber(overview.memories_created_today)} hint="仅聚合数量" />
        </Col>
        <Col xs={24} sm={12} xl={6}>
          <MetricCard title="成功检索" value={formatNumber(overview.successful_retrievals_today)} hint="今日成功检索次数" />
        </Col>
      </Row>

      <Row gutter={[16, 16]} className="dashboard-grid">
        <Col xs={24} xl={15}>
          <Card title="服务状态" className="admin-panel">
            <Row gutter={[12, 12]}>
              {services.map((service) => (
                <Col xs={24} md={12} key={service.key}>
                  <div className="service-row">
                    <Space>
                      <Badge
                        status={
                          service.status === 'NORMAL'
                            ? 'success'
                            : service.status === 'DISABLED'
                              ? 'default'
                              : 'warning'
                        }
                      />
                      <Text strong>{service.label}</Text>
                    </Space>
                    <Space>
                      <Text type="secondary">{service.detail}</Text>
                      <StatusBadge
                        status={service.status === 'NORMAL' ? 'success' : service.status === 'DISABLED' ? 'default' : 'warning'}
                        label={safeLabel(serviceStatusLabel, service.status)}
                      />
                    </Space>
                  </div>
                </Col>
              ))}
            </Row>
          </Card>
        </Col>
        <Col xs={24} xl={9}>
          <Card title="需要处理" className="admin-panel">
            <DataTable
              rowKey="key"
              dataSource={attention}
              columns={[
                { title: '事项', dataIndex: 'item' },
                {
                  title: '数量',
                  dataIndex: 'count',
                  width: 88,
                  render: (value: number) => (
                    <Title level={5} className="table-count">{value}</Title>
                  ),
                },
                { title: '建议', dataIndex: 'guidance' },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card title="近 7 日趋势" className="admin-panel trend-placeholder">
        <DataTable
          rowKey="day"
          dataSource={trend}
          columns={[
            {
              title: '日期',
              dataIndex: 'day',
              render: (value: string) =>
                new Intl.DateTimeFormat('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                }).format(new Date(value + 'T00:00:00+08:00')),
            },
            {
              title: '活跃用户',
              dataIndex: 'active_users',
              align: 'right',
              render: (value: number) => formatNumber(value),
            },
            {
              title: '成功检索',
              dataIndex: 'successful_retrievals',
              align: 'right',
              render: (value: number) => formatNumber(value),
            },
          ]}
        />
        <Text type="secondary" className="trend-note">
          趋势只使用已有活跃统计与成功检索聚合，不补造缺失指标。
        </Text>
      </Card>
    </>
  )
}
