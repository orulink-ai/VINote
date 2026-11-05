import { useEffect, useState } from 'react'
import { apiJson } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import type { LibraryNote } from './useLibraryNotes'
import type { TaskStatusResponse } from '@/lib/noteGenerationClient'

export type MeetingTaskState = 'checking' | 'unverified' | 'failed' | 'processing' | 'complete'
export type MeetingTaskProgress = { state: 'processing'; status: string; stage?: string; processedSeconds?: number; totalSeconds?: number; updatedAt?: string }
export type MeetingTaskStates = Record<string, MeetingTaskState | MeetingTaskProgress>
export const meetingTaskState = (value: MeetingTaskStates[string] | undefined) => typeof value === 'object' ? value.state : value

/** Read-only projection: saving a media placeholder is not generation success. */
export function useMeetingTaskStates(notes: LibraryNote[], route: string, recordingTaskIds: string[] = []): MeetingTaskStates {
  const owner = useAuthStore(s => s.user?.id)
  const origin = useAppModeStore(s => s.config?.server_url)
  const sources = notes.flatMap(note => [note, ...(note.localSources || [])])
  const tasks = [...new Set([...sources.map(note => note.taskId), ...recordingTaskIds].filter((task): task is string => !!task))].sort()
  const revision = JSON.stringify(sources.map(note => [note.id, note.taskId, note.status, note.updatedAt]))
  const binding = JSON.stringify([owner, origin, route, revision, tasks])
  const [snapshot, setSnapshot] = useState<{ binding: string; states: MeetingTaskStates }>({ binding: '', states: {} })
  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    const active = () => !controller.signal.aborted && owner === useAuthStore.getState().user?.id && origin === useAppModeStore.getState().config?.server_url
    const states: MeetingTaskStates = Object.fromEntries(tasks.map(task => [task, 'checking']))
    setSnapshot({ binding, states: { ...states } })
    const cycle = async () => {
      await Promise.all(tasks.filter(task => !['complete', 'failed'].includes(meetingTaskState(states[task]) || '')).map(async task => {
        let state: MeetingTaskStates[string] = 'unverified'
        try {
          const data = await apiJson<TaskStatusResponse>(`/api/task/${encodeURIComponent(task)}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]) })
          if ((!data.task_id || data.task_id === task) && (!data.result?.task_id || data.result.task_id === task) && typeof data.status === 'string') {
            if (['failed', 'error'].includes(data.status)) state = 'failed'
            else if (data.status === 'success' && data.result?.title?.trim() && data.result.markdown?.trim()) state = 'complete'
            else if (['pending', 'queued', 'preparing', 'preparing_media', 'uploaded', 'transcribing', 'diarizing', 'parallel_analysis', 'aligning', 'analyzing_video', 'summarizing', 'screenshots', 'saving', 'saving_result'].includes(data.status)) {
              state = { state: 'processing', status: data.status, stage: data.stage, updatedAt: data.updated_at,
                ...(data.status === 'transcribing' ? { processedSeconds: data.processed_seconds, totalSeconds: data.total_seconds } : {}) }
            }
          }
        } catch { /* A read failure does not prove completion or deletion. */ }
        if (active()) {
          states[task] = state
          setSnapshot({ binding, states: { ...states } })
        }
      }))
      if (active() && tasks.some(task => !['complete', 'failed'].includes(meetingTaskState(states[task]) || ''))) timer = setTimeout(() => void cycle(), 4000)
    }
    if (owner) void cycle()
    return () => { controller.abort(); if (timer) clearTimeout(timer) }
  }, [binding])
  return snapshot.binding === binding ? snapshot.states : Object.fromEntries(tasks.map(task => [task, 'checking']))
}
