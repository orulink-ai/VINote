import { useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { Switch } from '@/components/ui/switch'
import { Button } from '@/components/ui/button'
import { backgroundNotificationsEnabled, setBackgroundNotifications } from '@/lib/taskNotifications'
import { enableNativeNotifications } from '@/lib/nativeTaskNotification'
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission'
export function NotificationSettingsPanel() {
  const owner = useAuthStore(state => state.user?.id)
  return <NotificationPreferences key={owner} owner={owner} />
}
function NotificationPreferences({ owner }: { owner?: string }) {
  const [enabled, setEnabled] = useState(() => owner ? backgroundNotificationsEnabled(owner) : false)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  return <section><h3 className="font-medium">任务通知</h3><p className="mt-2 text-sm text-muted-foreground">完成或失败时提醒一次。前台在应用内提示，点击可查看结果或继续恢复原任务。</p>
    <div className="mt-4 flex items-center justify-between gap-4 border-y py-4"><label htmlFor="background-notifications">后台使用系统通知</label><Switch id="background-notifications" checked={enabled} disabled={!owner || !isTauriRuntime()} onCheckedChange={value => { if (owner) { setBackgroundNotifications(owner, value); setEnabled(value) } }} /></div>
    {isTauriRuntime() ? <Button className="mt-3" variant="outline" disabled={busy || !owner || !enabled} onClick={async () => { setBusy(true); try { const granted = await enableNativeNotifications(); setMessage(granted ? '系统通知权限已开启。' : '未获得系统权限，结果仍会在应用内提示。') } catch { setMessage('系统通知暂不可用，结果仍会在应用内提示。') } finally { setBusy(false) } }}>启用系统通知权限</Button> : <p className="mt-3 text-sm text-muted-foreground">系统通知可在桌面应用中启用；当前使用应用内提示。</p>}
    {message && <p role="status" className="mt-2 text-sm">{message}</p>}
  </section>
}
