import { Col, Row } from 'antd'
import { adminRequest } from '../api'
import {
  DescriptionList,
  DetailSection,
  ErrorState,
  Loading,
  PageHeader,
  StatusCard,
  TechnicalDetails,
} from '../components/AdminUi'
import { formatBytes } from '../productLanguage'
import type { HealthPayload } from '../types'
import { useAdminData } from '../useAdminData'

export function SystemHealthPage() {
  const state = useAdminData(
    () => adminRequest<HealthPayload>('/system/health'),
    [],
  )
  if (state.loading && !state.data) return <Loading />
  if (state.error || !state.data) {
    return <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
  }
  const health = state.data
  const services = [
    ['接口服务', health.api_status],
    ['数据库', health.database_status],
    ['文件存储', health.storage_status],
    ['AI 整理', health.ai_status],
    ['语音识别', health.asr_status],
    ['记忆检索', health.embedding_status],
  ] as const

  return (
    <>
      <PageHeader
        eyebrow="基础服务"
        title="系统运行"
        description="生产系统只读状态与部署信息。基础设施连接方式和密钥不能在这里修改。"
      />
      <Row gutter={[16, 16]}>
        {services.map(([title, status]) => (
          <Col xs={24} sm={12} xl={8} key={title}>
            <StatusCard
              title={title}
              status={status === '正常' ? 'success' : status === '未启用' ? 'default' : 'warning'}
              detail={status}
            />
          </Col>
        ))}
      </Row>
      <DetailSection title="部署信息">
        <DescriptionList
          items={[
            { label: '运行环境', value: health.environment === 'production' ? '生产环境' : '非生产环境' },
            { label: '应用版本', value: health.app_version },
            { label: '数据库结构', value: health.database_schema_status },
            { label: '部署时间', value: health.build_time ?? '未提供' },
            { label: '聚合存储使用', value: formatBytes(health.total_storage_used_bytes) },
          ]}
        />
      </DetailSection>
      <TechnicalDetails
        items={[
          { label: '代码版本', value: health.git_sha },
          { label: '数据库结构版本', value: health.database_schema_version },
        ]}
      />
    </>
  )
}
