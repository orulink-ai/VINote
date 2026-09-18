import { create } from 'zustand'
import type { LiveTranscriptDiagnostics, LiveTranscriptSegment, LiveTranscriptStatus } from '../types/liveTranscript'
import type { MeetingCaptureOptions } from '../lib/meetingCapture'

export type MeetingRecorderPhase =
  | 'idle'
  | 'requesting'
  | 'recording'
  | 'paused'
  | 'stopping'
  | 'stopped'
  | 'uploading'
  | 'transcribing'
  | 'summarizing'
  | 'saving'
  | 'completed'
  | 'failed'

export type MeetingRecorderStage =
  | 'uploading'
  | 'transcribing'
  | 'summarizing'
  | 'saving'

export interface MeetingRecorderNotification {
  kind: 'success' | 'error'
  title: string
  message?: string
  noteId?: string
}

interface MeetingRecorderState {
  preview?: MediaStream | null
  sizeBytes?: number
  isPanelOpen: boolean
  isMinimized: boolean
  confirmDiscardOpen: boolean
  phase: MeetingRecorderPhase
  elapsedSeconds: number
  taskId?: string
  noteId?: string
  recordingId?: string
  recordedAudio?: Blob
  generatedNote?: GeneratedMeetingNote
  failedStage?: MeetingRecorderStage
  error: string
  retryDescription: string
  hasRecoverableRecording: boolean
  localRecordingSaved: boolean
  notification: MeetingRecorderNotification | null
  captureOptions?: MeetingCaptureOptions
  liveTranscriptStatus: LiveTranscriptStatus
  liveTranscriptError: string
  liveTranscriptSegments: LiveTranscriptSegment[]
  liveTranscriptDiagnostics?: LiveTranscriptDiagnostics
  openPanel: () => void
  closePanel: () => void
  requestClose: () => void
  cancelCloseRequest: () => void
  discardSession: () => void
  minimizePanel: () => void
  restorePanel: () => void
  setPhase: (phase: MeetingRecorderPhase) => void
  setElapsedSeconds: (elapsedSeconds: number) => void
  setTaskId: (taskId: string) => void
  setRecordingId: (id: string | undefined) => void
  setRecordedAudio: (audio: Blob | undefined) => void
  setGeneratedNote: (note: GeneratedMeetingNote) => void
  failStage: (stage: MeetingRecorderStage, error: string) => void
  complete: (noteId: string) => void
  fail: (error: string) => void
  syncExternalState: (snapshot: MeetingRecorderExternalSnapshot) => void
  dismissNotification: () => void
  resetSession: () => void
}

export interface GeneratedMeetingNote {
  title: string
  markdown: string
  taskId: string
}

export interface MeetingRecorderExternalSnapshot {
  isPanelOpen?: boolean
  isMinimized?: boolean
  phase?: MeetingRecorderPhase
  elapsedSeconds?: number
  taskId?: string
  noteId?: string
  error?: string
  notification?: MeetingRecorderNotification | null
}

const initialState = {
  preview: null as MediaStream | null,
  sizeBytes: 0,
  isPanelOpen: false,
  isMinimized: false,
  confirmDiscardOpen: false,
  phase: 'idle' as MeetingRecorderPhase,
  elapsedSeconds: 0,
  taskId: undefined as string | undefined,
  noteId: undefined as string | undefined,
  recordingId: undefined as string | undefined,
  recordedAudio: undefined as Blob | undefined,
  generatedNote: undefined as GeneratedMeetingNote | undefined,
  failedStage: undefined as MeetingRecorderStage | undefined,
  error: '',
  retryDescription: '',
  hasRecoverableRecording: false,
  localRecordingSaved: false,
  notification: null as MeetingRecorderNotification | null,
  captureOptions: undefined as MeetingCaptureOptions | undefined,
  liveTranscriptStatus: 'idle' as LiveTranscriptStatus,
  liveTranscriptError: '',
  liveTranscriptSegments: [] as LiveTranscriptSegment[],
  liveTranscriptDiagnostics: undefined as LiveTranscriptDiagnostics | undefined,
}

const retryDescriptions: Record<MeetingRecorderStage, string> = {
  uploading: '录制已经保存在本机，可重新上传并生成纪要。',
  transcribing: '录制已经保存在本机，可稍后重新转写。',
  summarizing: '录制和可用逐字稿已经保存在本机，可稍后重新生成纪要。',
  saving: '生成结果尚未保存，可重新保存。',
}

export function isMeetingBusy(state: Pick<MeetingRecorderState, 'phase' | 'hasRecoverableRecording' | 'localRecordingSaved'>) {
  return !['idle', 'completed', 'failed'].includes(state.phase)
    || (state.hasRecoverableRecording && !state.localRecordingSaved)
}

function hasRecoveryRisk(state: Pick<MeetingRecorderState, 'phase' | 'recordedAudio' | 'generatedNote' | 'noteId'>) {
  if (state.noteId) return false
  if (state.recordedAudio || state.generatedNote) return true
  return ['recording', 'paused', 'stopping', 'stopped', 'uploading', 'transcribing', 'summarizing', 'saving'].includes(state.phase)
}

export const useMeetingRecorderStore = create<MeetingRecorderState>((set, get) => ({
  ...initialState,
  openPanel: () => set({ isPanelOpen: true, isMinimized: false }),
  closePanel: () => set({ isPanelOpen: false, isMinimized: false, confirmDiscardOpen: false }),
  requestClose: () => set((state) => {
    if (hasRecoveryRisk(state)) {
      return { confirmDiscardOpen: true, isPanelOpen: true }
    }
    return { isPanelOpen: false, isMinimized: false, confirmDiscardOpen: false }
  }),
  cancelCloseRequest: () => set({ confirmDiscardOpen: false }),
  discardSession: () => set(initialState),
  minimizePanel: () => set({ isPanelOpen: true, isMinimized: true, confirmDiscardOpen: false }),
  restorePanel: () => set({ isPanelOpen: true, isMinimized: false }),
  setPhase: (phase) => set((state) => ({
    phase,
    error: '',
    failedStage: undefined,
    retryDescription: '',
    hasRecoverableRecording: hasRecoveryRisk({ ...state, phase }),
  })),
  setElapsedSeconds: (elapsedSeconds) => set({ elapsedSeconds }),
  setTaskId: (taskId) => set({ taskId }),
  setRecordingId: (recordingId) => set({ recordingId }),
  setRecordedAudio: (recordedAudio) => set((state) => ({
    recordedAudio,
    hasRecoverableRecording: hasRecoveryRisk({ ...state, recordedAudio }),
  })),
  setGeneratedNote: (generatedNote) => set((state) => ({
    generatedNote,
    hasRecoverableRecording: hasRecoveryRisk({ ...state, generatedNote }),
  })),
  failStage: (failedStage, error) => set((state) => ({
    phase: 'failed',
    failedStage,
    error,
    retryDescription: retryDescriptions[failedStage],
    isPanelOpen: true,
    isMinimized: false,
    hasRecoverableRecording: hasRecoveryRisk({ ...state, phase: 'failed' }),
    notification: {
      kind: 'error',
      title: '会议纪要生成失败',
      message: `${retryDescriptions[failedStage]}${error ? ` 错误原因：${error}` : ''}`,
    },
  })),
  complete: (noteId) => set({
    phase: 'completed',
    noteId,
    recordedAudio: undefined,
    generatedNote: undefined,
    failedStage: undefined,
    isPanelOpen: true,
    isMinimized: false,
    error: '',
    retryDescription: '',
    hasRecoverableRecording: false,
    notification: {
      kind: 'success',
      title: '会议已总结好',
      noteId,
    },
  }),
  fail: (error) => get().failStage('summarizing', error),
  syncExternalState: (snapshot) => set((state) => ({
    isPanelOpen: snapshot.isPanelOpen ?? state.isPanelOpen,
    isMinimized: snapshot.isMinimized ?? state.isMinimized,
    phase: snapshot.phase ?? state.phase,
    elapsedSeconds: snapshot.elapsedSeconds ?? state.elapsedSeconds,
    taskId: snapshot.taskId ?? state.taskId,
    noteId: snapshot.noteId ?? state.noteId,
    error: snapshot.error ?? state.error,
    notification: snapshot.notification !== undefined ? snapshot.notification : state.notification,
  })),
  dismissNotification: () => set({ notification: null }),
  resetSession: () => set(initialState),
}))
