import { invoke } from '@tauri-apps/api/core'
import { isPermissionGranted, onAction, requestPermission } from '@tauri-apps/plugin-notification'
import { isTauriRuntime } from './desktopMicrophonePermission'
export async function enableNativeNotifications() {
  if (!isTauriRuntime()) return false
  return await isPermissionGranted() || await requestPermission() === 'granted'
}
export async function deliverNativeNotification(id: number, title: string, current: () => boolean = () => true) {
  if (!isTauriRuntime() || !await isPermissionGranted()) return false
  if (!current()) return false
  await invoke('plugin:notification|notify', { options: { id, title, body: '打开 VINote 查看结果', extra: {} } })
  return true
}
export async function listenNativeNotification(open: (id: number) => void) {
  if (!isTauriRuntime()) return () => undefined
  const listener = await onAction(event => { if (typeof event.notification?.id === 'number') open(event.notification.id) })
  return () => { void listener.unregister() }
}
export async function focusNotificationWindow() {
  if (isTauriRuntime()) await invoke('show_main_window')
}
