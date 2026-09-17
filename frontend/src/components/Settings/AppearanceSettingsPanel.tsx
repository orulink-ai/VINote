import { Moon, Monitor, Sun } from 'lucide-react'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useI18n } from '../../lib/i18n'
import type { LanguageCode } from '../../stores/languageStore'
type ThemeMode = 'light' | 'dark' | 'system'
interface Props { theme: ThemeMode; language: LanguageCode; onThemeChange: (theme: ThemeMode) => void; onLanguageChange: (language: LanguageCode) => void | Promise<void> }
export function AppearanceSettingsPanel({ theme, language, onThemeChange, onLanguageChange }: Props) {
  const { copy } = useI18n(); const themes = [{ value: 'light', label: copy.theme.light, icon: Sun }, { value: 'dark', label: copy.theme.dark, icon: Moon }, { value: 'system', label: copy.theme.system, icon: Monitor }] as const
  return <div className="divide-y"><section className="pb-6"><h3 className="font-medium">{copy.theme.title}</h3><p className="mt-1 text-sm text-muted-foreground">选择桌面端的显示外观。</p><ToggleGroup type="single" value={theme} onValueChange={value => value && onThemeChange(value as ThemeMode)} className="mt-4 grid grid-cols-3">{themes.map(item => <ToggleGroupItem key={item.value} value={item.value} className="h-16 flex-col"><item.icon />{item.label}</ToggleGroupItem>)}</ToggleGroup></section><section className="pt-6"><h3 className="font-medium">{copy.language.title}</h3><p className="mt-1 text-sm text-muted-foreground">更改界面语言。</p><ToggleGroup type="single" value={language} onValueChange={value => value && void onLanguageChange(value as LanguageCode)} className="mt-4 grid grid-cols-2"><ToggleGroupItem value="zh-CN">{copy.language.chinese}</ToggleGroupItem><ToggleGroupItem value="en">{copy.language.english}</ToggleGroupItem></ToggleGroup></section></div>
}
