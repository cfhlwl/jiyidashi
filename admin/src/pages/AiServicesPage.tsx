import { Col, Row, Typography } from 'antd'
import { adminRequest } from '../api'
import {
  DetailSection,
  ErrorState,
  Loading,
  PageHeader,
  SettingRow,
  StatusCard,
} from '../components/AdminUi'
import type { HealthPayload, SettingsPayload } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

export function AiServicesPage() {
  const settings = useAdminData(
    () => adminRequest<SettingsPayload>('/system/settings'),
    [],
  )
  const health = useAdminData(
    () => adminRequest<HealthPayload>('/system/health'),
    [],
  )
  if ((settings.loading && !settings.data) || (health.loading && !health.data)) {
    return <Loading />
  }
  if (settings.error || health.error || !settings.data || !health.data) {
    return (
      <ErrorState
        message={settings.error ?? health.error ?? undefined}
        onRetry={() => {
          void settings.reload()
          void health.reload()
        }}
      />
    )
  }

  const wanted = new Set(['ai', 'asr', 'embedding'])
  const sections = settings.data.sections.filter((section) => wanted.has(section.key))
  const cards = [
    ['AI 整理服务', health.data.ai_status],
    ['语音识别', health.data.asr_status],
    ['记忆检索', health.data.embedding_status],
  ] as const

  return (
    <>
      <PageHeader
        eyebrow="基础服务"
        title="AI 服务"
        description="展示服务配置完整性与安全投影；打开本页不会自动调用任何付费模型服务。"
      />
      <Row gutter={[16, 16]} className="admin-summary-row">
        {cards.map(([title, status]) => (
          <Col xs={24} md={8} key={title}>
            <StatusCard
              title={title}
              status={status === '正常' ? 'success' : 'default'}
              detail={status}
            />
          </Col>
        ))}
      </Row>
      <div className="admin-section-stack">
        {sections.map((section) => (
          <DetailSection key={section.key} title={section.title}>
            {section.items.map((item) => (
              <SettingRow key={item.key} item={item} />
            ))}
          </DetailSection>
        ))}
      </div>
      <Text type="secondary">
        服务地址仅显示安全主机信息，访问凭证只显示是否已配置。
      </Text>
    </>
  )
}
