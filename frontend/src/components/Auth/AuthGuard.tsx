import { Navigate, useLocation } from 'react-router-dom'
import { useAuthStore } from '../../stores/authStore'
import { ErrorState, LoadingState } from '../Feedback/ResourceState'

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, initialized, status, sessionError, initialize } = useAuthStore()
  const location = useLocation()

  if (!initialized) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingState rows={0} label="正在验证登录…" />
      </div>
    )
  }

  if (!user && status === 'checking' && sessionError) {
    return <div className="mx-auto flex min-h-full max-w-lg items-center p-6"><ErrorState title="连接暂不可用" error={sessionError} onRetry={() => void initialize()} retryLabel="重新验证登录" /></div>
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}
