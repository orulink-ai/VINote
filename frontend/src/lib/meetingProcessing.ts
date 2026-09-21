import { getPendingMeeting, getRecordedAudio, updatePendingMeeting, type PendingMeeting } from './audioStorage'
import { completeMeetingRecordingGeneration, createMeetingRecordingTitle, MeetingGenerationError, MissingMeetingTaskError, resumeMeetingTask, submitMeetingRecording, type MeetingGenerationStage } from './meetingGeneration'
import { apiJson } from './api'
import { useAuthStore } from '../stores/authStore'
import { useModelProfileStore } from '../stores/modelProfileStore'
import { useSTTProfileStore } from '../stores/sttProfileStore'
import { useNoteLibraryStore } from '../stores/noteLibraryStore'

// Capture state is deliberately absent: each worker owns one durable recording.
const running = new Map<string, Promise<void>>()
export const isMeetingProcessing = (id: string) => running.has(id)

export function processSavedMeeting(recording: PendingMeeting, language: string, audio?: Blob): Promise<void> {
  const existing = running.get(recording.id)
  if (existing) return existing
  const worker = run(recording, language, audio).finally(() => running.delete(recording.id))
  running.set(recording.id, worker)
  return worker
}

async function run(recording: PendingMeeting, language: string, audio?: Blob) {
  const id = recording.id
  let stage: MeetingGenerationStage = 'preparing_media'
  let draftId = recording.draftNoteId
  let writes = Promise.resolve()
  const persist = (patch: Partial<PendingMeeting>) => {
    writes = writes.then(async () => { await updatePendingMeeting(id, { ...patch, processingUpdatedAt: new Date().toISOString() }) })
    // Observe rejection immediately; the awaited tail still reports storage failure.
    void writes.catch(() => undefined)
    return writes
  }
  const onStage = (next: MeetingGenerationStage) => {
    stage = next
    const processingStatus = next === 'uploading' ? 'queued' : next === 'saving' ? 'saving_result' : next === 'summarizing' ? 'generating' : next
    void persist({ processingStatus }).catch(() => undefined)
  }
  try {
    if (useAuthStore.getState().user?.id !== recording.ownerId) throw new Error('请使用录制所属账号继续处理。')
    const pending = await getPendingMeeting(id) || recording
    if (pending.processingStatus === 'completed' && pending.noteId) return
    await persist({ processingStatus: 'queued', processingError: undefined, failedStage: undefined,
      retryCount: (pending.retryCount || 0) + (pending.processingStatus === 'failed' ? 1 : 0) })
    const blob = audio || await getRecordedAudio(id)
    if (!blob && !pending.taskId) throw new Error('找不到本地原始媒体，请恢复文件后重试。')
    let resumed
    if (pending.taskId) {
      try { resumed = await resumeMeetingTask(pending.taskId) }
      catch (error) {
        if (!(error instanceof MissingMeetingTaskError) || !blob) throw error
        await persist({ taskId: undefined })
      }
    }
    const response = resumed || await submitMeetingRecording({
      audioBlob: blob!, title: pending.options.title, diarize: true,
      startedAt: new Date(pending.startedAt), endedAt: pending.endedAt ? new Date(pending.endedAt) : undefined,
      outputLanguage: language, summaryMode: 'default',
      modelProfileId: useModelProfileStore.getState().selectedProfileId || undefined,
      sttProfileId: useSTTProfileStore.getState().selectedProfileId || undefined,
      meetingSessionId: id, meetingMode: 'minutes', meetingType: pending.options.meetingType,
    }, { onStage })
    await persist({ taskId: response.task_id, processingStatus: 'preparing_media' })
    const library = useNoteLibraryStore.getState()
    draftId = pending.draftNoteId
    stage = 'saving'
    if (!draftId) {
      const draft = await library.saveNote(pending.options.title.trim() || createMeetingRecordingTitle(new Date(pending.startedAt), language),
        '原始媒体已保存，正在进行会后处理。', undefined, response.task_id, pending.workspace,
        pending.options.screen ? 'meeting_video' : 'meeting_recording', 'pending')
      if (!draft) throw new MeetingGenerationError('saving', '无法保存记录，请重试。')
      draftId = draft.id
      await persist({ draftNoteId: draftId })
    }
    const note = await completeMeetingRecordingGeneration({ taskId: response.task_id, workspace: pending.workspace, onStage,
      saveNote: async (title, content) => {
        if (useAuthStore.getState().user?.id !== pending.ownerId) throw new MeetingGenerationError('saving', '账号已切换，请使用原账号恢复保存。')
        return library.updateNote(draftId!, title, content, 'done')
      },
      onProgress: status => { void persist({ processedSeconds: status.processed_seconds ?? undefined,
        totalSeconds: status.total_seconds ?? undefined, etaSeconds: status.eta_seconds ?? undefined,
        progress: status.progress ?? undefined }).catch(() => undefined) },
    })
    await persist({ noteId: note.id, processingStatus: 'completed' })
  } catch (error) {
    await writes.catch(() => undefined)
    await updatePendingMeeting(id, { processingStatus: 'failed',
      failedStage: error instanceof MeetingGenerationError ? error.stage : stage,
      processingError: error instanceof Error ? error.message : String(error),
      processingUpdatedAt: new Date().toISOString(),
    }).catch(console.error)
    // Status-only update preserves any user edits to the draft.
    if (draftId && useAuthStore.getState().user?.id === recording.ownerId) {
      await apiJson(`/api/notes/${draftId}`, { method: 'PATCH',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'failed' }),
      }).catch(() => undefined)
    }
  }
}
