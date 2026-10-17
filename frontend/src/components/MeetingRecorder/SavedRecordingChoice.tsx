import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { getPendingMeeting, type PendingMeeting } from '../../lib/audioStorage'
import { LocalRecordingPreview } from './LocalRecordingPreview'
import { resolvePageParent } from '../../lib/navigation'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '../ui/sheet'
import { Button } from '../ui/button'
import { useAuthStore } from '../../stores/authStore'
import { useI18n } from '../../lib/i18n'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'

/** The route also hands a saved compatibility-window recording back to the main window. */
export function SavedRecordingChoice() {
  const [params, setParams] = useSearchParams()
  const confirmId = params.get('recordingConfirm')
  const id = confirmId || params.get('recordingSaved')
  const navigate = useNavigate()
  const userId = useAuthStore(state => state.user?.id)
  const [recording, setRecording] = useState<PendingMeeting | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const { locale } = useI18n()
  const zh = locale.startsWith('zh')

  useEffect(() => {
    let active = true
    setRecording(null); setError(''); setLoading(!!id)
    if (id && userId) void getPendingMeeting(id).then(row => {
      if (!active || useAuthStore.getState().user?.id !== userId) return
      if (!row || row.id !== id || row.ownerId !== userId || row.recordingStatus !== 'saved') { setError('此录制不可用或不属于当前账号，请返回会议列表。'); return }
      if (confirmId || row.processingStatus === 'idle') setRecording(row)
    }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '读取录制失败，请重试。') })
      .finally(() => { if (active) setLoading(false) })
    else setLoading(false)
    return () => { active = false }
  }, [id, userId, confirmId, attempt])

  const dismiss = () => {
    setRecording(null)
    const parent = resolvePageParent(params.get('returnTo'), '')
    if (confirmId && parent && !parent.startsWith('/meetings')) { navigate(parent, { replace: true }); return }
    setParams(current => { const next = new URLSearchParams(current); next.delete('recordingSaved'); next.delete('recordingConfirm'); return next }, { replace: true })
  }

  if (confirmId) return <Sheet open={!!userId} onOpenChange={open => { if (!open) dismiss() }}><SheetContent className="w-full overflow-y-auto sm:max-w-xl"><SheetHeader><SheetTitle>录制详情</SheetTitle><SheetDescription>核对原录制与本次模型，确认后生成；原件继续保留。</SheetDescription></SheetHeader><div className="grid gap-4 pt-6">
    {loading && <p role="status">正在读取原录制…</p>}
    {error && <><p role="alert">{error}</p><Button variant="outline" onClick={() => setAttempt(value => value + 1)}>重新读取原录制</Button></>}
    {!loading && !error && recording && recording.ownerId === userId && recording.id === confirmId && <><h2 className="font-medium">{recording.options.title}</h2><LocalRecordingPreview key={`${userId}:${recording.id}`} recording={recording} confirmOnOpen={!!recording.generationConfirmationRequired || (!recording.taskId && !recording.generationOperation)} onRecordingUpdated={next => { if (next.id === confirmId && next.ownerId === useAuthStore.getState().user?.id) setRecording(next) }} onDeleted={dismiss} onOpenNote={noteId => navigate(`/note/${encodeURIComponent(noteId)}`, { state: { returnTo: '/meetings' } })} /></>}
    <Button variant="ghost" onClick={dismiss}>返回来源页面</Button>
  </div></SheetContent></Sheet>

  return <AlertDialog open={!!recording && recording.ownerId === userId} onOpenChange={open => { if (!open) dismiss() }}>
    <AlertDialogContent>
      <AlertDialogHeader>
        <AlertDialogTitle>{zh ? '录制已保存，生成会议纪要？' : 'Recording saved. Generate meeting notes?'}</AlertDialogTitle>
        <AlertDialogDescription>{zh ? '录制已保存。现在生成会议纪要，或稍后从会议列表继续。' : 'Recording saved. Generate meeting minutes now, or continue later from Meetings.'}</AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter>
        <AlertDialogCancel>{zh ? '暂不生成' : 'Not now'}</AlertDialogCancel>
        <AlertDialogAction onClick={event => { event.preventDefault(); const row = recording; if (row && row.ownerId === userId) setParams(current => { const next = new URLSearchParams(current); next.delete('recordingSaved'); next.set('recordingConfirm', row.id); return next }, { replace: true }) }}>{zh ? '生成会议纪要' : 'Generate meeting notes'}</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>
}
