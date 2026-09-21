import { apiJson } from './api'
import type { NoteRecord } from '../stores/noteLibraryStore'
import type { WorkspaceSelection } from '../stores/teamStore'
import {
  fetchTaskStatus,
  submitUploadedSource,
  type SummaryMode,
  type TaskResponse,
  type TaskStatusResponse,
  type UploadGenerationInput,
} from './noteGenerationClient'

export const MEETING_NOTE_SOURCE_TYPE = 'meeting_recording'
export type MeetingGenerationStage = 'uploading' | 'preparing_media' | 'transcribing' | 'diarizing' | 'aligning' | 'analyzing_video' | 'summarizing' | 'saving' | 'completed'

type SaveNote = (
  title: string,
  content: string,
  videoUrl?: string,
  taskId?: string,
  workspace?: WorkspaceSelection,
  sourceType?: string,
  status?: string,
) => Promise<NoteRecord | null>

interface SubmitMeetingRecordingInput {
  audioBlob: Blob
  title?: string
  diarize?: boolean
  speakerCount?: number
  startedAt: Date
  endedAt?: Date
  outputLanguage?: string
  summaryMode: SummaryMode
  modelProfileId?: string
  sttProfileId?: string
  meetingSessionId?: string
  meetingMode?: 'recording' | 'minutes'
  meetingType?: 'audio' | 'video'
}

interface SubmitMeetingRecordingDependencies {
  submitUploadedSource?: (input: UploadGenerationInput) => Promise<TaskResponse>
  onStage?: (stage: MeetingGenerationStage) => void
}

export class MeetingGenerationError extends Error {
  stage: Exclude<MeetingGenerationStage, 'completed'>

  constructor(stage: MeetingGenerationError['stage'], message: string) {
    super(message)
    this.name = 'MeetingGenerationError'
    this.stage = stage
  }
}

export class MissingMeetingTaskError extends MeetingGenerationError {
  constructor() { super('uploading', '服务端任务不存在，将使用保留的原始录制重新提交。') }
}

export function createMeetingRecordingTitle(date = new Date(), locale = 'zh-CN') {
  const formatter = new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
  const prefix = locale.startsWith('zh') ? '会议录音' : 'Meeting recording'
  return `${prefix} ${formatter.format(date)}`
}

export function buildMeetingRecordingFile(audioBlob: Blob, startedAt = new Date()) {
  const extension = resolveAudioExtension(audioBlob.type)
  const timestamp = startedAt.toISOString().replace(/\.\d{3}Z$/, '').replace(/[T:]/g, '-')
  return new File([audioBlob], `meeting-recording-${timestamp}.${extension}`, {
    type: audioBlob.type || 'audio/webm',
  })
}

export async function submitMeetingRecording(
  input: SubmitMeetingRecordingInput,
  dependencies: SubmitMeetingRecordingDependencies = {},
) {
  dependencies.onStage?.('uploading')
  const file = buildMeetingRecordingFile(input.audioBlob, input.startedAt)
  const submit = dependencies.submitUploadedSource || submitUploadedSource

  try {
    return await submit({
      file,
      ...(input.diarize ? { diarize: true, speakerCount: input.speakerCount } : {}),
      sourceType: input.audioBlob.type.startsWith('video/') ? 'video' : 'audio',
      title: input.title?.trim() || createMeetingRecordingTitle(input.startedAt, input.outputLanguage || 'zh-CN'),
      style: 'meeting',
      workflow: 'meeting',
      traceSource: 'desktop_recording',
      extras: `录制开始时间：${input.startedAt.toISOString()}。${input.endedAt ? `录制结束时间：${input.endedAt.toISOString()}。` : '录制结束时间未知。'}这是录制时间，不代表实际会议起止；录制可能暂停，禁止用音频时长推算会议结束时间。`,
      summaryMode: input.summaryMode,
      outputLanguage: input.outputLanguage,
      modelProfileId: input.modelProfileId,
      sttProfileId: input.sttProfileId,
      meetingSessionId: input.meetingSessionId,
      meetingMode: input.meetingMode,
      meetingType: input.meetingType,
    })
  } catch (error) {
    throw new MeetingGenerationError('uploading', error instanceof Error ? error.message : 'Upload failed')
  }
}

async function defaultDelay() {
  await new Promise((resolve) => window.setTimeout(resolve, 2000))
}

export async function waitForMeetingTaskCompletion({
  taskId,
  fetchStatus = fetchTaskStatus,
  onStage,
  onProgress,
  delay = defaultDelay,
}: {
  taskId: string
  fetchStatus?: (taskId: string) => Promise<TaskStatusResponse>
  onStage?: (stage: MeetingGenerationStage) => void
  onProgress?: (status: TaskStatusResponse) => void
  delay?: () => Promise<void>
}) {
  let lastRunningStage: Exclude<MeetingGenerationStage, 'uploading' | 'completed'> = 'transcribing'

  for (;;) {
    const status = await fetchStatus(taskId)
    onProgress?.(status)
    if (status.status === 'success') return status
    if (status.status === 'failed' || status.status === 'not_found') {
      const failed = status.failed_stage
      const known = ['preparing_media', 'transcribing', 'diarizing', 'aligning', 'analyzing_video', 'summarizing', 'saving']
      throw new MeetingGenerationError(known.includes(failed || '') ? failed as typeof lastRunningStage : lastRunningStage, status.message || 'Meeting generation failed')
    }
    const stage = status.stage || status.status
    if (stage === 'preparing' || stage === 'preparing_media' || stage === 'uploaded') {
      lastRunningStage = 'preparing_media'
      onStage?.('preparing_media')
    } else if (stage === 'transcribing') {
      lastRunningStage = 'transcribing'
      onStage?.('transcribing')
    } else if (stage === 'diarizing') {
      lastRunningStage = 'diarizing'; onStage?.('diarizing')
    } else if (stage === 'aligning') {
      lastRunningStage = 'aligning'; onStage?.('aligning')
    } else if (stage === 'analyzing_video') {
      lastRunningStage = 'analyzing_video'; onStage?.('analyzing_video')
    } else if (stage === 'saving' || stage === 'saving_result') {
      lastRunningStage = 'saving'; onStage?.('saving')
    } else if (status.status === 'summarizing' || status.status === 'screenshots' || stage === 'summarizing') {
      lastRunningStage = 'summarizing'
      onStage?.('summarizing')
    }

    await delay()
  }
}

export async function completeMeetingRecordingGeneration({
  taskId,
  workspace,
  saveNote,
  fetchTaskStatus,
  onStage,
  onProgress,
  delay,
}: {
  taskId: string
  workspace: WorkspaceSelection
  saveNote: SaveNote
  fetchTaskStatus?: (taskId: string) => Promise<TaskStatusResponse>
  onStage?: (stage: MeetingGenerationStage) => void
  onProgress?: (status: TaskStatusResponse) => void
  delay?: () => Promise<void>
}) {
  const status = await waitForMeetingTaskCompletion({
    taskId,
    fetchStatus: fetchTaskStatus,
    onStage,
    onProgress,
    delay,
  })
  const result = status.result

  if (!result) {
    throw new MeetingGenerationError('summarizing', 'Meeting summary completed without a result.')
  }

  onStage?.('saving')
  const note = await saveNote(
    result.title || createMeetingRecordingTitle(),
    result.markdown || '',
    undefined,
    result.task_id || taskId,
    workspace,
    MEETING_NOTE_SOURCE_TYPE,
  )

  if (!note) {
    throw new MeetingGenerationError('saving', 'Meeting summary was generated but could not be saved.')
  }

  onStage?.('completed')
  return note
}

function resolveAudioExtension(mimeType: string) {
  const normalized = mimeType.toLowerCase()
  if (normalized.includes('mp4')) return normalized.startsWith('video/') ? 'mp4' : 'm4a'
  if (normalized.includes('mpeg')) return 'mp3'
  if (normalized.includes('ogg')) return 'ogg'
  if (normalized.includes('wav')) return 'wav'
  return 'webm'
}

const AUDIO_EXTENSION_FALLBACKS = ['webm', 'mp4', 'm4a', 'wav', 'mp3', 'ogg'] as const

export async function fetchMeetingAudioBlob(taskId: string): Promise<Blob> {
  let lastError: unknown
  for (const ext of AUDIO_EXTENSION_FALLBACKS) {
    const url = `/api/task/${taskId}/artifacts/media/source_audio.${ext}`
    try {
      const response = await fetch(url, { credentials: 'include' })
      if (response.ok) {
        const contentType = response.headers.get('Content-Type') || `audio/${ext}`
        const blob = await response.blob()
        return new Blob([blob], { type: contentType })
      }
      lastError = new Error(`HTTP ${response.status} for ${ext}`)
    } catch (fetchError) {
      lastError = fetchError
    }
  }
  throw new MeetingGenerationError(
    'uploading',
    `无法加载已保留的录音 (${lastError instanceof Error ? lastError.message : 'unknown'})`,
  )
}

export async function resumeMeetingTask(taskId: string): Promise<TaskResponse> {
  const status = await fetchTaskStatus(taskId)
  if (status.status === 'not_found') throw new MissingMeetingTaskError()
  if (status.status === 'failed') return apiJson<TaskResponse>('/api/task/' + taskId + '/retry', { method: 'POST' })
  return { task_id: taskId }
}
