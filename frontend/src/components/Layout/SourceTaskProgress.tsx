import { useEffect, useRef, useState } from 'react'
import { apiJson } from '../../lib/api'
import { useAuthStore } from '../../stores/authStore'
import { captureDiagnostic } from '../../lib/captureDiagnostics'
import { isTauriRuntime } from '../../lib/desktopMicrophonePermission'

interface TaskProgress {
  task_id: string
  status: string
  message: string
  progress?: number | null
  label?: string
  processed_seconds?: number | null
  total_seconds?: number | null
  eta_seconds?: number | null
}

const duration = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
const isTerminal = (status: string) => ['success', 'failed', 'error', 'not_found'].includes(status)

export function SourceTaskProgress() {
  const userId = useAuthStore(state => state.user?.id)
  const [tasks, setTasks] = useState<TaskProgress[]>([])
  const [error, setError] = useState(false)
  const observedActive = useRef(new Set<string>())
  const renderedStatus = tasks.map(task => task.status).join(',')
  useEffect(() => {
    captureDiagnostic(`task-progress.${isTauriRuntime() ? 'desktop' : 'web'}.${userId ? 'signed-in' : 'signed-out'}`, {
      errorMessage: error ? 'Progress request failed' : renderedStatus,
    })
  }, [userId, error, renderedStatus])
  useEffect(() => {
    if (!import.meta.env.DEV || !userId) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const response = await fetch('/__vinote/dev-tasks', { cache: 'no-store' })
        if (!response.ok) throw new Error('Task registration unavailable')
        const registrations: { taskId: string; label: string }[] = await response.json()
        const results = await Promise.allSettled(registrations.map(async ({ taskId, label }) =>
          ({ ...await apiJson<TaskProgress>(`/api/task/${taskId}`), label })))
        if (disposed) return
        setTasks(results.flatMap(result => {
          if (result.status !== 'fulfilled') return []
          const task = result.value
          if (!isTerminal(task.status)) observedActive.current.add(task.task_id)
          return observedActive.current.has(task.task_id) ? [task] : []
        }))
        setError(results.some(result => result.status === 'rejected'))
      } catch { if (!disposed) setError(true) }
      if (!disposed) timer = setTimeout(() => { void poll() }, 2000)
    }
    void poll()
    return () => { disposed = true; clearTimeout(timer) }
  }, [userId])

  if (!userId || (!tasks.length && !error)) return null
  return <section aria-label="会议处理进度" className="mx-4 my-2 shrink-0 rounded-lg border bg-card p-3 text-sm">
    <div className="mb-2 font-medium">会议处理进度</div>
    {tasks.map((task, index) => <div key={task.task_id} className="mt-2" role="status">
      <div className="flex items-start justify-between gap-3">
        <span>{task.label || `任务 ${index + 1}`} · {task.message}</span>
        <div className="flex shrink-0 items-center gap-3"><span className="text-muted-foreground">{task.status === 'success' ? '完成' : isTerminal(task.status) ? '失败' : '处理中'}</span>
          {isTerminal(task.status) && <button type="button" aria-label={`关闭${task.label || '任务'}结果`} className="text-muted-foreground hover:text-foreground" onClick={() => {
            observedActive.current.delete(task.task_id)
            setTasks(current => current.filter(item => item.task_id !== task.task_id))
          }}>关闭</button>}
        </div>
      </div>
      {typeof task.progress === 'number' && task.status !== 'failed' && <progress
        className="mt-2 h-2 w-full" max={1} value={Math.min(1, Math.max(0, task.progress))}
        aria-label={`任务 ${index + 1} 进度`} />}
      {typeof task.processed_seconds === 'number' && typeof task.total_seconds === 'number' &&
        <p className="mt-1 text-xs text-muted-foreground">已转写 {duration(task.processed_seconds)} / {duration(task.total_seconds)}
          {typeof task.eta_seconds === 'number' && task.status !== 'failed' ? ` · 预计剩余 ${duration(task.eta_seconds)}` : ''}</p>}
    </div>)}
    {error && <p role="alert" className="mt-2 text-destructive">部分任务进度暂时无法获取，正在重新连接。</p>}
  </section>
}
