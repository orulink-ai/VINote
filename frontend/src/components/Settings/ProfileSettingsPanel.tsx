import { Mail } from 'lucide-react'
import { useI18n } from '../../lib/i18n'

interface ProfileSettingsPanelProps {
  email?: string
}

export function ProfileSettingsPanel({ email }: ProfileSettingsPanelProps) {
  const { copy } = useI18n()

  return (
    <div>
      <div>
        <p className="mb-2 text-sm font-medium">{copy.settings.email}</p>
        <div className="flex min-w-0 items-center gap-2 rounded-lg bg-muted px-3 py-3 text-sm">
          <Mail className="w-4 h-4" />
          <span className="min-w-0 break-all">{email || copy.settings.notSignedIn}</span>
        </div>
      </div>
    </div>
  )
}
