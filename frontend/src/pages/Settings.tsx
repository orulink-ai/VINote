import { useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { ModelSourcePanel } from '../components/Settings/ModelSourcePanel'
import { Settings2 } from 'lucide-react'
import { Badge } from '../components/ui/badge'
import { AppearanceSettingsPanel } from '../components/Settings/AppearanceSettingsPanel'
import { NotificationSettingsPanel } from '../components/Settings/NotificationSettingsPanel'
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
    <div className="mx-auto w-full max-w-[1380px] p-6 lg:p-10">
      <div className="motion-rise mb-8"><Badge variant="secondary" className="mb-4"><Settings2 />偏好与服务</Badge><h2 className="text-3xl font-semibold tracking-tight">{copy.settings.title}</h2><p className="mt-2 text-sm text-muted-foreground">管理账号、模型、外观和通知偏好。团队与共享在团队页面管理。</p></div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <SettingsNav activeTab={activeTab} onChange={setActiveTab} />

        <section key={activeTab} className="motion-rise min-w-0 flex-1 rounded-2xl border bg-card shadow-sm"><div className="p-6 lg:p-8">
          {activeTab === 'profile' && <ProfileSettingsPanel email={user?.email} />}
          {activeTab === 'models' && (
            <ModelSourcePanel />
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
