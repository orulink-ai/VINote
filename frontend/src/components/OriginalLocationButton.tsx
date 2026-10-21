import { useEffect, useRef, useState } from 'react'
import { FolderOpen, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission'
import { revealOriginalFile } from '@/lib/originalLocation'
import { useAuthStore } from '@/stores/authStore'

type Props = ({ url: string; taskId?: never } | { taskId: string; url?: never }) & { disabled?: boolean; zh?: boolean }
export function OriginalLocationButton(props: Props) {
  const owner = useAuthStore(state => state.user?.id)
  if (!isTauriRuntime()) return null
  return <OriginalLocationAction key={JSON.stringify([owner, props.url, props.taskId])} {...props} owner={owner} />
}
function OriginalLocationAction({ url, taskId, disabled = false, zh = true, owner }: Props & { owner?: string }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('')
  const sequence = useRef(0), locked = useRef(false), abort = useRef<AbortController | null>(null)
  const context = useRef({ owner, url, taskId, disabled }); context.current = { owner, url, taskId, disabled }
  useEffect(() => {
    ++sequence.current; setBusy(false); setMessage(''); setError('')
    return () => { ++sequence.current; abort.current?.abort() }
  }, [owner, url, taskId])
  useEffect(() => useAuthStore.subscribe((next, previous) => {
    if (next.user?.id !== previous.user?.id) {
      ++sequence.current; abort.current?.abort(); locked.current = false
      setBusy(false); setMessage(''); setError('')
    }
  }), [])
  const reveal = async () => {
    if (locked.current || disabled || !owner) return
    locked.current = true
    const request = sequence.current, controller = new AbortController(); abort.current = controller
    const current = () => request === sequence.current && context.current.owner === owner && context.current.url === url && context.current.taskId === taskId
      && !context.current.disabled && useAuthStore.getState().user?.id === owner
    setBusy(true); setMessage(''); setError('')
    try {
      const result = await revealOriginalFile(taskId ? { taskId } : url!, current, controller.signal)
      if (current() && result === 'shown') setMessage(zh ? '已打开文件所在文件夹，并定位原文件。' : 'Opened the containing folder and selected the original.')
    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { if (request === sequence.current) { locked.current = false; setBusy(false) } }
  }
  return <div className="grid min-w-0 gap-2">
    <Button variant="outline" disabled={disabled || busy || !owner} aria-busy={busy} onClick={() => void reveal()}>
      {busy ? <Loader2 className="size-4 animate-spin" /> : <FolderOpen className="size-4" />}
      {busy ? zh ? '正在打开文件夹…' : 'Opening folder…' : zh ? '在文件夹中显示' : 'Show in folder'}
    </Button>
    {message && <p role="status" className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{message}</p>}
    {error && <p role="alert" className="text-xs text-destructive [overflow-wrap:anywhere]">{error}</p>}
  </div>
}
