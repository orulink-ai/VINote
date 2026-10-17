import { useEffect, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'

export function SessionConnection() {
  const { status, sessionError, initialize } = useAuthStore()
  const [busy, setBusy] = useState(false)
  const retry = async () => { setBusy(true); try { await initialize() } finally { setBusy(false) } }
  useEffect(() => {
    const reconnect = () => { void useAuthStore.getState().initialize() }
    window.addEventListener('online', reconnect)
    return () => window.removeEventListener('online', reconnect)
  }, [])
  if (status !== 'offline-known') return null
  return <Alert className="shrink-0 rounded-none border-x-0 border-t-0"><AlertDescription className="flex flex-wrap items-center justify-between gap-3"><span>{sessionError} 当前为离线状态；本机内容仍可使用。</span><Button variant="outline" disabled={busy} onClick={() => void retry()}>{busy ? '正在核验…' : '重新连接'}</Button></AlertDescription></Alert>
}
