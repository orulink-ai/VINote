import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import { apiJson } from '@/lib/api'
import { backgroundNotificationsEnabled, notificationTarget, observeGeneration, sourceNotificationTasks, readTrackedGenerations, TASK_NOTIFICATION_EVENT } from '@/lib/taskNotifications'
import { backgroundSaveCompletedTask } from '@/lib/backgroundTaskSave'
import { deletedMeetingTasks, rememberDeletedMeetingOperation, MEETING_TASKS_DELETED } from '@/lib/deletedMeetingTasks'
import { useNoteLibraryStore } from '@/stores/noteLibraryStore'
import { useTeamStore } from '@/stores/teamStore'
import { deliverNativeNotification, focusNotificationWindow, listenNativeNotification } from '@/lib/nativeTaskNotification'
import { Button } from '@/components/ui/button'
import { CheckCircle2, AlertCircle, X } from 'lucide-react'
type Notice = { id: number; title: string; target: string; success?: boolean; action: string; taskId?: string }
let sequence = Date.now() % 1000000000
export function TaskNotifications() {
  const owner = useAuthStore(state => state.user?.id)
  const navigate = useNavigate()
  const [notices, setNotices] = useState<Notice[]>([])
  const authEpoch = useRef(0)
  const [epoch, setEpoch] = useState(0)
  useEffect(() => useAuthStore.subscribe((state, previous) => {
    if (state.user?.id !== previous.user?.id) {
      authEpoch.current += 1
      setEpoch(authEpoch.current)
    }
  }), [])
  useEffect(() => {
    setNotices([])
    if (!owner) return
    let alive = true, polling = false
    let unregister = () => undefined as void
    const destinations = new Map<number, string>()
    const saveWarnings = new Map<string, number>()
    const startedEpoch = authEpoch.current
    const current = () => alive && authEpoch.current === startedEpoch && useAuthStore.getState().user?.id === owner
    const listenerReady = listenNativeNotification(id => {
      const target = destinations.get(id)
      if (current() && target) { void focusNotificationWindow().catch(() => undefined); navigate(target) }
    }).then(stop => { if (alive) unregister = stop; else stop() }).catch(() => undefined)
    const poll = async () => {
      if (polling || !current()) return
      polling = true
      try {
        for (const task of sourceNotificationTasks(owner)) {
          if (!current()) return
          try {
            if (!task.taskId && task.operationId) {
              const receipt = await apiJson<{ operation_id?: string; state?: string; task_id?: string }>(`/api/source-requests/${encodeURIComponent(task.operationId)}`)
              if (!current()) return
              if (receipt.task_id && deletedMeetingTasks(owner).has(receipt.task_id)) {
                if (receipt.operation_id === task.operationId && receipt.state === 'accepted') rememberDeletedMeetingOperation(owner, task.operationId, receipt.task_id)
                continue
              }
              task.taskId = receipt.task_id
            }
            if (!task.taskId) continue
            if (deletedMeetingTasks(owner).has(task.taskId)) continue
            const status = await apiJson<{ task_id: string; status: string; result?: { task_id?: string; title?: string } }>(`/api/task/${encodeURIComponent(task.taskId)}`)
            if (!current()) return
            if (deletedMeetingTasks(owner).has(task.taskId)) continue
            if (status.task_id !== task.taskId || (status.result?.task_id && status.result.task_id !== task.taskId)) continue
            let noteId: string | undefined
            if (status.status === 'success') {
              // Only work explicitly tracked after submission is auto-saved;
              // mounting historical terminal receipts never backfills content.
              const tracked = readTrackedGenerations(owner).some(item => item.active &&
                (item.taskId === task.taskId || !!task.operationId && item.operationId === task.operationId))
              if (tracked) {
                try {
                  noteId = await backgroundSaveCompletedTask(owner, task.taskId) || undefined
                  if (!current()) return
                  if (deletedMeetingTasks(owner).has(task.taskId)) continue
                  if (noteId) {
                    const warning = saveWarnings.get(task.taskId)
                    if (warning) setNotices(previous => previous.filter(item => item.id !== warning))
                    saveWarnings.delete(task.taskId)
                    void useNoteLibraryStore.getState().loadNotes(useTeamStore.getState().currentWorkspace)
                  }
                } catch {
                  if (current() && !deletedMeetingTasks(owner).has(task.taskId) && !saveWarnings.has(task.taskId)) {
                    const warning = { id: ++sequence, title: '内容已生成，保存暂未完成', target: notificationTarget(task), action: '继续保存', taskId: task.taskId }
                    saveWarnings.set(task.taskId, warning.id)
                    setNotices(previous => [...previous, warning])
                  }
                  continue // Keep checking the same result, never regenerate.
                }
              }
              if (!noteId) try { const notes = await apiJson<{ id: string; task_id?: string }[]>('/api/notes?scope=personal'); noteId = notes.find(note => note.task_id === task.taskId)?.id } catch { /* Keep exact recovery route. */ }
            }
            if (!current()) return
            if (!observeGeneration(owner, task, status.status)) continue
            const label = (status.result?.title || task.title || '').slice(0, 48)
            const notice = { id: ++sequence, title: `${task.meeting ? '会议纪要' : '笔记整理'}${status.status === 'success' ? '已完成' : '未完成'}${label ? ` · ${label}` : ''}`, target: notificationTarget(task, noteId), success: status.status === 'success', action: status.status !== 'success' ? '查看原因' : noteId ? task.meeting ? '打开纪要' : '打开笔记' : '查看结果', taskId: task.taskId }
            destinations.set(notice.id, notice.target)
            setNotices(previous => [...previous, notice])
            if ((document.visibilityState !== 'visible' || !document.hasFocus()) && backgroundNotificationsEnabled(owner)) {
              try { await listenerReady; if (current() && !deletedMeetingTasks(owner).has(task.taskId)) await deliverNativeNotification(notice.id, notice.title, () => current() && !deletedMeetingTasks(owner).has(task.taskId!) && (document.visibilityState !== 'visible' || !document.hasFocus())) } catch { /* In-app fallback remains available. */ }
            }
          } catch { /* Transport failure is not task failure. Never resubmit. */ }
        }
      } finally { polling = false }
    }
    void poll()
    const timer = setInterval(() => { void poll() }, 3000)
    const wake = () => { void poll() }
    const removeDeleted = () => { const ids = deletedMeetingTasks(owner); setNotices(previous => previous.filter(item => !item.taskId || !ids.has(item.taskId))) }
    window.addEventListener(TASK_NOTIFICATION_EVENT, wake)
    window.addEventListener(MEETING_TASKS_DELETED, removeDeleted)
    return () => { alive = false; clearInterval(timer); unregister(); window.removeEventListener(TASK_NOTIFICATION_EVENT, wake); window.removeEventListener(MEETING_TASKS_DELETED, removeDeleted) }
  }, [owner, navigate, epoch])
  if (!owner || !notices.length) return null
  return <section aria-label="任务结果通知" className="task-result-notices">
    {notices.slice(-3).map(notice => <div key={notice.id} className="task-result-notice">
      {notice.success ? <CheckCircle2 className="size-4 shrink-0 text-emerald-600" aria-hidden="true" /> : <AlertCircle className="size-4 shrink-0 text-amber-600" aria-hidden="true" />}
      <span role="status" className="min-w-0 flex-1 break-words text-sm">{notice.title}</span>
      <Button size="sm" variant="ghost" className="shrink-0" onClick={() => { navigate(notice.target); setNotices(previous => previous.filter(item => item.id !== notice.id)); }}>{notice.action}</Button>
      <Button size="icon" variant="ghost" className="size-7" aria-label={`关闭${notice.title}通知`} onClick={() => setNotices(previous => previous.filter(item => item.id !== notice.id))}><X className="size-3.5" /></Button>
    </div>)}
    {notices.length > 1 && <div className="flex justify-end gap-2"><Button size="sm" variant="outline" onClick={() => { navigate('/tasks'); setNotices([]); }}>全部任务</Button><Button size="sm" variant="outline" onClick={() => setNotices([])}>收起通知</Button></div>}
  </section>
}
