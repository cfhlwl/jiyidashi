import { Typography } from 'antd'
import { adminRequest } from '../api'
import {
  DescriptionList,
  DetailSection,
  ErrorState,
  Loading,
  PageHeader,
  SettingRow,
  StatusBadge,
} from '../components/AdminUi'
import { formatBytes } from '../productLanguage'
import type { HealthPayload, SettingsPayload } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

export function StoragePage() {
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
    return <ErrorState message={settings.error ?? health.error ?? undefined} />
  }
  const section = settings.data.sections.find((item) => item.key === 'storage')

  return (
    <>
      <PageHeader
        eyebrow="基础服务"
        title="文件存储"
        description="只展示存储配置状态与聚合使用量，不提供用户文件浏览、对象标识或临时访问链接。"
      />
      <DetailSection title="运行状态">
        <DescriptionList
          items={[
            {
              label: '服务状态',
              value: (
                <StatusBadge
                  status={health.data.storage_status === '正常' ? 'success' : 'default'}
                  label={health.data.storage_status}
                />
              ),
            },
            {
              label: '全站聚合使用量',
              value: formatBytes(health.data.total_storage_used_bytes),
            },
            {
              label: '待处理存储告警',
              value: (
                <StatusBadge
                  status={health.data.storage_alerts_needing_attention > 0 ? 'warning' : 'success'}
                  label={
                    health.data.storage_alerts_needing_attention > 0
                      ? `${health.data.storage_alerts_needing_attention} 条需要关注`
                      : '暂无'
                  }
                />
              ),
            },
            { label: '存储策略', value: '私有访问；临时能力由服务端按需签发' },
          ]}
        />
      </DetailSection>
      {section && (
        <DetailSection title="部署配置">
          {section.items.map((item) => (
            <SettingRow key={item.key} item={item} />
          ))}
        </DetailSection>
      )}
      <Text type="secondary">
        管理后台不会返回访问凭证、用户对象路径或可下载用户文件的临时地址。
      </Text>
    </>
  )
}
