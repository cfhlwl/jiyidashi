import { Navigate, Route, Routes } from 'react-router-dom'
import { fixtureMode } from './api'
import { AdminShell, Loading } from './components/AdminUi'
import { AdminSessionProvider, useAdminSession } from './session'
import { AdminAccountsPage } from './pages/AdminAccountsPage'
import { AiServicesPage } from './pages/AiServicesPage'
import { AuditPage } from './pages/AuditPage'
import { DashboardPage } from './pages/DashboardPage'
import { DataTasksPage } from './pages/DataTasksPage'
import { EntitlementsPage } from './pages/EntitlementsPage'
import { FamiliesPage } from './pages/FamiliesPage'
import { FamilyDetailPage } from './pages/FamilyDetailPage'
import { LoginPage } from './pages/LoginPage'
import { ReviewStatePage } from './pages/ReviewStatePage'
import { SecurityCenterPage } from './pages/SecurityCenterPage'
import { SettingsPage } from './pages/SettingsPage'
import { StoragePage } from './pages/StoragePage'
import { SystemHealthPage } from './pages/SystemHealthPage'
import { UserDetailPage } from './pages/UserDetailPage'
import { UsersPage } from './pages/UsersPage'

function ProtectedApp() {
  const { loading, session } = useAdminSession()
  if (loading) return <Loading title="正在验证管理会话" />
  if (!session) return <Navigate to="/login" replace />

  return (
    <AdminShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/users/:id" element={<UserDetailPage />} />
        <Route path="/families" element={<FamiliesPage />} />
        <Route path="/families/:id" element={<FamilyDetailPage />} />
        <Route path="/entitlements" element={<EntitlementsPage />} />
        <Route path="/data-tasks" element={<DataTasksPage />} />
        <Route path="/security" element={<SecurityCenterPage />} />
        <Route path="/ai-services" element={<AiServicesPage />} />
        <Route path="/storage" element={<StoragePage />} />
        <Route path="/system-health" element={<SystemHealthPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admins" element={<AdminAccountsPage />} />
        {fixtureMode && (
          <>
            <Route path="/review/empty" element={<ReviewStatePage state="empty" />} />
            <Route path="/review/loading" element={<ReviewStatePage state="loading" />} />
            <Route path="/review/error" element={<ReviewStatePage state="error" />} />
            <Route path="/review/permission" element={<ReviewStatePage state="permission" />} />
            <Route path="/review/danger" element={<ReviewStatePage state="danger" />} />
          </>
        )}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AdminShell>
  )
}

function RoutedApp() {
  const { loading, session } = useAdminSession()
  const reviewLogin = fixtureMode && window.location.search.includes('review=login')
  return (
    <Routes>
      <Route
        path="/login"
        element={
          loading || !session || reviewLogin ? <LoginPage /> : <Navigate to="/" replace />
        }
      />
      <Route path="/*" element={<ProtectedApp />} />
    </Routes>
  )
}

export function App() {
  return (
    <AdminSessionProvider>
      <RoutedApp />
    </AdminSessionProvider>
  )
}
