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
        description="每个配置项都明确标注修改方式；部署配置与敏感配置不会因为出现在页面上就获得保存按钮。"
      />
      <SectionAlert
        message="在线可修改项仅限经过审核的会员额度目录"
        description="其余配置保持部署管理或只读；访问凭证永远不会返回原值。"
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
