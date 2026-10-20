import { useEffect, useState } from 'react'
import { apiJson, ApiError } from '@/lib/api'
import { depthLabels, presentationLabels, type ContentDepth, type Presentation } from '@/lib/summaryPresentation'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import type { LibraryNote } from './useLibraryNotes'

export type MeetingSummaryPresentation = { presentation: Presentation; depth: ContentDepth }
type Readback = MeetingSummaryPresentation | 'checking' | 'missing' | 'unverified'
const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/

/** Existing authenticated task metadata only; no body/title inference or generation. */
export function useMeetingSummaryPresentations(notes: LibraryNote[], ownerId: string | undefined, enabled: boolean) {
  const owner = useAuthStore(s => s.user?.id)
  const origin = useAppModeStore(s => s.config?.server_url)
  const tasks = [...new Set(notes.filter(note => !note.meetingSource || note.meetingSource.ownerId === ownerId)
    .map(note => note.taskId).filter((task): task is string => !!task && uuid.test(task)))].sort()
  const binding = JSON.stringify([owner, ownerId, origin, enabled, tasks, notes.map(note => [note.id, note.taskId, note.updatedAt])])
  const [snapshot, setSnapshot] = useState<{ binding: string; values: Record<string, Readback> }>({ binding: '', values: {} })
  useEffect(() => {
    const controller = new AbortController()
    setSnapshot({ binding, values: {} })
    if (enabled && ownerId && owner === ownerId) void (async () => {
      // Bound the local read fan-out; one read per distinct child task, on disclosure.
      for (const task of tasks) {
        if (controller.signal.aborted) return
        let value: Readback = 'unverified'
        try {
          const result = await apiJson<unknown>(`/api/task/${encodeURIComponent(task)}/summary-presentation`,
            { method: 'GET', signal: controller.signal, cache: 'no-store' })
          if (result && typeof result === 'object' && !Array.isArray(result)) {
            const row = result as Record<string, unknown>
            if (row.protocol === 1 && row.task_id === task
                && typeof row.presentation === 'string' && Object.prototype.hasOwnProperty.call(presentationLabels, row.presentation)
                && typeof row.content_depth === 'string' && Object.prototype.hasOwnProperty.call(depthLabels, row.content_depth)) {
              value = { presentation: row.presentation as Presentation, depth: row.content_depth as ContentDepth }
            }
          }
        } catch (error) {
          if (error instanceof ApiError && error.status === 404) value = 'missing'
        }
        if (!controller.signal.aborted) setSnapshot(current => current.binding === binding
          ? { binding, values: { ...current.values, [task]: value } } : current)
      }
    })()
    return () => controller.abort()
  }, [binding]) // Includes disclosure, note revisions, account and connection.
  return (note: LibraryNote): Readback => {
    if (!ownerId || owner !== ownerId || note.meetingSource && note.meetingSource.ownerId !== ownerId) return 'unverified'
    if (!note.taskId || !tasks.includes(note.taskId)) return 'missing'
    return snapshot.binding === binding && snapshot.values[note.taskId] || 'checking'
  }
}
