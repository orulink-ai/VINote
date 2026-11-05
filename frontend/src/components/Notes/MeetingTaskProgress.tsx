import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiJson } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import { useNoteLibraryStore, type NoteRecord } from '@/stores/noteLibraryStore'
import { Button } from '@/components/ui/button'
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from '@/components/ui/alert-dialog'

type Task = { task_id?: string; status: string; stage?: string; message?: string; processed_seconds?: number | null; total_seconds?: number | null; updated_at?: string; result?: { task_id?: string; title?: string; markdown?: string } }
const stages: Record<string, [string, string]> = {
  pending: ['等待处理', 'Waiting to process'], queued: ['排队等待', 'Queued'], downloading: ['下载原文件', 'Downloading original'],
  preparing: ['准备录音', 'Preparing recording'], preparing_media: ['准备媒体', 'Preparing media'], uploaded: ['等待处理', 'Waiting to process'],
  transcribing: ['正在转写', 'Transcribing'], diarizing: ['识别发言人', 'Identifying speakers'], parallel_analysis: ['分析会议', 'Analyzing meeting'],
  aligning: ['对齐发言', 'Aligning speech'], analyzing_video: ['分析画面', 'Analyzing video'], summarizing: ['生成纪要', 'Generating notes'],
  screenshots: ['提取画面', 'Extracting frames'], saving: ['保存纪要', 'Saving notes'], saving_result: ['保存纪要', 'Saving notes'],
  failed: ['处理未完成', 'Processing failed'], error: ['处理未完成', 'Processing failed'], success: ['处理已完成，等待保存纪要', 'Processing complete; awaiting saved notes'],
}
const duration = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`

/** Only reads the original task; never resumes, regenerates or publishes it. */
export function MeetingTaskProgress({ note, returnTo, zh, onSaved, hasUnsavedChanges = false }: { note: NoteRecord; returnTo: string; zh: boolean; onSaved?: (note: NoteRecord) => void; hasUnsavedChanges?: boolean }) {
  const { loadNoteById } = useNoteLibraryStore()
  const owner = useAuthStore(state => state.user?.id)
  const origin = useAppModeStore(state => state.config?.server_url)
  const binding = JSON.stringify([owner, origin, note.id, note.taskId, returnTo])
  const [snapshot, setSnapshot] = useState<{ binding: string; task?: Task; error?: boolean; saved?: NoteRecord }>({ binding: '' })
  const [discardBinding, setDiscardBinding] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let savedReadTimeout: ReturnType<typeof setTimeout> | undefined
    const active = () => !controller.signal.aborted && owner === useAuthStore.getState().user?.id && origin === useAppModeStore.getState().config?.server_url
    setSnapshot({ binding })
    const readSaved = async (task: Task) => {
      try {
        const saved = await Promise.race([loadNoteById(note.id, { fresh: true }), new Promise<null>(resolve => { savedReadTimeout = setTimeout(() => resolve(null), 15000) })])
        clearTimeout(savedReadTimeout)
        if (!active()) return
        if (saved?.id === note.id && saved.taskId === note.taskId && saved.status === 'done' && saved.content.trim()) {
          setSnapshot({ binding, task, saved })
          return
        }
      } catch { clearTimeout(savedReadTimeout); /* Saved-note read failures do not replay generation. */ }
      if (active()) timer = setTimeout(() => void readSaved(task), 5000)
    }
    const read = async () => {
      const request = new AbortController()
      const cancel = () => request.abort()
      controller.signal.addEventListener('abort', cancel, { once: true })
      const timeout = setTimeout(cancel, 15000)
      try {
        const task = await apiJson<Task>(`/api/task/${encodeURIComponent(note.taskId!)}`, { signal: request.signal })
        if (!active()) return
        if ((task.task_id && task.task_id !== note.taskId) || !stages[task.status]) throw new Error('Unverified task')
        if (task.status === 'success' && (!task.result?.title?.trim() || !task.result.markdown?.trim() || (task.result.task_id && task.result.task_id !== note.taskId))) throw new Error('Incomplete task result')
        setSnapshot({ binding, task })
        if (task.status === 'success') void readSaved(task)
        if (!['success', 'failed', 'error'].includes(task.status)) timer = setTimeout(() => void read(), 5000)
      } catch {
        if (active()) setSnapshot({ binding, error: true })
      } finally { clearTimeout(timeout); controller.signal.removeEventListener('abort', cancel) }
    }
    if (owner && note.taskId) void read()
    const clock = setInterval(() => setNow(Date.now()), 1000)
    return () => { controller.abort(); clearTimeout(timer); clearTimeout(savedReadTimeout); clearInterval(clock) }
  }, [binding, attempt])
  const task = snapshot.binding === binding ? snapshot.task : undefined
  const saved = snapshot.binding === binding ? snapshot.saved : undefined
  const error = snapshot.binding === binding && snapshot.error
  const stage = task && (['success', 'failed', 'error'].includes(task.status) ? stages[task.status] : stages[task.stage || task.status] || stages[task.status])
  const measured = task?.status === 'transcribing' && typeof task.processed_seconds === 'number' && Number.isFinite(task.processed_seconds) && task.processed_seconds >= 0 && typeof task.total_seconds === 'number' && Number.isFinite(task.total_seconds) && task.total_seconds > 0 && task.processed_seconds <= task.total_seconds
  const percent = measured ? Math.round(task!.processed_seconds! / task!.total_seconds! * 100) : null
  const updated = task?.updated_at ? Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/.test(task.updated_at) ? task.updated_at : task.updated_at + 'Z') : NaN
  const taskPath = note.taskId ? '/generate?' + new URLSearchParams({ meeting: '1', task: note.taskId, returnTo }).toString() : null
  return <div className="my-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border px-3 py-2 text-sm">
    <div className="min-w-0 flex-1" role="status">
      <p className="font-medium">{error ? zh ? '暂时无法读取任务进度' : 'Could not read task progress' : stage ? stage[zh ? 0 : 1] : zh ? note.taskId ? '正在读取原任务…' : '录音已保留，等待生成' : note.taskId ? 'Reading original task…' : 'Recording retained; awaiting generation'}</p>
      {task?.message && <p className="mt-1 break-words text-xs text-muted-foreground">{task.message}</p>}
      {percent !== null ? <div className="mt-2"><progress aria-label={zh ? '转写进度' : 'Transcription progress'} value={percent} max={100} className="h-1 w-full" /><p className="text-xs text-muted-foreground">{duration(task!.processed_seconds!)} / {duration(task!.total_seconds!)} · {percent}%</p></div> : task?.status === 'transcribing' && <p className="mt-1 text-xs text-muted-foreground">{zh ? '服务暂未提供识别百分比' : 'The service has not provided a transcription percentage'}</p>}
      {Number.isFinite(updated) && now >= updated && task && !['success', 'failed', 'error'].includes(task.status) && <p className="mt-1 text-xs text-muted-foreground">{zh ? '距任务状态更新 ' : 'Since task status update '}{duration((now - updated) / 1000)}</p>}
    </div>
    {saved && onSaved && <Button size="sm" onClick={() => { if (owner !== useAuthStore.getState().user?.id || origin !== useAppModeStore.getState().config?.server_url) return; if (hasUnsavedChanges) setDiscardBinding(binding); else onSaved(saved) }}>{zh ? '查看已保存纪要' : 'View saved notes'}</Button>}
    {hasUnsavedChanges && <p className="w-full text-xs text-muted-foreground">{zh ? '当前草稿已保留，不会覆盖生成结果。' : 'Your draft is retained and will not overwrite generated notes.'}</p>}
    <AlertDialog open={discardBinding === binding && !!saved} onOpenChange={open => { if (!open) setDiscardBinding(null) }}>
      <AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{zh ? '放弃当前草稿并查看纪要？' : 'Discard this draft and view notes?'}</AlertDialogTitle><AlertDialogDescription>{zh ? '只清除当前编辑草稿。已生成的纪要和原录音保持不变。' : 'Only this editing draft is discarded. Generated notes and the original recording are preserved.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter>
        <AlertDialogCancel>{zh ? '保留草稿' : 'Keep draft'}</AlertDialogCancel>
        <AlertDialogAction onClick={() => { if (saved && owner === useAuthStore.getState().user?.id && origin === useAppModeStore.getState().config?.server_url) onSaved?.(saved); setDiscardBinding(null) }}>{zh ? '放弃草稿并查看' : 'Discard draft and view'}</AlertDialogAction>
      </AlertDialogFooter></AlertDialogContent>
    </AlertDialog>
    {error && <Button size="sm" variant="ghost" onClick={() => setAttempt(value => value + 1)}>{zh ? '重新读取' : 'Read again'}</Button>}
    {taskPath && <Button size="sm" variant="outline" asChild><Link to={taskPath}>{zh ? '查看原任务' : 'View original task'}</Link></Button>}
  </div>
}
