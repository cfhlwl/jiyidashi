import { useState } from 'react'
import { Typography } from 'antd'
import {
  DangerConfirmDialog,
  EmptyState,
  ErrorState,
  Loading,
  PageHeader,
  PermissionDenied,
} from '../components/AdminUi'

const { Text } = Typography

export function ReviewStatePage({ state }: { state: string }) {
  const [dangerOpen, setDangerOpen] = useState(true)
  if (state === 'loading') return <Loading title="正在加载生产数据" />
  if (state === 'error') {
    return (
      <ErrorState
        title="页面暂时无法加载"
        message="服务暂时不可用，请稍后重试"
      />
    )
  }
  if (state === 'permission') return <PermissionDenied />
  if (state === 'danger') {
    return (
      <>
        <PageHeader title="敏感操作确认" description="视觉验收专用状态" />
        <DangerConfirmDialog
          open={dangerOpen}
          title="确认高风险变更"
          impact={<Text>这项操作会立即影响生产运行策略，并记录操作结果。</Text>}
          phrase="确认高风险变更"
          confirmText="确认执行"
          onCancel={() => setDangerOpen(false)}
          onConfirm={() => setDangerOpen(false)}
        />
      </>
    )
  }
  return (
    <>
      <PageHeader title="空状态" description="视觉验收专用状态" />
      <EmptyState
        title="暂无符合条件的数据"
        description="调整筛选条件后可以重新查看。"
      />
    </>
  )
}
