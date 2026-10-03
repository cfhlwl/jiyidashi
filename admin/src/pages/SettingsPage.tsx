import { adminRequest } from '../api'
import {
  ErrorState,
  Loading,
  PageHeader,
  SectionAlert,
  SettingSection,
} from '../components/AdminUi'
import type { SettingsPayload } from '../types'
import { useAdminData } from '../useAdminData'

export function SettingsPage() {
  const state = useAdminData(
    () => adminRequest<SettingsPayload>('/system/settings'),
    [],
  )
  if (state.loading && !state.data) return <Loading />
  if (state.error || !state.data) {
    return <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
  }

  return (
    <>
      <PageHeader
        eyebrow="治理"
        title="系统设置"
        description="每个配置项都明确标注修改方式；会员额度与模型服务使用独立的受控在线配置入口，其余部署配置保持只读或部署管理。"
      />
      <SectionAlert
        message="在线修改仅通过专用受控入口"
        description="会员额度在“会员与额度”维护；AI、语音识别和语义检索在“AI 服务”维护。其他配置保持部署管理或只读，访问凭证永远不会返回原值。"
      />
      <div className="admin-section-stack">
        {state.data.sections.map((section) => (
          <SettingSection
            key={section.key}
            title={section.title}
            items={section.items}
          />
        ))}
      </div>
    </>
  )
}
