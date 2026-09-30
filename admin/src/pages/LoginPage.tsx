import { Button, Card, Form, Input, Typography } from 'antd'
import { Navigate } from 'react-router-dom'
import { fixtureMode } from '../api'
import { useAdminSession } from '../session'

const { Text, Title } = Typography

export function LoginPage() {
  const { session, loading, error, login } = useAdminSession()
  const reviewLogin = fixtureMode && window.location.search.includes('review=login')
  if (!loading && session && !reviewLogin) return <Navigate to="/" replace />

  return (
    <main className="admin-login-page">
      <section className="admin-login-hero" aria-label="迹忆生产管理后台介绍">
        <div className="admin-login-brand">
          <div className="admin-brand-mark admin-brand-mark-large">迹</div>
          <div>
            <Title level={1}>迹忆管理后台</Title>
            <Text>生产运营与安全管理</Text>
          </div>
        </div>
        <div className="admin-login-message">
          <Text className="login-kicker">JiYi Production Operations</Text>
          <Title level={2}>清晰掌握系统状态，可信处理关键操作。</Title>
          <Text>
            面向授权运营人员的生产控制台。所有敏感变更都会重新验证当前权限并记录操作结果。
          </Text>
        </div>
      </section>
      <section className="admin-login-form-wrap">
        <Card className="admin-login-card" bordered>
          <Title level={3}>管理员登录</Title>
          <Text type="secondary">请使用独立的管理后台账号。</Text>
          <Form
            layout="vertical"
            requiredMark={false}
            onFinish={async (values: { email: string; password: string }) => {
              try {
                await login(values.email, values.password)
              } catch {
                // Product-safe error is rendered from the session layer.
              }
            }}
          >
            <Form.Item
              label="管理员邮箱"
              name="email"
              rules={[
                { required: true, message: '请输入管理员邮箱' },
                { type: 'email', message: '请输入有效邮箱地址' },
              ]}
            >
              <Input autoComplete="username" size="large" />
            </Form.Item>
            <Form.Item
              label="密码"
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password autoComplete="current-password" size="large" />
            </Form.Item>
            {error && <div className="admin-form-error" role="alert">{error}</div>}
            <Button
              type="primary"
              htmlType="submit"
              size="large"
              block
              loading={loading}
            >
              登录管理后台
            </Button>
          </Form>
          <div className="admin-login-security-note">
            <Text type="secondary">
              管理会话仅用于本后台，退出或权限变更后会立即失效。
            </Text>
          </div>
        </Card>
      </section>
    </main>
  )
}
