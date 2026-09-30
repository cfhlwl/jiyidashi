import { describe, expect, it } from 'vitest'
import {
  auditActionLabel,
  dataDeletionStatusLabel,
  deliveryStatusLabel,
  familyRoleLabel,
  permissionLabel,
  planLabel,
  roleLabel,
  securityCategoryLabel,
  securitySeverityLabel,
} from '../src/productLanguage'

describe('Admin product language dictionaries', () => {
  it('maps every privileged role to human-facing copy', () => {
    expect(roleLabel.SUPER_ADMIN).toBe('超级管理员')
    expect(roleLabel.OPERATOR).toBe('运营管理员')
    expect(roleLabel.SUPPORT_READONLY).toContain('只读')
  })

  it('maps canonical plan and deletion states without exposing raw status as copy', () => {
    expect(planLabel.LEGACY_FULL).toBe('历史兼容方案')
    expect(dataDeletionStatusLabel.DB_FAILED).toBe('数据清理未完成')
  })

  it('has stable mappings for family, security, delivery and audit surfaces', () => {
    expect(familyRoleLabel.OWNER).toBeTruthy()
    expect(permissionLabel.VIEW_MEMORY).toBe('记忆')
    expect(securitySeverityLabel.CRITICAL).toBe('严重')
    expect(securityCategoryLabel.LOGIN_PROTECTION).toBe('登录保护')
    expect(deliveryStatusLabel.RETRYABLE_FAILURE).toBe('等待重试')
    expect(auditActionLabel.USER_ENTITLEMENT_ADJUST).toBe('调整会员方案')
  })
})
