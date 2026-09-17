import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Field, FieldContent, FieldLabel, FieldTitle } from '@/components/ui/field'
import { Switch } from '@/components/ui/switch'
import { useI18n } from '../../lib/i18n'
export function NotificationSettingsPanel() { const { copy } = useI18n(); const items = [[copy.settings.notifyFinished, true], [copy.settings.notifyInvites, true], [copy.settings.emailNotifications, false]] as const; return <Card><CardHeader><CardTitle>{copy.settings.notificationsTitle}</CardTitle></CardHeader><CardContent className="grid gap-3">{items.map(([label, checked], index) => <Field key={label} orientation="horizontal" className="rounded-xl border p-4"><FieldContent><FieldLabel htmlFor={`notification-${index}`}><FieldTitle>{label}</FieldTitle></FieldLabel></FieldContent><Switch id={`notification-${index}`} defaultChecked={checked} /></Field>)}</CardContent></Card> }
