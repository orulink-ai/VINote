import { ArrowLeft } from 'lucide-react'
import { contextualPageParent, resolvePageParent, pageParentLabel } from '@/lib/navigation'
import { useLocation } from 'react-router-dom'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

/** Return to an explicit parent, including when opened from a deep link. */
export function PageReturn({ to, label, contextual = true }: { to: string; label: string; contextual?: boolean }) {
  const location = useLocation()
  const parent = (contextual ? contextualPageParent(location.pathname, location.search, location.state?.returnTo) : null) || resolvePageParent(to)
  return <div><Button asChild variant="ghost" size="sm">
    <Link to={parent}><ArrowLeft data-icon="inline-start" />{parent === to ? label : pageParentLabel(parent)}</Link>
  </Button></div>
}
