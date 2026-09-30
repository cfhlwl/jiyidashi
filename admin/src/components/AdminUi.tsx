import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Divider,
  Drawer as AntDrawer,
  Empty,
  Input,
  Layout,
  Menu,
  Modal as AntModal,
  Pagination as AntPagination,
  Result,
  Row,
  Skeleton as AntSkeleton,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Timeline,
  Typography,
  type TableColumnsType,
} from 'antd'
import {
  type PropsWithChildren,
  type ReactNode,
  useMemo,
  useState,
} from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAdminSession } from '../session'
import { roleLabel, safeLabel } from '../productLanguage'
import type { AdminRole, AuditEvent, SettingItem } from '../types'

const { Header, Sider, Content } = Layout
const { Text, Title, Paragraph } = Typography

type NavItem = {
  key: string
  label: string
  roles?: AdminRole[]
  section?: string
}

const navItems: NavItem[] = [
  { key: '/', label: '概览', section: '生产运行' },
  { key: '/users', label: '用户', section: '用户与关系' },
  { key: '/families', label: '家庭' },
  { key: '/entitlements', label: '会员与额度' },
  { key: '/data-tasks', label: '数据任务', section: '安全与运营' },
  { key: '/security', label: '安全中心' },
  { key: '/ai-services', label: 'AI 服务', section: '基础服务' },
  { key: '/storage', label: '文件存储' },
  { key: '/system-health', label: '系统运行' },
  { key: '/audit', label: '审计日志', section: '治理' },
  { key: '/settings', label: '系统设置' },
  { key: '/admins', label: '管理员', roles: ['SUPER_ADMIN'] },
]

function roleAllows(role: AdminRole, allowed?: AdminRole[]) {
  return !allowed || allowed.includes(role)
}

export function SideNavigation({
  collapsed,
}: {
  collapsed: boolean
}) {
  const { session } = useAdminSession()
  const location = useLocation()
  const navigate = useNavigate()

  const items = useMemo(() => {
    if (!session) return []
    return navItems
      .filter((item) => roleAllows(session.role, item.roles))
      .map((item) => ({ key: item.key, label: item.label }))
  }, [session])

  const selected =
    navItems
      .map((item) => item.key)
      .filter((key) => key !== '/' && location.pathname.startsWith(key))
      .sort((a, b) => b.length - a.length)[0] ?? '/'

  return (
    <div className="admin-side">
      <div className="admin-brand" aria-label="迹忆管理后台">
        <div className="admin-brand-mark">迹</div>
        {!collapsed && (
          <div>
            <div className="admin-brand-name">迹忆</div>
            <div className="admin-brand-subtitle">管理后台</div>
          </div>
        )}
      </div>
      <Menu
        theme="dark"
        mode="inline"
        selectedKeys={[selected]}
        items={items}
        onClick={({ key }) => navigate(key)}
        aria-label="管理后台主导航"
      />
    </div>
  )
}

export function TopBar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean
  onToggle: () => void
}) {
  const { session, logout } = useAdminSession()
  return (
    <Header className="admin-topbar">
      <Button
        type="text"
        className="admin-menu-toggle"
        onClick={onToggle}
        aria-label={collapsed ? '展开导航' : '收起导航'}
      >
        {collapsed ? '☰' : '≡'}
      </Button>
      <div className="admin-topbar-context">
        <Text className="admin-environment">生产管理</Text>
        <Text type="secondary">所有敏感操作都会重新验证当前权限</Text>
      </div>
      <Space size={12}>
        <div className="admin-identity">
          <Text strong>{session?.display_name}</Text>
          <Text type="secondary">
            {session ? roleLabel[session.role] : ''}
          </Text>
        </div>
        <Button onClick={() => void logout()}>退出</Button>
      </Space>
    </Header>
  )
}

export function AdminShell({ children }: PropsWithChildren) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <Layout className="admin-layout">
      <Sider
        width={232}
        collapsedWidth={72}
        collapsed={collapsed}
        className="admin-sider"
      >
        <SideNavigation collapsed={collapsed} />
      </Sider>
      <Layout>
        <TopBar
          collapsed={collapsed}
          onToggle={() => setCollapsed((value) => !value)}
        />
        <Content className="admin-content">{children}</Content>
      </Layout>
    </Layout>
  )
}

export function PageHeader({
  title,
  description,
  extra,
  eyebrow,
}: {
  title: string
  description?: string
  extra?: ReactNode
  eyebrow?: string
}) {
  return (
    <div className="admin-page-header">
      <div>
        {eyebrow && <Text className="admin-eyebrow">{eyebrow}</Text>}
        <Title level={2}>{title}</Title>
        {description && <Paragraph type="secondary">{description}</Paragraph>}
      </div>
      {extra && <div className="admin-page-actions">{extra}</div>}
    </div>
  )
}

export function MetricCard({
  title,
  value,
  suffix,
  hint,
}: {
  title: string
  value: number | string
  suffix?: string
  hint?: string
}) {
  return (
    <Card className="metric-card" bordered>
      <Statistic title={title} value={value} suffix={suffix} />
      {hint && <Text type="secondary">{hint}</Text>}
    </Card>
  )
}

export function StatusCard({
  title,
  status,
  detail,
}: {
  title: string
  status: 'success' | 'warning' | 'error' | 'info' | 'default'
  detail: string
}) {
  return (
    <Card className="status-card" size="small">
      <Space align="start">
        <StatusBadge status={status} label={title} />
        <Text type="secondary">{detail}</Text>
      </Space>
    </Card>
  )
}

export function StatusBadge({
  status,
  label,
}: {
  status: 'success' | 'warning' | 'error' | 'info' | 'default'
  label: string
}) {
  const color =
    status === 'success'
      ? 'success'
      : status === 'warning'
        ? 'warning'
        : status === 'error'
          ? 'error'
          : status === 'info'
            ? 'processing'
            : 'default'
  return <Tag color={color}>{label}</Tag>
}

export function DataTable<T extends object>({
  columns,
  dataSource,
  rowKey,
  loading,
  emptyText = '暂无数据',
  onRowClick,
}: {
  columns: TableColumnsType<T>
  dataSource: T[]
  rowKey: string | ((record: T) => string)
  loading?: boolean
  emptyText?: string
  onRowClick?: (record: T) => void
}) {
  return (
    <Table<T>
      size="middle"
      columns={columns}
      dataSource={dataSource}
      rowKey={rowKey}
      loading={loading}
      pagination={false}
      scroll={{ x: 'max-content' }}
      locale={{ emptyText: <Empty description={emptyText} /> }}
      onRow={
        onRowClick
          ? (record) => ({
              onClick: () => onRowClick(record),
              onKeyDown: (event) => {
                if (event.key === 'Enter') onRowClick(record)
              },
              tabIndex: 0,
              className: 'admin-clickable-row',
            })
          : undefined
      }
    />
  )
}

export function FilterBar({ children }: PropsWithChildren) {
  return <div className="admin-filter-bar">{children}</div>
}

export function SearchField({
  value,
  onChange,
  onSearch,
  placeholder = '搜索',
}: {
  value: string
  onChange: (value: string) => void
  onSearch?: (value: string) => void
  placeholder?: string
}) {
  return (
    <Input.Search
      allowClear
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      onSearch={onSearch}
      enterButton="搜索"
      className="admin-search"
      aria-label={placeholder}
    />
  )
}

export function DetailSection({
  title,
  description,
  extra,
  children,
}: PropsWithChildren<{
  title: string
  description?: string
  extra?: ReactNode
}>) {
  return (
    <Card
      className="detail-section"
      title={title}
      extra={extra}
      bordered
    >
      {description && (
        <Paragraph type="secondary" className="section-description">
          {description}
        </Paragraph>
      )}
      {children}
    </Card>
  )
}

export function DescriptionList({
  items,
  columns = 2,
}: {
  items: Array<{ label: string; value: ReactNode }>
  columns?: number
}) {
  return (
    <Descriptions
      column={{ xs: 1, sm: 1, md: columns }}
      items={items.map((item, index) => ({
        key: String(index),
        label: item.label,
        children: item.value,
      }))}
      size="middle"
    />
  )
}

export function EmptyState({
  title = '暂无数据',
  description,
}: {
  title?: string
  description?: string
}) {
  return (
    <div className="admin-state">
      <Empty description={title} />
      {description && <Text type="secondary">{description}</Text>}
    </div>
  )
}

export function Loading({
  title = '正在加载',
}: {
  title?: string
}) {
  return (
    <div className="admin-state" role="status" aria-live="polite">
      <Spin size="large" />
      <Text>{title}</Text>
    </div>
  )
}

export const Skeleton = AntSkeleton

export function ErrorState({
  title = '页面暂时无法加载',
  message = '服务暂时不可用，请稍后重试',
  onRetry,
}: {
  title?: string
  message?: string
  onRetry?: () => void
}) {
  return (
    <Result
      status="error"
      title={title}
      subTitle={message}
      extra={
        onRetry ? (
          <Button type="primary" onClick={onRetry}>
            重新加载
          </Button>
        ) : undefined
      }
    />
  )
}

export function PermissionDenied() {
  return (
    <Result
      status="403"
      title="当前账号没有访问权限"
      subTitle="如需执行这项工作，请联系超级管理员调整职责范围。"
    />
  )
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText = '确认',
  loading,
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  description: string
  confirmText?: string
  loading?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <AntModal
      open={open}
      title={title}
      okText={confirmText}
      cancelText="取消"
      confirmLoading={loading}
      onCancel={onCancel}
      onOk={onConfirm}
      destroyOnClose
    >
      <Paragraph>{description}</Paragraph>
    </AntModal>
  )
}

export function DangerConfirmDialog({
  open,
  title,
  impact,
  confirmText,
  phrase,
  loading,
  onCancel,
  onConfirm,
}: {
  open: boolean
  title: string
  impact: ReactNode
  confirmText: string
  phrase?: string
  loading?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const [typed, setTyped] = useState('')
  const allowed = !phrase || typed.trim() === phrase
  return (
    <AntModal
      open={open}
      title={title}
      okText={confirmText}
      cancelText="取消"
      okButtonProps={{ danger: true, disabled: !allowed }}
      confirmLoading={loading}
      onCancel={() => {
        setTyped('')
        onCancel()
      }}
      onOk={() => {
        if (allowed) onConfirm()
      }}
      destroyOnClose
    >
      <Alert
        type="warning"
        showIcon
        message="请确认这次操作的影响"
        description={impact}
      />
      {phrase && (
        <div className="danger-confirm-phrase">
          <Text>
            请输入 <Text code>{phrase}</Text> 继续
          </Text>
          <Input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            aria-label="危险操作确认文字"
          />
        </div>
      )}
    </AntModal>
  )
}

export const Drawer = AntDrawer
export const Modal = AntModal

export function Pagination({
  hasNext,
  onNext,
  disabled,
}: {
  hasNext: boolean
  onNext: () => void
  disabled?: boolean
}) {
  if (!hasNext) return null
  return (
    <div className="admin-pagination">
      <Button disabled={disabled} onClick={onNext}>
        加载更多
      </Button>
    </div>
  )
}

export function NumberedPagination({
  current,
  total,
  pageSize,
  onChange,
}: {
  current: number
  total: number
  pageSize: number
  onChange: (page: number) => void
}) {
  return (
    <AntPagination
      current={current}
      total={total}
      pageSize={pageSize}
      showSizeChanger={false}
      onChange={onChange}
    />
  )
}

export function AuditTimeline({
  items,
}: {
  items: AuditEvent[]
}) {
  return (
    <Timeline
      items={items.map((item) => ({
        children: (
          <div className="audit-event">
            <Text strong>{item.actor}</Text>
            <Text>{item.action}</Text>
            <Text type="secondary">{new Date(item.created_at).toLocaleString('zh-CN')}</Text>
          </div>
        ),
      }))}
    />
  )
}

export function TechnicalDetails({
  items,
}: {
  items: Array<{ label: string; value: string | null | undefined }>
}) {
  return (
    <Collapse
      ghost
      className="technical-details"
      items={[
        {
          key: 'technical',
          label: '技术详情',
          children: (
            <Descriptions
              column={1}
              size="small"
              items={items.map((item, index) => ({
                key: String(index),
                label: item.label,
                children: (
                  <Text copyable={Boolean(item.value)} code={Boolean(item.value)}>
                    {item.value || '—'}
                  </Text>
                ),
              }))}
            />
          ),
        },
      ]}
    />
  )
}

export function SettingRow({
  item,
}: {
  item: SettingItem
}) {
  return (
    <div className="setting-row">
      <div className="setting-row-main">
        <Text strong>{item.label}</Text>
        {item.help_text && <Text type="secondary">{item.help_text}</Text>}
      </div>
      <Space size={12}>
        <Tag>{item.classification}</Tag>
        {item.classification === '敏感配置' ? (
          <SecretConfiguredState configured={Boolean(item.configured)} />
        ) : (
          <Text className="setting-value">
            {typeof item.value === 'boolean'
              ? item.value
                ? '已启用'
                : '未启用'
              : String(item.value ?? '—')}
          </Text>
        )}
      </Space>
    </div>
  )
}

export function SettingSection({
  title,
  items,
}: {
  title: string
  items: SettingItem[]
}) {
  return (
    <DetailSection title={title}>
      <div className="setting-section">
        {items.map((item, index) => (
          <div key={item.key}>
            {index > 0 && <Divider />}
            <SettingRow item={item} />
          </div>
        ))}
      </div>
    </DetailSection>
  )
}

export function SecretConfiguredState({
  configured,
}: {
  configured: boolean
}) {
  return (
    <StatusBadge
      status={configured ? 'success' : 'warning'}
      label={configured ? '已配置' : '未配置'}
    />
  )
}

export function MetricGrid({ children }: PropsWithChildren) {
  return (
    <Row gutter={[16, 16]}>
      {Array.isArray(children)
        ? children.map((child, index) => (
            <Col xs={24} sm={12} xl={6} key={index}>
              {child}
            </Col>
          ))
        : (
            <Col span={24}>{children}</Col>
          )}
    </Row>
  )
}

export function SectionAlert({
  type = 'info',
  message,
  description,
}: {
  type?: 'success' | 'info' | 'warning' | 'error'
  message: string
  description?: string
}) {
  return (
    <Alert
      showIcon
      type={type}
      message={message}
      description={description}
    />
  )
}
