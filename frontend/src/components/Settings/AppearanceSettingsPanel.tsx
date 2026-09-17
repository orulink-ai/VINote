import { Moon, Monitor, Sun } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useI18n } from '../../lib/i18n'
import type { LanguageCode } from '../../stores/languageStore'
type ThemeMode = 'light' | 'dark' | 'system'
interface Props { theme: ThemeMode; language: LanguageCode; onThemeChange: (theme: ThemeMode) => void; onLanguageChange: (language: LanguageCode) => void | Promise<void> }
export function AppearanceSettingsPanel({ theme, language, onThemeChange, onLanguageChange }: Props) {
  const { copy } = useI18n(); const themes = [{ value: 'light', label: copy.theme.light, icon: Sun }, { value: 'dark', label: copy.theme.dark, icon: Moon }, { value: 'system', label: copy.theme.system, icon: Monitor }] as const
  return <div className="grid gap-6"><Card><CardHeader><CardTitle>{copy.theme.title}</CardTitle><CardDescription>选择桌面端的显示外观。</CardDescription></CardHeader><CardContent><ToggleGroup type="single" value={theme} onValueChange={value => value && onThemeChange(value as ThemeMode)} className="grid grid-cols-3">{themes.map(item => <ToggleGroupItem key={item.value} value={item.value} className="h-20 flex-col"><item.icon />{item.label}</ToggleGroupItem>)}</ToggleGroup></CardContent></Card><Card><CardHeader><CardTitle>{copy.language.title}</CardTitle><CardDescription>更改界面语言。</CardDescription></CardHeader><CardContent><ToggleGroup type="single" value={language} onValueChange={value => value && void onLanguageChange(value as LanguageCode)} className="grid grid-cols-2"><ToggleGroupItem value="zh-CN">{copy.language.chinese}</ToggleGroupItem><ToggleGroupItem value="en">{copy.language.english}</ToggleGroupItem></ToggleGroup></CardContent></Card></div>
}
