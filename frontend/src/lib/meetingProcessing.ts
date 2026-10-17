import { modelEligible, type ModelEligibilityInput } from './modelEligibility'
import { getPendingMeeting, getRecordedAudio, updatePendingMeeting, type PendingMeeting, type MeetingGenerationSelection } from './audioStorage'
import { completeMeetingRecordingGeneration, createMeetingRecordingTitle, MeetingGenerationError, MissingMeetingTaskError, resumeMeetingTask, submitMeetingRecording, type MeetingGenerationStage } from './meetingGeneration'
import { apiJson } from './api'
import { formatMeetingTitle, meetingSubject } from './meetingTitle'
import { useAuthStore } from '../stores/authStore'
import { type ModelSourceConfig } from '../stores/appModeStore'
import { fetchModelProfiles } from './modelProfiles'
import { fetchSTTProfiles } from './sttProfiles'
import { useNoteLibraryStore } from '../stores/noteLibraryStore'
import { publishToFeishu } from './feishu'

// Capture state is deliberately absent: each worker owns one durable recording.
const running = new Map<string, Promise<void>>()
export const isMeetingProcessing = (id: string) => running.has(id)

export interface MeetingGenerationConfirmation {
  selection: MeetingGenerationSelection
  previousOperationId?: string
  previousTaskId?: string
}

export function processSavedMeeting(recording: PendingMeeting, language: string, audio?: Blob, confirmation?: MeetingGenerationConfirmation): Promise<void> {
  const existing = running.get(recording.id)
  if (existing) return existing
  const worker = run(recording, language, audio, confirmation).finally(() => running.delete(recording.id))
  running.set(recording.id, worker)
  return worker
}

async function run(recording: PendingMeeting, language: string, audio?: Blob, confirmation?: MeetingGenerationConfirmation) {
  const id = recording.id
  let stage: MeetingGenerationStage = 'preparing_media'
  let draftId = recording.draftNoteId
  let ownsOperation = false
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
    let pending = await getPendingMeeting(id)
    if (!pending || pending.ownerId !== recording.ownerId) throw new Error('录制不存在或不属于当前账号。')
    if (useAuthStore.getState().user?.id !== pending.ownerId) throw new Error('账号已切换，请返回原账号处理。')
    if (pending.processingStatus === 'completed' && pending.noteId) return
    if (confirmation) {
      if (pending.taskId !== confirmation.previousTaskId || pending.generationOperation?.id !== confirmation.previousOperationId ||
        (!['idle', 'failed'].includes(pending.processingStatus) && !pending.generationConfirmationRequired)) {
        throw new Error('处理记录已更新，请返回原任务；不会重复提交。')
      }
      if (pending.taskId && !pending.generationConfirmationRequired) throw new Error('请先恢复原任务，不能重复提交。')
      if (!confirmation.selection.asr || !confirmation.selection.llm) throw new Error('请明确选择语音转写和总结模型，再确认生成。')
      pending = await updatePendingMeeting(id, {
        generationOperation: { id: crypto.randomUUID(), selection: { ...confirmation.selection }, outputLanguage: language, previousTaskId: pending.taskId },
        generationConfirmationRequired: false, taskId: undefined, draftNoteId: undefined,
      })
    }
    draftId = pending.draftNoteId
    ownsOperation = true
    if (pending.generationConfirmationRequired || (!pending.taskId && !pending.generationOperation)) {
      await persist({ generationConfirmationRequired: true, processingError: '请在原录制详情确认本次语音转写和总结模型，再开始生成；原录制保留。' })
      return
    }
    await persist({ processingStatus: 'queued', processingError: undefined, failedStage: undefined,
      retryCount: (pending.retryCount || 0) + (pending.processingStatus === 'failed' ? 1 : 0) })
    const blob = audio || await getRecordedAudio(id)
    if (!blob && !pending.taskId) throw new Error('找不到本地原始媒体，请恢复文件后重试。')
    let resumed
    if (pending.taskId) {
      try { resumed = await resumeMeetingTask(pending.taskId) }
      catch (error) {
        if (!(error instanceof MissingMeetingTaskError)) throw error
        await persist({ generationConfirmationRequired: true })
        throw new MeetingGenerationError('uploading', '原任务已失效，未重新提交。原录制与原任务记录保留，请确认模型后另建生成操作。')
      }
    }
    if (!resumed) {
      const selection = pending.generationOperation!.selection
      const config = await apiJson<ModelSourceConfig>('/api/vilab/config', { cache: 'no-store' })
      if (useAuthStore.getState().user?.id !== pending.ownerId) throw new Error('账号已切换，未提交生成。')
      if (config.mode !== selection.mode || (selection.mode === 'cloud' &&
        (config.asr_model !== selection.asr || config.llm_model !== selection.llm))) {
        await persist({ generationConfirmationRequired: true })
        throw new Error('模型配置已变化，未提交生成。请核对模型后明确另建操作。')
      }
      const available = selection.mode === 'cloud'
        ? await apiJson<(ModelEligibilityInput & { id: string; modelType: string })[]>('/api/vilab/models', { cache: 'no-store' })
          .then(catalog => catalog.some(model => model.id === selection.asr && model.modelType === 'asr' && modelEligible(model)) &&
            catalog.some(model => model.id === selection.llm && model.modelType === 'llm' && modelEligible(model)))
        : await Promise.all([fetchSTTProfiles(), fetchModelProfiles()]).then(([speech, models]) =>
          speech.some(profile => profile.id === selection.asr && profile.isActive && `${profile.name} · ${profile.modelName || profile.provider}` === selection.asrLabel) &&
          models.some(profile => profile.id === selection.llm && profile.isActive && `${profile.name} · ${profile.modelName}` === selection.llmLabel))
      if (!available) {
        await persist({ generationConfirmationRequired: true })
        throw new Error('已确认模型不可用或配置已修改，未提交生成。请重新核对模型。')
      }
      if (useAuthStore.getState().user?.id !== pending.ownerId) throw new Error('账号已切换，未提交生成。')
    }
    const selection = pending.generationOperation?.selection
    const response = resumed || await submitMeetingRecording({
      audioBlob: blob!, title: pending.options.title, diarize: true,
      startedAt: new Date(pending.startedAt), endedAt: pending.endedAt ? new Date(pending.endedAt) : undefined,
      outputLanguage: pending.generationOperation!.outputLanguage, summaryMode: 'default',
      modelProfileId: selection?.mode === 'local' ? selection.llm : undefined,
      sttProfileId: selection?.mode === 'local' ? selection.asr : undefined,
      meetingSessionId: id, meetingMode: 'minutes', meetingType: pending.options.meetingType,
    }, { onStage })
    await persist({ taskId: response.task_id, processingStatus: 'preparing_media' })
    if (useAuthStore.getState().user?.id !== pending.ownerId) throw new Error('账号已切换，请用原账号恢复任务保存。')
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
      saveNote: async (_title, content) => {
        if (useAuthStore.getState().user?.id !== pending.ownerId) throw new MeetingGenerationError('saving', '账号已切换，请使用原账号恢复保存。')
        const current = await getPendingMeeting(id) || pending
        const generatedTitle = current.titleEdited ? current.options.title
          : formatMeetingTitle(pending.startedAt, meetingSubject(content) || (language.startsWith('zh') ? '会议纪要' : 'Meeting notes'), language)
        // Preserve a title the user changed in the draft while processing.
        const draft = await library.loadNoteById(draftId!)
        const originalTitle = pending.options.title.trim() || createMeetingRecordingTitle(new Date(pending.startedAt), language)
        const finalTitle = draft?.title && draft.title !== originalTitle ? draft.title : generatedTitle
        if (useAuthStore.getState().user?.id !== pending.ownerId) throw new MeetingGenerationError('saving', '账号已切换，请使用原账号恢复保存。')
        const saved = await library.updateNote(draftId!, finalTitle, content, 'done')
        if (saved) await persist({ options: { ...current.options, title: finalTitle } })
        return saved
      },
      onProgress: status => { void persist({ processedSeconds: status.processed_seconds ?? undefined,
        totalSeconds: status.total_seconds ?? undefined, etaSeconds: status.eta_seconds ?? undefined,
        progress: status.progress ?? undefined }).catch(() => undefined) },
    })
    await persist({ noteId: note.id, processingStatus: 'completed', feishuPending: true })
    // Publication failure must never turn successful minutes into a generation failure.
    if (useAuthStore.getState().user?.id === recording.ownerId) {
      void publishToFeishu(note.id, note.title, note.content, true)
        .then(() => updatePendingMeeting(id, { feishuPending: false })).catch(() => undefined)
    }
  } catch (error) {
    await writes.catch(() => undefined)
    if (useAuthStore.getState().user?.id !== recording.ownerId) return
    if (!ownsOperation) throw error
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
