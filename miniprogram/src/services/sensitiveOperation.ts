import Taro from '@tarojs/taro'

export type SensitiveOperationStrength =
  | 'disclosure'
  | 'destructive-data'
  | 'irreversible-account'
  | 'permission-mutation'
  | 'sensitive-location'

export type SensitiveOperationSpec = {
  id: string
  strength: SensitiveOperationStrength
  title: string
  summary: string
  scope: string
  undo: string
  confirmText: string
  destructive?: boolean
}

export const sensitiveOperationStateChangedMessage =
  '状态刚刚发生变化，请重新打开后再试'

export function dataExportConfirmation(): SensitiveOperationSpec {
  return {
    id: 'data-export',
    strength: 'disclosure',
    title: '导出这些数据？',
    summary: '将生成一份你当前账号可导出的个人数据副本。',
    scope: '仅包含本次请求明确列出的导出范围；导出不会修改服务器上的数据。',
    undo: '导出本身不会修改数据，但导出的文件需要由你自行安全保管。',
    confirmText: '导出这些数据',
  }
}

export function dataDeleteConfirmation(): SensitiveOperationSpec {
  return {
    id: 'data-delete',
    strength: 'destructive-data',
    title: '删除这些数据？',
    summary: '将删除当前账号中本次操作覆盖的数据。',
    scope: '实际删除范围以服务端当前权威状态为准，不会创建回收站或隐藏副本。',
    undo: '完成真实删除后无法通过迹忆恢复。',
    confirmText: '删除这些数据',
    destructive: true,
  }
}

export function familyPermissionConfirmation(input: {
  enabled: boolean
  permissionLabel: string
  memberLabel: string
}): SensitiveOperationSpec {
  return {
    id: input.enabled ? 'family-grant' : 'family-revoke',
    strength: 'permission-mutation',
    title: input.enabled ? '允许这项家庭查看权限？' : '取消这项家庭查看权限？',
    summary: input.enabled
      ? `${input.memberLabel} 将能够按当前家庭规则使用这项查看权限。`
      : `${input.memberLabel} 将不再能够通过这项家庭授权查看对应内容。`,
    scope: input.permissionLabel,
    undo: input.enabled ? '之后可以再次取消授权。' : '之后可以重新授权。',
    confirmText: input.enabled ? '允许查看' : '取消授权',
    destructive: !input.enabled,
  }
}

export function familyMemberChangeConfirmation(input: {
  leaving: boolean
  memberLabel: string
}): SensitiveOperationSpec {
  return {
    id: input.leaving ? 'family-leave' : 'family-remove',
    strength: 'permission-mutation',
    title: input.leaving ? '退出这个家庭？' : '移除这个家庭成员？',
    summary: input.leaving
      ? '退出后，你与家庭成员之间现有的共享授权会被清理。'
      : `移除后，与 ${input.memberLabel} 相关的家庭共享授权会被清理。`,
    scope: input.leaving ? '当前账号在这个家庭中的成员关系' : `${input.memberLabel} 的家庭成员关系`,
    undo: '如需恢复关系，需要重新加入家庭并重新授权。',
    confirmText: input.leaving ? '退出家庭' : '移除成员',
    destructive: true,
  }
}

export function emergencyLocationShareConfirmation(input: {
  memberLabel: string
  durationLabel: string
}): SensitiveOperationSpec {
  return {
    id: 'emergency-location-share',
    strength: 'sensitive-location',
    title: '开始紧急共享位置？',
    summary: `${input.memberLabel} 将在限定时间内获得紧急位置查看能力。`,
    scope: `共享当前位置，持续 ${input.durationLabel}；不会扩展为后台共享新能力。`,
    undo: '可以随时停止共享；到期后服务端也会停止该临时能力。',
    confirmText: '开始共享位置',
  }
}

export async function confirmSensitiveOperation(
  spec: SensitiveOperationSpec,
): Promise<boolean> {
  const result = await Taro.showModal({
    title: spec.title,
    content: [
      spec.summary,
      `影响范围：${spec.scope}`,
      `是否可撤销：${spec.undo}`,
    ].join('\n'),
    confirmText: spec.confirmText,
    ...(spec.destructive ? { confirmColor: '#b3261e' } : {}),
  })
  return result.confirm === true
}

export class SensitiveOperationEpoch {
  private generation = 0

  capture(): number {
    return this.generation
  }

  invalidate(): number {
    this.generation += 1
    return this.generation
  }

  isCurrent(captured: number): boolean {
    return captured === this.generation
  }
}
