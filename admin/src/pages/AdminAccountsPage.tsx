import {
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
  type TableColumnsType,
} from 'antd'
import { useState } from 'react'
import { adminRequest, patchJson, postJson } from '../api'
import {
  ConfirmDialog,
  DataTable,
  DangerConfirmDialog,
  ErrorState,
  Loading,
  PageHeader,
  StatusBadge,
} from '../components/AdminUi'
import { formatDateTime, roleLabel, safeLabel } from '../productLanguage'
import { useAdminSession } from '../session'
import type { AdminAccount, AdminRole } from '../types'
import { useAdminData } from '../useAdminData'

const { Text } = Typography

type CreateValues = {
  email: string
  display_name: string
  password: string
  role: AdminRole
}
type PasswordValues = { new_password: string }

export function AdminAccountsPage() {
  const { session } = useAdminSession()
  const state = useAdminData(
    () => adminRequest<AdminAccount[]>('/admins'),
    [],
  )
  const [createOpen, setCreateOpen] = useState(false)
  const [createValues, setCreateValues] = useState<CreateValues | null>(null)
  const [editTarget, setEditTarget] = useState<AdminAccount | null>(null)
  const [nextRole, setNextRole] = useState<AdminRole | null>(null)
  const [toggleTarget, setToggleTarget] = useState<AdminAccount | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<AdminAccount | null>(null)
  const [passwordTarget, setPasswordTarget] = useState<AdminAccount | null>(null)
  const [passwordValues, setPasswordValues] = useState<PasswordValues | null>(null)
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [createForm] = Form.useForm<CreateValues>()
  const [passwordForm] = Form.useForm<PasswordValues>()

  const run = async (operation: () => Promise<unknown>) => {
    setSaving(true)
    setActionError(null)
    try {
      await operation()
      await state.reload()
      return true
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '操作没有完成')
      return false
    } finally {
      setSaving(false)
    }
  }

  const columns: TableColumnsType<AdminAccount> = [
    {
      title: '管理员',
      key: 'admin',
      width: 250,
      render: (_, row) => (
        <div className="table-primary">
          <Text strong>{row.display_name}</Text>
          <Text type="secondary">{row.email}</Text>
        </div>
      ),
    },
    {
      title: '职责',
      dataIndex: 'role',
      width: 170,
      render: (value: AdminRole) => <Tag>{safeLabel(roleLabel, value)}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'disabled',
      width: 110,
      render: (disabled: boolean) => (
        <StatusBadge
          status={disabled ? 'default' : 'success'}
          label={disabled ? '已停用' : '可用'}
        />
      ),
    },
    {
      title: '最近登录',
      dataIndex: 'last_login_at',
      width: 180,
      render: (value: string | null) => formatDateTime(value),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: '操作',
      key: 'actions',
      fixed: 'right',
      width: 300,
      render: (_, row) => {
        const self = row.id === session?.admin_id
        return (
          <Space wrap>
            <Button
              size="small"
              disabled={self}
              onClick={() => {
                setEditTarget(row)
                setNextRole(row.role)
              }}
            >
              调整职责
            </Button>
            <Button
              size="small"
              disabled={self}
              onClick={() => setToggleTarget(row)}
            >
              {row.disabled ? '恢复' : '停用'}
            </Button>
            <Button size="small" onClick={() => setPasswordTarget(row)}>
              重置密码
            </Button>
            <Button size="small" onClick={() => setRevokeTarget(row)}>
              撤销会话
            </Button>
          </Space>
        )
      },
    },
  ]

  if (session?.role !== 'SUPER_ADMIN') {
    return <ErrorState title="当前账号没有访问权限" message="管理员管理仅向超级管理员开放。" />
  }

  return (
    <>
      <PageHeader
        eyebrow="治理"
        title="管理员"
        description="管理独立的后台身份、职责和会话。普通迹忆用户账号不能用于登录此后台。"
        extra={<Button type="primary" onClick={() => setCreateOpen(true)}>创建管理员</Button>}
      />
      {actionError && <div className="admin-form-error" role="alert">{actionError}</div>}
      {state.loading && !state.data ? (
        <Loading />
      ) : state.error || !state.data ? (
        <ErrorState message={state.error ?? undefined} onRetry={() => void state.reload()} />
      ) : (
        <DataTable
          rowKey="id"
          columns={columns}
          dataSource={state.data}
          emptyText="暂无管理员"
        />
      )}

      <Modal
        open={createOpen}
        title="创建管理员"
        okText="下一步"
        cancelText="取消"
        onCancel={() => {
          setCreateOpen(false)
          createForm.resetFields()
        }}
        onOk={() => void createForm.validateFields().then((values) => {
          setCreateValues(values)
          setCreateOpen(false)
        })}
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" requiredMark={false}>
          <Form.Item
            label="姓名"
            name="display_name"
            rules={[{ required: true, message: '请输入管理员姓名' }]}
          >
            <Input maxLength={80} />
          </Form.Item>
          <Form.Item
            label="管理员邮箱"
            name="email"
            rules={[
              { required: true, message: '请输入管理员邮箱' },
              { type: 'email', message: '请输入有效邮箱地址' },
            ]}
          >
            <Input autoComplete="off" />
          </Form.Item>
          <Form.Item
            label="初始密码"
            name="password"
            rules={[
              { required: true, message: '请输入初始密码' },
              { min: 12, message: '密码至少 12 个字符' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            label="职责"
            name="role"
            initialValue="SUPPORT_READONLY"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: 'SUPPORT_READONLY', label: '支持人员（只读）' },
                { value: 'OPERATOR', label: '运营管理员' },
                { value: 'SUPER_ADMIN', label: '超级管理员' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <DangerConfirmDialog
        open={Boolean(createValues)}
        title={createValues?.role === 'SUPER_ADMIN' ? '创建超级管理员' : '创建管理员'}
        impact={
          <Text>
            {createValues?.role === 'SUPER_ADMIN'
              ? '超级管理员可以管理其他管理员、系统设置和会员额度。请确认职责确实需要。'
              : '新管理员将获得所选职责范围内的后台访问能力。'}
          </Text>
        }
        phrase={createValues?.role === 'SUPER_ADMIN' ? '创建超级管理员' : '创建管理员'}
        confirmText="确认创建"
        loading={saving}
        onCancel={() => setCreateValues(null)}
        onConfirm={() => {
          if (!createValues) return
          void run(async () => {
            await postJson('/admins', {
              ...createValues,
              confirmation:
                createValues.role === 'SUPER_ADMIN'
                  ? '创建超级管理员'
                  : '创建管理员',
            })
          }).then((ok) => {
            if (ok) {
              setCreateValues(null)
              createForm.resetFields()
            }
          })
        }}
      />

      <DangerConfirmDialog
        open={Boolean(editTarget)}
        title="调整管理员职责"
        impact={
          <Space direction="vertical" style={{ width: '100%' }}>
            <Text>职责变化会让该管理员现有登录会话立即失效。</Text>
            <Select
              value={nextRole ?? undefined}
              onChange={setNextRole}
              style={{ width: '100%' }}
              options={[
                { value: 'SUPPORT_READONLY', label: '支持人员（只读）' },
                { value: 'OPERATOR', label: '运营管理员' },
                { value: 'SUPER_ADMIN', label: '超级管理员' },
              ]}
            />
          </Space>
        }
        phrase={nextRole === 'SUPER_ADMIN' && editTarget?.role !== 'SUPER_ADMIN'
          ? '授予超级管理员'
          : '确认管理员变更'}
        confirmText="确认调整"
        loading={saving}
        onCancel={() => setEditTarget(null)}
        onConfirm={() => {
          if (!editTarget || !nextRole) return
          void run(() => patchJson('/admins/' + editTarget.id, {
            expected_revision: editTarget.revision,
            role: nextRole,
            confirmation:
              nextRole === 'SUPER_ADMIN' && editTarget.role !== 'SUPER_ADMIN'
                ? '授予超级管理员'
                : '确认管理员变更',
          })).then((ok) => {
            if (ok) setEditTarget(null)
          })
        }}
      />

      <DangerConfirmDialog
        open={Boolean(toggleTarget)}
        title={toggleTarget?.disabled ? '恢复管理员账号' : '停用管理员账号'}
        impact={
          <Text>
            {toggleTarget?.disabled
              ? '恢复后，该管理员可以重新登录后台。'
              : '停用后，该管理员的现有会话会立即失效，不能继续访问后台。'}
          </Text>
        }
        phrase="确认管理员变更"
        confirmText={toggleTarget?.disabled ? '确认恢复' : '确认停用'}
        loading={saving}
        onCancel={() => setToggleTarget(null)}
        onConfirm={() => {
          if (!toggleTarget) return
          void run(() => patchJson('/admins/' + toggleTarget.id, {
            expected_revision: toggleTarget.revision,
            disabled: !toggleTarget.disabled,
            confirmation: '确认管理员变更',
          })).then((ok) => {
            if (ok) setToggleTarget(null)
          })
        }}
      />

      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="撤销管理员会话"
        description="该管理员当前有效的后台登录会话会立即失效，需要重新登录。"
        confirmText="撤销会话"
        loading={saving}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => {
          if (!revokeTarget) return
          void run(() => postJson('/admins/' + revokeTarget.id + '/revoke-sessions'))
            .then((ok) => {
              if (ok) setRevokeTarget(null)
            })
        }}
      />

      <Modal
        open={Boolean(passwordTarget)}
        title="重置管理员密码"
        okText="下一步"
        cancelText="取消"
        onCancel={() => {
          setPasswordTarget(null)
          setPasswordValues(null)
          passwordForm.resetFields()
        }}
        onOk={() => void passwordForm.validateFields().then((values) => {
          setPasswordValues(values)
        })}
        destroyOnClose
      >
        <Form form={passwordForm} layout="vertical" requiredMark={false}>
          <Form.Item
            label="新密码"
            name="new_password"
            rules={[
              { required: true, message: '请输入新密码' },
              { min: 12, message: '密码至少 12 个字符' },
            ]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>

      <DangerConfirmDialog
        open={Boolean(passwordTarget && passwordValues)}
        title="确认重置管理员密码"
        impact={<Text>密码变更后，该管理员现有后台会话都会立即失效。</Text>}
        phrase="重置管理员密码"
        confirmText="确认重置"
        loading={saving}
        onCancel={() => setPasswordValues(null)}
        onConfirm={() => {
          if (!passwordTarget || !passwordValues) return
          void run(() => postJson('/admins/' + passwordTarget.id + '/password-reset', {
            expected_revision: passwordTarget.revision,
            new_password: passwordValues.new_password,
            confirmation: '重置管理员密码',
          })).then((ok) => {
            if (ok) {
              setPasswordTarget(null)
              setPasswordValues(null)
              passwordForm.resetFields()
            }
          })
        }}
      />
    </>
  )
}
