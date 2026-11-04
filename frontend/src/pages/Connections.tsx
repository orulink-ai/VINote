import { Navigate, useLocation, useSearchParams } from 'react-router-dom'
import { resolvePageParent } from '@/lib/navigation'

/** Legacy plugin URLs retain their return context, never dispatch tool operations. */
export function Connections() {
  const [params] = useSearchParams()
  const location = useLocation()
  const parent = resolvePageParent(params.get('returnTo') || (location.state as { returnTo?: string } | null)?.returnTo, '')
  const returnTo = parent && !['/connections', '/settings/mcp', '/settings/feishu'].includes(parent.split('?')[0]) ? parent : ''
  return <Navigate replace to={'/settings/feishu' + (returnTo ? '?' + new URLSearchParams({ returnTo }) : '')} />
}
