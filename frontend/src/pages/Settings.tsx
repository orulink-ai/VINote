import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ModelSourcePanel } from '../components/Settings/ModelSourcePanel'
import { Settings2, Shield } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { AppearanceSettingsPanel } from '../components/Settings/AppearanceSettingsPanel'
import { NotificationSettingsPanel } from '../components/Settings/NotificationSettingsPanel'
import { PlaceholderSettingsPanel } from '../components/Settings/PlaceholderSettingsPanel'
import { ProfileSettingsPanel } from '../components/Settings/ProfileSettingsPanel'
import { SettingsNav, type SettingsTab } from '../components/Settings/SettingsNav'
import { useI18n } from '../lib/i18n'
import { useAuthStore } from '../stores/authStore'
import { useThemeStore } from '../stores/themeStore'

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('profile')
  const location = useLocation()
  useEffect(() => { if (new URLSearchParams(location.search).get('tab') === 'models') setActiveTab('models') }, [location.search])
  const { user } = useAuthStore()
  const { theme, setTheme } = useThemeStore()
  const { copy, language, setLanguage } = useI18n()

  return (
    <div className="mx-auto w-full max-w-[1180px] p-6 lg:p-10">
      <div className="mb-7 border-b pb-6"><Badge variant="secondary" className="mb-3"><Settings2 />工作区设置</Badge><h2 className="text-2xl font-semibold tracking-tight">{copy.settings.title}</h2><p className="mt-2 text-sm text-muted-foreground">管理账号、模型、外观和通知偏好。</p></div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <SettingsNav activeTab={activeTab} onChange={setActiveTab} />

        <section className="min-w-0 flex-1 border"><header className="border-b px-6 py-4"><h3 className="text-sm font-semibold">{copy.settings.title}</h3></header><div className="p-6 lg:p-8">
          {activeTab === 'profile' && <ProfileSettingsPanel email={user?.email} />}
          {activeTab === 'models' && (
            <ModelSourcePanel />
          )}
          {activeTab === 'team' && (
            <PlaceholderSettingsPanel
              icon={Shield}
              title={copy.settings.team}
              body={copy.settings.teamBody}
            />
          )}
          {activeTab === 'appearance' && (
            <AppearanceSettingsPanel
              theme={theme}
              language={language}
              onThemeChange={setTheme}
              onLanguageChange={setLanguage}
            />
          )}
          {activeTab === 'notifications' && <NotificationSettingsPanel />}
        </div></section>
      </div>
    </div>
  )
}
