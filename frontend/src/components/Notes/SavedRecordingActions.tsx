import { useEffect, useRef, useState } from 'react'
import { Download, Trash2 } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { apiJson } from '../../lib/api'
import { downloadOriginalFile, downloadResultMessage } from '../../lib/recordingDownload'
import { useAuthStore } from '../../stores/authStore'
import { useI18n } from '../../lib/i18n'
import { OriginalLocationButton } from '@/components/OriginalLocationButton'
import { isTauriRuntime } from '@/lib/desktopMicrophonePermission'

type RecordingInfo = { available: boolean; deleted: boolean; can_delete: boolean; filename: string; size_bytes: number }
export function SavedRecordingActions({ noteId, title, onDeleted, compact = false, mediaKind = 'audio' }: {
  noteId: string; title: string; onDeleted: () => void; compact?: boolean; mediaKind?: 'audio' | 'video'
}) {
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')
  const owner = useAuthStore(state => state.user?.id)
  const [info, setInfo] = useState<RecordingInfo | null>(null)
  const [error, setError] = useState('')
  const [errorAction, setErrorAction] = useState<'load' | 'download' | 'delete'>('load')
  const [busy, setBusy] = useState(false)
  const [downloadStatus, setDownloadStatus] = useState('')
  const downloadLock = useRef(false)
  const abort = useRef<AbortController | null>(null)
  const saveButton = useRef<HTMLButtonElement | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const epoch = useRef(0)
  const context = useRef({ noteId, owner })
  context.current = { noteId, owner }
  const guard = () => {
    const request = epoch.current
    return () => request === epoch.current && context.current.noteId === noteId && context.current.owner === owner && useAuthStore.getState().user?.id === owner
  }
  useEffect(() => useAuthStore.subscribe((next, previous) => {
    if (next.user?.id !== previous.user?.id) {
      ++epoch.current; abort.current?.abort(); downloadLock.current = false
      setInfo(null); setError(''); setDownloadStatus(''); setBusy(false); setLoadAttempt(value => value + 1)
    }
  }), [])
  useEffect(() => {
    epoch.current++
    const current = guard()
    downloadLock.current = false; setInfo(null); setError(''); setErrorAction('load'); setDownloadStatus(''); setBusy(false)
    void apiJson<RecordingInfo>(`/api/notes/${noteId}/recording`).then(result => {
      if (!current()) return
      if (!result || typeof result.available !== 'boolean' || typeof result.deleted !== 'boolean') throw new Error(zh ? '原文件状态未核验，请重新读取。' : 'Original status is unverified. Reload it.')
      setInfo(result)
    }).catch(cause => { if (current()) setError(cause instanceof Error ? cause.message : String(cause)) })
    return () => { epoch.current++; abort.current?.abort() }
  }, [noteId, owner, loadAttempt])

  const download = async () => {
    if (downloadLock.current) return
    downloadLock.current = true
    const downloadEpoch = epoch.current
    const current = guard()
    const controller = new AbortController(); abort.current = controller
    setBusy(true); setError(''); setErrorAction('download'); setDownloadStatus(zh ? '正在准备并导出原文件…' : 'Preparing and exporting original…')
    try {
      const result = await downloadOriginalFile(`/api/notes/${noteId}/media`, info?.filename || `${title}.${mediaKind === 'video' ? 'webm' : 'm4a'}`, current, controller.signal)
      if (current()) {
        setDownloadStatus(downloadResultMessage(result, zh))
        if (result === 'cancelled') window.setTimeout(() => { if (current()) saveButton.current?.focus() }, 0)
      }
    } catch (cause) { if (current()) { setDownloadStatus(''); setError(cause instanceof Error ? cause.message : String(cause)) } }
    finally { if (downloadEpoch === epoch.current) { downloadLock.current = false; setBusy(false) } }
  }

  const remove = async () => {
    const current = guard()
    setBusy(true); setError(''); setErrorAction('delete'); setDownloadStatus('')
    try {
      await apiJson(`/api/notes/${noteId}/recording`, { method: 'DELETE' })
      if (!current()) return
      document.querySelectorAll<HTMLMediaElement>('audio, video').forEach(media => {
        if (media.currentSrc.includes(`/api/notes/${noteId}/media`) || media.src.includes(`/api/notes/${noteId}/media`)) {
          media.pause(); media.removeAttribute('src'); media.load()
        }
      })
      setInfo(info ? { ...info, available: false, deleted: true } : null)
      onDeleted()
    } catch (cause) { if (current()) setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { if (current()) setBusy(false) }
  }
  const label = mediaKind === 'video' ? zh ? '导出原视频' : 'Export original video' : zh ? '导出原音频' : 'Export original audio'
  const status = info?.available
    ? (zh ? '原文件已保留' : 'Original retained') + (Number.isFinite(info.size_bytes) ? ` · ${(info.size_bytes / 1024 / 1024).toFixed(1)} MB` : '')
    : info?.deleted ? zh ? '文件已删除，纪要和转写已保留' : 'Recording deleted; notes and transcript retained'
    : error ? zh ? '原文件状态未读取' : 'Recording status unavailable'
    : info ? zh ? '暂无可用原文件' : 'Original unavailable'
    : zh ? '正在读取原文件状态…' : 'Loading original…'
  return <div className={compact ? 'grid gap-3' : 'grid min-w-0 gap-3 border-b pb-4'}>
    <OriginalLocationButton url={`/api/notes/${noteId}/media`} disabled={busy || !info?.available} zh={zh} />
    <Button ref={saveButton} className={compact ? 'w-full' : undefined} variant="outline" disabled={busy || !info?.available} aria-busy={busy} onClick={() => void download()}><Download />{busy ? errorAction === 'delete' ? zh ? '正在处理…' : 'Processing…' : zh ? '正在保存…' : 'Saving…' : isTauriRuntime() ? zh ? '另存为…' : 'Save as…' : label}</Button>
    {busy && downloadStatus && <Button variant="ghost" onClick={() => abort.current?.abort()}>{zh ? '取消导出' : 'Cancel export'}</Button>}
    <p role="status" aria-live="polite" className="text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">{downloadStatus || status}</p>
    {!compact && info?.available && info.can_delete && <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer py-2">{zh ? mediaKind === 'video' ? '管理原视频' : '管理原录音' : 'Manage original'}</summary>
      <AlertDialog><AlertDialogTrigger asChild><Button variant="ghost" size="sm" disabled={busy} className="text-destructive hover:text-destructive"><Trash2 />{zh ? '删除录制' : 'Delete recording'}</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{zh ? '删除录制文件？' : 'Delete recording?'}</AlertDialogTitle><AlertDialogDescription>{zh ? '录制及音频副本会永久删除，文字纪要、转写和截图会保留。' : 'The recording is permanently deleted. Notes, transcript and screenshots are retained.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{zh ? '取消' : 'Cancel'}</AlertDialogCancel><AlertDialogAction onClick={() => void remove()}>{zh ? '确认删除' : 'Delete'}</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </details>}
    {!compact && info?.available && !info.can_delete && <p className="text-xs text-muted-foreground">{zh ? '共用或无法验证归属的文件仅支持导出。' : 'Shared or unverified originals can only be exported.'}</p>}
    {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription><Button variant="outline" size="sm" disabled={busy} onClick={() => errorAction === 'download' ? void download() : setLoadAttempt(value => value + 1)}>{errorAction === 'download' ? isTauriRuntime() ? zh ? '重试另存为…' : 'Retry save as…' : zh ? '重试导出' : 'Retry export' : errorAction === 'delete' ? zh ? '重新核验原文件' : 'Check original status' : zh ? '重新加载录制' : 'Reload recording'}</Button></Alert>}
  </div>
}
