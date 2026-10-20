import { useEffect, useRef, useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { downloadOriginalFile, downloadResultMessage } from '@/lib/recordingDownload'
import { useAuthStore } from '@/stores/authStore'
import { OriginalLocationButton } from './OriginalLocationButton'
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission'

/** Mount with a key for the selected owner/file. Export always uses the original URL. */
export function OriginalDownloadButton({ url, filename }: { url: string; filename: string }) {
  const owner = useAuthStore(state => state.user?.id)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const locked = useRef(false)
  const epoch = useRef(0)
  const abort = useRef<AbortController | null>(null)
  const saveButton = useRef<HTMLButtonElement | null>(null)
  useEffect(() => { epoch.current++; locked.current = false; setBusy(false); setMessage(''); setError(''); return () => { epoch.current++; abort.current?.abort() } }, [owner, url, filename])
  useEffect(() => useAuthStore.subscribe((next, previous) => {
    if (next.user?.id !== previous.user?.id) {
      ++epoch.current; abort.current?.abort(); locked.current = false
      setBusy(false); setMessage(''); setError('')
    }
  }), [])
  const download = async () => {
    if (locked.current) return
    locked.current = true
    const snapshot = epoch.current
    const current = () => snapshot === epoch.current && owner === useAuthStore.getState().user?.id
    const controller = new AbortController(); abort.current = controller
    setBusy(true); setError(''); setMessage('正在准备并导出原文件…')
    try {
      const result = await downloadOriginalFile(url, filename, current, controller.signal)
      if (current()) {
        setMessage(downloadResultMessage(result))
        if (result === 'cancelled') window.setTimeout(() => { if (current()) saveButton.current?.focus() }, 0)
      }
    } catch (cause) {
      if (current()) { setMessage(''); setError(cause instanceof Error ? cause.message : String(cause)) }
    } finally { if (snapshot === epoch.current) { locked.current = false; setBusy(false) } }
  }
  return <div className="grid gap-2">
    <OriginalLocationButton url={url} disabled={busy} />
    <Button ref={saveButton} variant="outline" disabled={busy} aria-busy={busy} onClick={() => void download()}>{busy ? <Loader2 className="animate-spin" /> : <Download />}{busy ? '正在保存…' : isTauriRuntime() ? error ? '重试另存为…' : '另存为…' : error ? '重试导出原文件' : '导出原文件'}</Button>
    {busy && <Button variant="ghost" onClick={() => abort.current?.abort()}>取消导出</Button>}
    {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>
}
