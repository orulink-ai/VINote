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
        <label className="mb-2 block text-sm font-medium">{copy.settings.email}</label>
        <div className="flex items-center gap-2 border-y px-1 py-4 text-muted-foreground">
          <Mail className="w-4 h-4" />
          {email || copy.settings.notSignedIn}
        </div>
      </div>
    </div>
  )
}
