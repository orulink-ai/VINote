import { apiJson } from './api'
import type { LiveTranscriptDiagnostics } from '../types/liveTranscript'

export type SummaryMode = 'default' | 'accurate' | 'oneshot'
export type UploadSourceType = 'audio' | 'video' | 'transcript'

export interface TaskResponse {
  task_id: string
  status?: string
  message?: string
}

export interface TaskStatusResponse {
  task_id?: string
  status: string
  message: string
  result?: {
    task_id: string
    title: string
    markdown: string
  }
}

export interface UploadGenerationInput {
  file: File
  recordingFile?: File
  sourceType: UploadSourceType
  title: string
  style?: string
  extras?: string
  summaryMode: SummaryMode
  outputLanguage?: string
  modelProfileId?: string
  sttProfileId?: string
  diarize?: boolean
  speakerCount?: number
  workflow?: 'meeting' | 'note_organization'
  traceSource?: 'desktop_recording' | 'desktop_live_transcript' | 'local_file'
  meetingSessionId?: string
  meetingMode?: 'recording' | 'minutes'
  meetingType?: 'audio' | 'video'
  realtimeDiagnostics?: LiveTranscriptDiagnostics
}

export async function submitUploadedSource(input: UploadGenerationInput) {
  const formData = new FormData()
  formData.append('file', input.file)
  if (input.recordingFile) formData.append('recording', input.recordingFile)
  formData.append('source_type', input.sourceType)
  formData.append('title', input.title)
  formData.append('style', input.style || 'meeting')
  if (input.extras) formData.append('extras', input.extras)
  formData.append('summary_mode', input.summaryMode)
  formData.append('workflow', input.workflow || 'note_organization')
  formData.append('trace_source', input.traceSource || 'local_file')
  if (input.diarize !== undefined) formData.append('diarize', String(input.diarize))
  if (input.speakerCount) formData.append('speaker_count', String(input.speakerCount))
  if (input.meetingSessionId) formData.append('meeting_session_id', input.meetingSessionId)
  if (input.meetingMode) formData.append('meeting_mode', input.meetingMode)
  if (input.meetingType) formData.append('meeting_type', input.meetingType)
  if (input.realtimeDiagnostics) formData.append('realtime_diagnostics', JSON.stringify(input.realtimeDiagnostics))

  if (input.outputLanguage) {
    formData.append('output_language', input.outputLanguage)
  }
  if (input.modelProfileId) {
    formData.append('model_profile_id', input.modelProfileId)
  }
  if (input.sttProfileId) {
    formData.append('stt_profile_id', input.sttProfileId)
  }

  return apiJson<TaskResponse>('/api/generate_from_upload', {
    method: 'POST',
    body: formData,
  })
}

export async function fetchTaskStatus(taskId: string) {
  return apiJson<TaskStatusResponse>(`/api/task/${taskId}`)
}

export function wait(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

export async function waitForTaskCompletion({
  taskId,
  fetchStatus = fetchTaskStatus,
  onProgress,
  delay = () => wait(2000),
}: {
  taskId: string
  fetchStatus?: (taskId: string) => Promise<TaskStatusResponse>
  onProgress?: (status: TaskStatusResponse) => void
  delay?: () => Promise<void>
}) {
  while (true) {
    const status = await fetchStatus(taskId)
    onProgress?.(status)

    if (status.status === 'success') {
      return status
    }

    if (status.status === 'failed' || status.status === 'not_found') {
      throw new Error(status.message || 'Generation failed')
    }

    await delay()
  }
}
