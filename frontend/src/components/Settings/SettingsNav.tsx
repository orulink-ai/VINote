import { Bell, Bot, Palette, User, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useI18n } from '../../lib/i18n'

export type SettingsTab = 'profile' | 'models' | 'appearance' | 'notifications'

type TabConfig = {
  key: SettingsTab
  label: string
  icon: LucideIcon
}

interface SettingsNavProps {
  activeTab: SettingsTab
  onChange: (tab: SettingsTab) => void
}

export function SettingsNav({ activeTab, onChange }: SettingsNavProps) {
  const { copy } = useI18n()
  const tabs: TabConfig[] = [
    { key: 'profile', label: copy.settings.profile, icon: User },
    { key: 'models', label: copy.settings.models, icon: Bot },
    { key: 'appearance', label: copy.settings.appearance, icon: Palette },
    { key: 'notifications', label: copy.settings.notifications, icon: Bell },
  ]

  return (
    <nav className="flex w-full shrink-0 gap-1 overflow-x-auto lg:sticky lg:top-6 lg:w-52 lg:flex-col lg:self-start">
      {tabs.map((tab) => (
        <Button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          variant={activeTab === tab.key ? 'secondary' : 'ghost'}
          className="min-w-max justify-start lg:w-full"
        >
          <tab.icon className="w-4 h-4" />
          {tab.label}
        </Button>
      ))}
    </nav>
  )
}
