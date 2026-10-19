import { useEffect, useState } from 'react'
import { apiJson } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import type { LibraryNote } from './useLibraryNotes'

export type MeetingTaskState = 'checking' | 'unverified' | 'failed' | 'processing' | 'complete'
export type MeetingTaskStates = Record<string, MeetingTaskState>

/** Read-only projection: saving a media placeholder is not generation success. */
export function useMeetingTaskStates(notes: LibraryNote[], route: string): MeetingTaskStates {
  const owner = useAuthStore(s => s.user?.id)
  const origin = useAppModeStore(s => s.config?.server_url)
  const sources = notes.flatMap(note => [note, ...(note.localSources || [])])
  const tasks = [...new Set(sources.map(note => note.taskId).filter((task): task is string => !!task))].sort()
  const revision = JSON.stringify(sources.map(note => [note.id, note.taskId, note.status, note.updatedAt]))
  const binding = JSON.stringify([owner, origin, route, revision])
  const [snapshot, setSnapshot] = useState<{ binding: string; states: MeetingTaskStates }>({ binding: '', states: {} })
  useEffect(() => {
    const controller = new AbortController()
    const active = () => !controller.signal.aborted && owner === useAuthStore.getState().user?.id && origin === useAppModeStore.getState().config?.server_url
    setSnapshot({ binding, states: Object.fromEntries(tasks.map(task => [task, 'checking'])) })
    if (owner) void Promise.all(tasks.map(async task => {
      let state: MeetingTaskState = 'unverified'
      try {
        const data = await apiJson<{ task_id?: string; status: string; result?: { title?: string; markdown?: string } }>(`/api/task/${encodeURIComponent(task)}`, { signal: controller.signal })
        if ((!data.task_id || data.task_id === task) && typeof data.status === 'string') {
          if (['failed', 'error'].includes(data.status)) state = 'failed'
          else if (data.status === 'success' && data.result?.title?.trim() && data.result.markdown?.trim()) state = 'complete'
          else if (['preparing', 'preparing_media', 'uploaded', 'transcribing', 'diarizing', 'parallel_analysis', 'aligning', 'analyzing_video', 'summarizing', 'screenshots', 'saving', 'saving_result'].includes(data.status)) state = 'processing'
        }
      } catch { /* A read failure does not prove completion or deletion. */ }
      if (active()) setSnapshot(current => current.binding === binding ? { binding, states: { ...current.states, [task]: state } } : current)
    }))
    return () => controller.abort()
  }, [binding]) // The binding includes every source identity/revision and account/route/Origin.
  return snapshot.binding === binding ? snapshot.states : Object.fromEntries(tasks.map(task => [task, 'checking']))
}
