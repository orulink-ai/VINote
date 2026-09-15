import { openMeetingController, publishMeetingState, listenMeetingActions, type MeetingControlAction } from '../../lib/meetingController'
import { useAuthStore } from '../../stores/authStore'
import { DEFAULT_CAPTURE_OPTIONS, START_MEETING_EVENT, type MeetingCaptureOptions } from '../../lib/meetingCapture'
import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { ChevronDown, Loader2, Mic, Minus, Pause, Play, RotateCcw, Square, X } from 'lucide-react'
import clsx from 'clsx'
import { useNavigate } from 'react-router-dom'
import { useAudioRecorder } from '../../hooks/useAudioRecorder'
import {
  closeCurrentRecorderWindow,
  emitRecorderWindowReady,
  emitRecorderWindowState,
  isRecorderWindowRoute,
  isTauriRuntime,
  listenDesktopNavigation,
  listenRecorderOpenPanel,
  listenRecorderWindowState,
  openRecorderWindowWhenReady,
  setRecorderActive,
  setRecorderWindowLayout,
  setRecorderWindowSize,
  showMainWindow,
  startCurrentRecorderWindowDrag,
} from '../../lib/desktopRecorderWindow'
import {
  MEETING_NOTE_SOURCE_TYPE,
  MeetingGenerationError,
  completeMeetingRecordingGeneration,
  createMeetingRecordingTitle,
  fetchMeetingAudioBlob,
  submitMeetingRecording,
} from '../../lib/meetingGeneration'
import { useI18n } from '../../lib/i18n'
import { deleteLocalRecording, savePendingMeeting, type PendingMeeting, generateRecordingId, getRecordedAudio, saveRecordedAudio } from '../../lib/audioStorage'
import { useMeetingRecorderStore, type MeetingRecorderPhase, type MeetingRecorderStage } from '../../stores/meetingRecorderStore'
import { useModelProfileStore } from '../../stores/modelProfileStore'
import { useNoteLibraryStore } from '../../stores/noteLibraryStore'
import { useSTTProfileStore } from '../../stores/sttProfileStore'
import { useTeamStore } from '../../stores/teamStore'

const PANEL_WIDTH = 360
const PANEL_HEIGHT = 132
const EDGE_PADDING = 20
const WAVEFORM_BAR_HEIGHTS = [4, 7, 5, 14, 21, 10, 5, 7, 17, 24, 10, 16, 8, 11, 6, 5, 18, 22, 11, 8, 5, 4] as const
const PROCESSING_PHASES: MeetingRecorderPhase[] = ['requesting', 'stopping', 'uploading', 'transcribing', 'summarizing', 'saving']
const NATIVE_PROTECTED_PHASES: MeetingRecorderPhase[] = ['requesting', 'recording', 'paused', 'stopping', 'uploading', 'transcribing', 'summarizing', 'saving']
const ACTIVE_RECORDING_PHASES: MeetingRecorderPhase[] = ['recording', 'paused', 'requesting', 'uploading', 'transcribing', 'summarizing', 'saving', 'stopping']
// Exact native window sizes per logical state. The window only resizes for the
// minimized pill; everything else (idle, recording, paused, failed, completed)
// keeps a fixed 360x132 so the recorder surface never has to grow.
const RECORDER_WINDOW_SIZE = {
  minimized: { width: 320, height: 48 },
  normal: { width: 360, height: 132 },
} as const

function computeRecorderWindowSize(isMinimized: boolean) {
  if (isMinimized) return RECORDER_WINDOW_SIZE.minimized
  return RECORDER_WINDOW_SIZE.normal
}

function getInitialPosition() {
  if (typeof window === 'undefined') return { x: EDGE_PADDING, y: EDGE_PADDING }
  return {
    x: Math.max(EDGE_PADDING, window.innerWidth - PANEL_WIDTH - EDGE_PADDING),
    y: Math.max(EDGE_PADDING, window.innerHeight - PANEL_HEIGHT - EDGE_PADDING),
  }
}

function clampPosition(x: number, y: number) {
  if (typeof window === 'undefined') return { x, y }
  return {
    x: Math.min(Math.max(EDGE_PADDING, x), Math.max(EDGE_PADDING, window.innerWidth - PANEL_WIDTH - EDGE_PADDING)),
    y: Math.min(Math.max(EDGE_PADDING, y), Math.max(EDGE_PADDING, window.innerHeight - PANEL_HEIGHT - EDGE_PADDING)),
  }
}

function formatElapsedTime(totalSeconds: number) {
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, '0')).join(':')
}

function formatRecorderFailure(error: unknown, copy: ReturnType<typeof useI18n>['copy']['meetingRecorder']) {
  const message = error instanceof Error ? error.message : String(error || '')
  const normalized = message.toLowerCase()
  if (normalized.includes('invalid api key') || normalized.includes('unauthorized') || normalized.includes('401')) {
    return copy.modelConfigRequired
  }
  if (normalized.includes('microphone_denied')) return copy.microphoneDenied
  if (normalized.includes('microphone_restricted')) return copy.microphoneRestricted
  if (normalized.includes('microphone_request_timeout')) return copy.microphoneTimeout
  if (normalized.includes('microphone_unsupported')) return copy.unsupported
  if (normalized.includes('microphone_no-device') || normalized.includes('microphone_no_audio')) return copy.microphoneNoAudio
  if (normalized.includes('microphone_unavailable')) return copy.microphoneUnavailable
  if (normalized.includes('recorder_window_load_timeout')) return copy.windowLoadFailed
  return message || copy.unknownError
}

function stageFromError(error: unknown): MeetingRecorderStage {
  if (error instanceof MeetingGenerationError) return error.stage
  const message = error instanceof Error ? error.message : String(error || '')
  if (message.toLowerCase().includes('microphone_')) return 'uploading'
  return 'summarizing'
}

function phaseLabel(phase: MeetingRecorderPhase, copy: ReturnType<typeof useI18n>['copy']['meetingRecorder']) {
  return copy.phases?.[phase] || copy[phase] || phase
}

function recordingDotClass(phase: MeetingRecorderPhase, activeShadow: string) {
  return clsx(
    'rounded-full transition-colors',
    phase === 'recording'
      ? `bg-[#EF2B2D] ${activeShadow}`
      : phase === 'paused' ? 'bg-amber-400' : 'bg-gray-300',
  )
}

function meetingAudioExtension(audioBlob?: Blob | null) {
  const mime = (audioBlob?.type || '').toLowerCase()
  if (mime.includes('mp4')) return 'm4a'
  if (mime.includes('mpeg')) return 'mp3'
  if (mime.includes('ogg')) return 'ogg'
  if (mime.includes('wav')) return 'wav'
  return 'webm'
}

function buildMeetingDraftContent({
  taskId,
  audioBlob,
  startedAt,
  statusText,
  errorMessage,
}: {
  taskId: string
  audioBlob?: Blob | null
  startedAt: Date
  statusText: string
  errorMessage?: string
}) {
  const durationSeconds = useMeetingRecorderStore.getState().elapsedSeconds
  const audioUrl = taskId ? `/api/task/${taskId}/artifacts/media/source_audio.${meetingAudioExtension(audioBlob)}` : ''
  return [
    '## 会议录音草稿',
    '',
    `- 当前状态：${statusText}`,
    `- 录音时长：${formatElapsedTime(durationSeconds)}`,
    `- 创建时间：${startedAt.toLocaleString()}`,
    audioUrl ? `- 原始音频：[打开录音](${audioUrl})` : '- 原始音频：已保留，等待任务记录同步。',
    errorMessage ? `- 错误原因：${errorMessage}` : '',
    '',
    audioUrl ? `<audio controls src="${audioUrl}"></audio>` : '',
  ].filter(Boolean).join('\n')
}

interface MeetingRecorderDockProps {
  autoStart?: boolean
}

export function MeetingRecorderDock({ autoStart = false }: MeetingRecorderDockProps) {
  const navigate = useNavigate()
  const recorder = useAudioRecorder()
  const { user } = useAuthStore()
  const captureOptionsRef = useRef<MeetingCaptureOptions>(DEFAULT_CAPTURE_OPTIONS)
  const { copy, language } = useI18n()
  const recorderCopy = copy.meetingRecorder
  const isRecorderWindow = isRecorderWindowRoute()
  const isDesktopMainWindow = isTauriRuntime() && !isRecorderWindow
  const { saveNote, updateNote, deleteNote } = useNoteLibraryStore()
  const { currentWorkspace } = useTeamStore()
  const captureWorkspaceRef = useRef(currentWorkspace)
  const { selectedProfileId: selectedModelProfileId, loadProfiles: loadModelProfiles } = useModelProfileStore()
  const { loadProfiles: loadSTTProfiles } = useSTTProfileStore()
  const {
    isPanelOpen,
    isMinimized,
    confirmDiscardOpen,
    phase,
    elapsedSeconds,
    taskId,
    noteId,
    recordedAudio,
    hasRecoverableRecording,
    error,
    retryDescription,
    notification,
    openPanel,
    closePanel,
    requestClose,
    cancelCloseRequest,
    discardSession,
    minimizePanel,
    restorePanel,
    setPhase,
    setElapsedSeconds,
    setTaskId,
    setRecordingId,
    setRecordedAudio,
    setGeneratedNote,
    complete,
    failStage,
    dismissNotification,
    resetSession,
    syncExternalState,
  } = useMeetingRecorderStore()
  const [position, setPosition] = useState(getInitialPosition)
  const [hasCustomPosition, setHasCustomPosition] = useState(false)
  const [useInlineDesktopRecorder, setUseInlineDesktopRecorder] = useState(false)
  const dragOffsetRef = useRef<{ x: number; y: number } | null>(null)
  const minimizedPointerRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number; dragging: boolean } | null>(null)
  const suppressRestoreRef = useRef(false)
  const startedAtRef = useRef<Date | null>(null)
  const draftNoteIdRef = useRef<string | null>(null)
  const draftTitleRef = useRef('')
  const recordingIdRef = useRef<string | null>(null)
  const endedAtRef = useRef<Date | undefined>(undefined)
  const finishInFlightRef = useRef(false)

  useEffect(() => {
    if (recorder.status === 'failed' && ['recording', 'paused'].includes(useMeetingRecorderStore.getState().phase)) {
      failStage('uploading', formatRecorderFailure(new Error(recorder.error), recorderCopy))
    }
  }, [recorder.status, recorder.error, failStage, recorderCopy])

  useEffect(() => {
    if (!isRecorderWindow) return
    void emitRecorderWindowReady()
  }, [isRecorderWindow])

  useEffect(() => {
    void loadModelProfiles()
    void loadSTTProfiles()
  }, [loadModelProfiles, loadSTTProfiles])

  useEffect(() => {
    if (!isTauriRuntime() || isRecorderWindow) return
    let disposed = false
    let unlisten: (() => void) | undefined
    void listenRecorderWindowState((snapshot) => {
      syncExternalState(snapshot)
    }).then((cleanup) => {
      if (disposed) cleanup?.()
      else unlisten = cleanup
    })
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [isRecorderWindow, syncExternalState])

  useEffect(() => {
    if (!isTauriRuntime() || isRecorderWindow) return
    let disposed = false
    let unlisten: (() => void) | undefined
    void listenDesktopNavigation((route) => {
      navigate(route)
    }).then((cleanup) => {
      if (disposed) cleanup?.()
      else unlisten = cleanup
    })
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [isRecorderWindow, navigate])

  useEffect(() => {
    if (!isTauriRuntime() || !isRecorderWindow) return
    let disposed = false
    let unlisten: (() => void) | undefined
    void listenRecorderOpenPanel(() => {
      const state = useMeetingRecorderStore.getState()
      // Reset session BEFORE opening the panel so isPanelOpen is not flipped back to false by initialState.
      if (!ACTIVE_RECORDING_PHASES.includes(state.phase)) {
        resetSession()
      }
      openPanel()
      void setRecorderWindowLayout('expanded')
      if (!ACTIVE_RECORDING_PHASES.includes(useMeetingRecorderStore.getState().phase)) {
        setPhase('idle')
      }
    }).then((cleanup) => {
      if (disposed) cleanup?.()
      else unlisten = cleanup
    })
    return () => {
      disposed = true
      unlisten?.()
    }
  }, [isRecorderWindow, openPanel, resetSession, setPhase])

  useEffect(() => {
    if (!isRecorderWindow) return
    void emitRecorderWindowState({
      isPanelOpen,
      isMinimized,
      phase,
      elapsedSeconds,
      taskId,
      noteId,
      error,
      notification,
    })
  }, [elapsedSeconds, error, isMinimized, isPanelOpen, isRecorderWindow, noteId, notification, phase, taskId])

  useEffect(() => {
    if (!isRecorderWindow && !useInlineDesktopRecorder) return
    const shouldProtectRecorder =
      NATIVE_PROTECTED_PHASES.includes(phase) || Boolean(recordedAudio)
    void setRecorderActive(shouldProtectRecorder)
  }, [isRecorderWindow, useInlineDesktopRecorder, phase, recordedAudio])

  useEffect(() => {
    if (!isRecorderWindow) return
    return () => {
      void setRecorderActive(false)
    }
  }, [isRecorderWindow])

  useEffect(() => {
    if (isDesktopMainWindow && !useInlineDesktopRecorder) return
    setElapsedSeconds(recorder.elapsedSeconds)
  }, [isDesktopMainWindow, useInlineDesktopRecorder, recorder.elapsedSeconds, setElapsedSeconds])

  useEffect(() => {
    if (!isRecorderWindow) return
    const { width, height } = computeRecorderWindowSize(isMinimized)
    void setRecorderWindowSize(width, height)
  }, [isMinimized, isRecorderWindow])

  useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      const state = useMeetingRecorderStore.getState()
      if (state.hasRecoverableRecording) {
        event.preventDefault()
        event.returnValue = recorderCopy.beforeUnload
      }
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => window.removeEventListener('beforeunload', beforeUnload)
  }, [recorderCopy.beforeUnload])

  useEffect(() => {
    const handleResize = () => setPosition((current) => clampPosition(current.x, current.y))
    const handlePointerMove = (event: PointerEvent) => {
      if (minimizedPointerRef.current) {
        const pointer = minimizedPointerRef.current
        const dx = event.clientX - pointer.startX
        const dy = event.clientY - pointer.startY
        if (pointer.dragging || Math.hypot(dx, dy) > 6) {
          pointer.dragging = true
          suppressRestoreRef.current = true
          setHasCustomPosition(true)
          setPosition(clampPosition(pointer.baseX + dx, pointer.baseY + dy))
        }
        return
      }
      if (!dragOffsetRef.current) return
      setPosition(clampPosition(event.clientX - dragOffsetRef.current.x, event.clientY - dragOffsetRef.current.y))
    }
    const handlePointerUp = () => {
      dragOffsetRef.current = null
      minimizedPointerRef.current = null
    }
    window.addEventListener('resize', handleResize)
    window.addEventListener('pointermove', handlePointerMove)
    window.addEventListener('pointerup', handlePointerUp)
    return () => {
      window.removeEventListener('resize', handleResize)
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerup', handlePointerUp)
    }
  }, [])

  const beginDrag = (event: ReactPointerEvent<HTMLElement>) => {
    if (isRecorderWindow) {
      void startCurrentRecorderWindowDrag()
      return
    }
    const current = hasCustomPosition ? position : getInitialPosition()
    setPosition(current)
    setHasCustomPosition(true)
    dragOffsetRef.current = { x: event.clientX - current.x, y: event.clientY - current.y }
  }

  const handlePanelPointerDown = (event: ReactPointerEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('button')) return
    beginDrag(event)
  }

  const handleNativePanelMouseDown = (event: ReactMouseEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest('button')) return
    void startCurrentRecorderWindowDrag()
  }

  const handleMinimizedPointerDown = (event: ReactPointerEvent<HTMLElement>) => {
    if (isRecorderWindow) {
      void startCurrentRecorderWindowDrag()
      return
    }
    const current = hasCustomPosition ? position : getInitialPosition()
    setPosition(current)
    minimizedPointerRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      baseX: current.x,
      baseY: current.y,
      dragging: false,
    }
    suppressRestoreRef.current = false
  }

  const handleMinimize = () => {
    minimizePanel()
    void setRecorderWindowLayout('minimized')
  }

  const handleRestoreClick = () => {
    if (suppressRestoreRef.current) {
      suppressRestoreRef.current = false
      return
    }
    restorePanel()
    void setRecorderWindowLayout('expanded')
  }

  const startLocalRecording = async (options?: MeetingCaptureOptions) => {
    endedAtRef.current = undefined
    setPhase('requesting')
    try {
      if (await recorder.start(options) === false) return
      startedAtRef.current = new Date()
      if (useMeetingRecorderStore.getState().phase === 'requesting') {
        setPhase('recording')
        if (options && isTauriRuntime()) void openMeetingController().catch(() => undefined)
      }
    } catch (startError) {
      failStage('uploading', formatRecorderFailure(startError, recorderCopy))
    }
  }

  const handleOpenLauncher = () => navigate('/meetings')

  const handleStart = async () => {
    if (isTauriRuntime() && !isRecorderWindow && !useInlineDesktopRecorder) {
      try {
        await openRecorderWindowWhenReady()
        closePanel()
      } catch (windowError) {
        failStage('uploading', formatRecorderFailure(windowError, recorderCopy))
        closePanel()
      }
      return
    }

    await startLocalRecording()
  }

  useEffect(() => {
    if (!autoStart || phase !== 'idle' || finishInFlightRef.current) return
    openPanel()
    void setRecorderWindowLayout('expanded')
    void handleStart()
    // Run only for recorder-window bootstrap; phase changes must not restart recording.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoStart])

  const handlePause = () => {
    if (phase !== 'recording') return
    recorder.pause()
    setPhase('paused')
  }

  const handleResume = () => {
    if (phase !== 'paused') return
    recorder.resume()
    setPhase('recording')
  }

  const handleStop = async () => {
    if (phase !== 'paused' && phase !== 'recording') return
    if (finishInFlightRef.current) return
    finishInFlightRef.current = true
    try {
      endedAtRef.current = new Date()
      setPhase('stopping')
      const audioBlob = await recorder.stop()
      if (audioBlob.size === 0) throw new Error('microphone_no_audio')
      setRecordedAudio(audioBlob)
      // Persist the audio locally so it survives a page reload, window close, or restart.
      // History is independent of generation; retain both bytes and owner/workspace metadata.
      const persistedId = recordingIdRef.current || generateRecordingId()
      recordingIdRef.current = persistedId
      setRecordingId(persistedId)
      await saveRecordedAudio(persistedId, audioBlob)
      await savePendingMeeting({ id: persistedId, ownerId: user?.id || '', workspace: captureWorkspaceRef.current,
        options: captureOptionsRef.current, startedAt: (startedAtRef.current || new Date()).toISOString(),
        endedAt: endedAtRef.current.toISOString(),
        fileName: recorder.getRecordingFileName?.(),
        elapsedSeconds: useMeetingRecorderStore.getState().elapsedSeconds })
      recorder.retainRecordingFile?.()
      // Recording history exists independently of STT/LLM generation.
      recorder.reset()
      resetSession()
      closePanel()
      await setRecorderActive(false)
      if (isRecorderWindow) {
        await showMainWindow('/meetings')
        await closeCurrentRecorderWindow()
      } else navigate('/meetings')
    } catch (stopError) {
      const failedStage = stageFromError(stopError)
      const failureMessage = formatRecorderFailure(stopError, recorderCopy)
      await markDraftFailed(failedStage, failureMessage)
      failStage(failedStage, failureMessage)
    } finally {
      finishInFlightRef.current = false
    }
  }

  const generateFromAudio = async (audioBlob: Blob, sttProfileIdOverride?: string) => {
    setPhase('uploading')
    const startedAt = startedAtRef.current || new Date()
    const activeSTTProfileId = sttProfileIdOverride ?? useSTTProfileStore.getState().selectedProfileId
    const response = await submitMeetingRecording({
      audioBlob,
      title: captureOptionsRef.current.title,
      diarize: captureOptionsRef.current.diarize,
      speakerCount: captureOptionsRef.current.speakerCount,
      startedAt,
      endedAt: endedAtRef.current,
      outputLanguage: language,
      summaryMode: 'default',
      modelProfileId: selectedModelProfileId || undefined,
      sttProfileId: activeSTTProfileId || undefined,
    }, { onStage: setPhase })
    setTaskId(response.task_id)
    await createMeetingDraft(response.task_id, audioBlob, startedAt)
    const note = await completeMeetingRecordingGeneration({
      taskId: response.task_id,
      workspace: captureWorkspaceRef.current,
      saveNote: saveCompletedMeetingNote,
      onStage: setPhase,
    })
    setGeneratedNote({ title: note.title, markdown: note.content, taskId: response.task_id })
    if (recordingIdRef.current) {
      // A cleanup failure must not turn an already saved note into a failed task.
      // Its local history entry remains available for a later explicit deletion.
      await deleteLocalRecording(recordingIdRef.current, user?.id || '').catch(() => undefined)
    }
    complete(note.id)
  }

  useEffect(() => {
    if (isRecorderWindow) return
    const startMeeting = (event: Event) => {
      if (ACTIVE_RECORDING_PHASES.includes(useMeetingRecorderStore.getState().phase) || useMeetingRecorderStore.getState().hasRecoverableRecording) return
      captureWorkspaceRef.current = currentWorkspace
      captureOptionsRef.current = (event as CustomEvent<MeetingCaptureOptions>).detail
      draftNoteIdRef.current = null
      recordingIdRef.current = null
      resetSession()
      setUseInlineDesktopRecorder(true)
      openPanel()
      void startLocalRecording(captureOptionsRef.current)
    }
    const restore = (event: Event) => {
      const restoreState = useMeetingRecorderStore.getState()
      if (restoreState.hasRecoverableRecording || ACTIVE_RECORDING_PHASES.includes(restoreState.phase)) return
      const pending = (event as CustomEvent<PendingMeeting>).detail
      if (pending.ownerId !== user?.id) return
      setPhase('requesting')
      void getRecordedAudio(pending.id).then(blob => {
        if (useMeetingRecorderStore.getState().phase !== 'requesting') return
        if (!blob) { failStage('uploading', '找不到本地录制文件。'); return }
        resetSession()
        captureOptionsRef.current = pending.options
        captureWorkspaceRef.current = pending.workspace
        startedAtRef.current = new Date(pending.startedAt)
        endedAtRef.current = pending.endedAt ? new Date(pending.endedAt) : undefined
        recordingIdRef.current = pending.id
        draftNoteIdRef.current = null
        setUseInlineDesktopRecorder(true)
        setRecordingId(pending.id)
        setRecordedAudio(blob)
        setElapsedSeconds(pending.elapsedSeconds)
        setPhase('stopped')
        openPanel()
      })
    }
    window.addEventListener(START_MEETING_EVENT, startMeeting)
    window.addEventListener('vinote-restore-meeting', restore)
    return () => { window.removeEventListener(START_MEETING_EVENT, startMeeting); window.removeEventListener('vinote-restore-meeting', restore) }
  })

  useEffect(() => {
    if (recorder.sourceEnded && (phase === 'recording' || phase === 'paused')) void handleStop()
  }, [recorder.sourceEnded, phase])

  useEffect(() => {
    useMeetingRecorderStore.setState({ preview: recorder.preview, sizeBytes: recorder.sizeBytes })
  }, [recorder.preview, recorder.sizeBytes])

  const handleGenerate = async () => {
    if (phase !== 'stopped' || !recordedAudio || finishInFlightRef.current) return
    finishInFlightRef.current = true
    try {
      await generateFromAudio(recordedAudio)
    } catch (error) {
      const message = formatRecorderFailure(error, recorderCopy)
      await markDraftFailed(stageFromError(error), message)
      failStage(stageFromError(error), message)
    } finally {
      finishInFlightRef.current = false
    }
  }

  const createMeetingDraft = async (draftTaskId: string, audioBlob: Blob, startedAt: Date) => {
    const title = captureOptionsRef.current.title.trim() || createMeetingRecordingTitle(startedAt, language)
    draftTitleRef.current = title
    const body = buildMeetingDraftContent({
      taskId: draftTaskId,
      audioBlob,
      startedAt,
      statusText: recorderCopy.phases.transcribing,
    })
    // Embed the recordingId in the note body so the note detail page can
    // recover the persisted audio from IndexedDB even after a reload.
    const draft = await saveNote(
      title,
      `${body}\n\n<!-- recording_id: ${recordingIdRef.current || ''} -->`,
      undefined,
      draftTaskId,
      captureWorkspaceRef.current,
      audioBlob.type.startsWith('video/') ? 'meeting_video' : MEETING_NOTE_SOURCE_TYPE,
      'pending',
    )
    if (draft) draftNoteIdRef.current = draft.id
  }

  const saveCompletedMeetingNote = async (title: string, content: string) => {
    if (draftNoteIdRef.current) {
      const updated = await updateNote(draftNoteIdRef.current, title, content, 'done')
      if (updated) return updated
    }
    return saveNote(title, content, undefined, useMeetingRecorderStore.getState().taskId || undefined, captureWorkspaceRef.current, captureOptionsRef.current.screen ? 'meeting_video' : MEETING_NOTE_SOURCE_TYPE, 'done')
  }

  const markDraftFailed = async (failedStage: MeetingRecorderStage, failureMessage: string) => {
    if (!draftNoteIdRef.current) return
    const state = useMeetingRecorderStore.getState()
    const statusText = failedStage === 'transcribing' ? recorderCopy.phases.transcribingFailed : recorderCopy.phases.generationFailed
    await updateNote(
      draftNoteIdRef.current,
      draftTitleRef.current || createMeetingRecordingTitle(startedAtRef.current || new Date(), language),
      buildMeetingDraftContent({
        taskId: state.taskId || '',
        audioBlob: state.recordedAudio,
        startedAt: startedAtRef.current || new Date(),
        statusText,
        errorMessage: failureMessage,
      }),
      failedStage === 'transcribing' ? 'transcribing_failed' : 'generation_failed',
    )
  }

  const resolveRetrySTTProfileId = async (failureMessage: string) => {
    if (!failureMessage.toLowerCase().includes('openai-whisper')) return undefined

    await loadSTTProfiles()
    const sttState = useSTTProfileStore.getState()
    const defaultProfile = sttState.profiles.find((profile) => profile.isDefault && profile.isActive)
    if (!defaultProfile || defaultProfile.id === sttState.selectedProfileId) return undefined

    sttState.selectProfile(defaultProfile.id)
    return defaultProfile.id
  }

  const handleRetry = async () => {
    const state = useMeetingRecorderStore.getState()
    if (finishInFlightRef.current) return
    finishInFlightRef.current = true
    try {
      // Saving failed but the LLM already produced a summary — try saving the
      // existing note text again without re-running the pipeline.
      if (state.failedStage === 'saving' && state.generatedNote) {
        setPhase('saving')
        const note = await saveNote(state.generatedNote.title, state.generatedNote.markdown, undefined, state.generatedNote.taskId, captureWorkspaceRef.current, captureOptionsRef.current.screen ? 'meeting_video' : MEETING_NOTE_SOURCE_TYPE, 'done')
        if (!note) throw new MeetingGenerationError('saving', recorderCopy.saveFailed)
        complete(note.id)
        return
      }
      // Recover the recording first — from memory, IndexedDB, or the server's
      // saved artifact. Without audio there is nothing to re-generate from.
      let audio = state.recordedAudio
      if (!audio) {
        // IndexedDB survives reloads, window hides, and full app restarts.
        // The recordingId is stored on the note draft too (see
        // `createMeetingDraft`), so the user can always come back to it.
        const persistedId = state.recordingId || recordingIdRef.current
        if (persistedId) {
          const persisted = await getRecordedAudio(persistedId)
          if (persisted) {
            setRecordedAudio(persisted)
            setRecordingId(persistedId)
            audio = persisted
          }
        }
        // Last resort: ask the backend for the audio it stored when the
        // original task ran. This works as long as the original upload succeeded
        // and `state.taskId` is still known.
        if (!audio && state.taskId) {
          try {
            const restored = await fetchMeetingAudioBlob(state.taskId)
            setRecordedAudio(restored)
            audio = restored
          } catch {
            // Swallow — we'll throw the no-recoverable-audio error below if no
            // other source produced a blob.
          }
        }
        if (!audio) {
          throw new Error(recorderCopy.noRecoverableAudio)
        }
      }
      // Always re-upload and re-generate from the audio. This is the only path
      // that works regardless of whether the previous task is still running or
      // already failed server-side — and it gives the user a fresh chance after
      // fixing their API key, network, etc.
      const retrySTTProfileId = await resolveRetrySTTProfileId(state.error)
      setPhase('uploading')
      await generateFromAudio(audio, retrySTTProfileId)
    } catch (retryError) {
      failStage(stageFromError(retryError), formatRecorderFailure(retryError, recorderCopy))
    } finally {
      finishInFlightRef.current = false
    }
  }

  const handleViewNote = async () => {
    if (!notification?.noteId) return
    const route = `/note/${notification.noteId}`
    if (isRecorderWindow) {
      await showMainWindow(route)
    } else {
      navigate(route)
    }
    dismissNotification()
    // Reset the shared store first so the bottom-right mic launcher
    // reappears in the main window after the recorder window closes.
    closePanel()
    if (isRecorderWindow) {
      discardSession()
      await setRecorderActive(false)
      // Actually destroy the recorder window so the next launcher click
      // always gets a fresh window. `hide()` on macOS doesn't always round-trip
      // back to visible via `show()`, so destroying is the only reliable path.
      await closeCurrentRecorderWindow()
    }
  }

  const handleRequestClose = async () => {
    if (phase === 'requesting' && !hasRecoverableRecording) {
      recorder.reset()
      discardSession()
      if (isRecorderWindow) {
        await setRecorderActive(false)
        await closeCurrentRecorderWindow()
      }
      return
    }
    if (hasRecoverableRecording || NATIVE_PROTECTED_PHASES.includes(phase)) {
      requestClose()
      return
    }

    closePanel()
    if (isRecorderWindow) {
      await setRecorderActive(false)
      await closeCurrentRecorderWindow()
    }
  }

  const handleConfirmDiscard = async () => {
    const persistedRecordingId = recordingIdRef.current || useMeetingRecorderStore.getState().recordingId
    const draftNoteId = draftNoteIdRef.current

    recorder.reset()
    if (persistedRecordingId) {
      try { await deleteLocalRecording(persistedRecordingId, user?.id || '') }
      catch (cause) { failStage('uploading', cause instanceof Error ? cause.message : '无法删除本地录制'); return }
    }
    if (draftNoteId) {
      await deleteNote(draftNoteId)
    }

    recordingIdRef.current = null
    draftNoteIdRef.current = null
    draftTitleRef.current = ''
    discardSession()

    if (isRecorderWindow) {
      await setRecorderActive(false)
      await closeCurrentRecorderWindow()
    }
  }

  const controlsRef = useRef<(action: MeetingControlAction) => void>(() => undefined)
  controlsRef.current = action => {
    const state = useMeetingRecorderStore.getState()
    if (action === 'sync') void publishMeetingState({ phase: state.phase, elapsedSeconds: state.elapsedSeconds, noteId: state.noteId, error: state.error })
    if (action === 'pause') handlePause()
    if (action === 'resume') handleResume()
    if (action === 'stop') void handleStop()
    if (action === 'generate') void handleGenerate()
    if (action === 'retry') void handleRetry()
  }
  useEffect(() => {
    if (!isTauriRuntime() || isRecorderWindow) return
    let disposed = false
    let unsubscribe: (() => void) | undefined
    void listenMeetingActions(action => controlsRef.current(action)).then(cleanup => {
      if (disposed) cleanup()
      else unsubscribe = cleanup
    })
    return () => { disposed = true; unsubscribe?.() }
  }, [isRecorderWindow])
  useEffect(() => {
    if (useInlineDesktopRecorder) void publishMeetingState({ phase, elapsedSeconds, noteId, error })
  }, [useInlineDesktopRecorder, phase, elapsedSeconds, noteId, error])

  const handleReRecord = () => {
    const previousRecordingId = recordingIdRef.current
    recorder.reset()
    void setRecorderActive(false)
    void setRecorderWindowLayout('expanded')
    if (previousRecordingId) {
      void deleteLocalRecording(previousRecordingId, user?.id || '').catch(() => undefined)
    }
    recordingIdRef.current = null
    resetSession()
    setPosition(getInitialPosition())
    setHasCustomPosition(false)
    openPanel()
    setPhase('idle')
  }

  const elapsedLabel = formatElapsedTime(elapsedSeconds)
  const isProcessing = PROCESSING_PHASES.includes(phase)
  const canStart = phase === 'idle' || phase === 'failed'
  const canStop = phase === 'paused' || phase === 'recording'
  const canRetry = phase === 'failed' && (hasRecoverableRecording || Boolean(taskId))
  const statusLabel = phaseLabel(phase, recorderCopy)
  const statusText = phase === 'failed' && error
    ? `${recordedAudio ? `${recorderCopy.audioPreserved} · ` : ''}${error}${canRetry && retryDescription ? ` · ${retryDescription}` : ''}`
    : notification?.kind === 'success'
      ? recorderCopy.completedNotice
      : isProcessing
        ? `${recorderCopy.processingHint}: ${statusLabel}`
        : statusLabel
  const dockedStyle = hasCustomPosition ? { left: position.x, top: position.y } : { right: EDGE_PADDING, bottom: EDGE_PADDING }
  const shouldRenderRecorderSurface = isPanelOpen && (!isDesktopMainWindow || useInlineDesktopRecorder)
  const minimizedContainerClass = clsx(
    'inline-flex h-12 w-[320px] items-center gap-3 rounded-full border border-white/80 bg-white px-3.5 pr-4 text-base font-medium text-[#111827]',
    isRecorderWindow ? '' : 'shadow-[0_8px_22px_rgba(15,23,42,0.14)]',
    isRecorderWindow ? 'relative' : 'fixed z-50',
  )
  const expandedContainerClass = clsx(
    'box-border w-[360px] rounded-[22px] border border-white/80 bg-white px-4 py-3 text-[#111827]',
    isRecorderWindow ? '' : 'shadow-[0_12px_28px_rgba(15,23,42,0.14)]',
    isRecorderWindow ? 'relative min-h-[132px]' : 'fixed z-50 max-w-[calc(100vw-24px)]',
  )

  return (
    <div
      data-testid={isRecorderWindow ? 'meeting-recorder-native-surface' : undefined}
      className={isRecorderWindow ? 'meeting-recorder-native-surface box-border h-screen w-screen overflow-hidden bg-transparent' : undefined}
    >
      {!isPanelOpen && !isRecorderWindow ? (
        <button
          type="button"
          onClick={handleOpenLauncher}
          aria-label={recorderCopy.openPanel}
          className="fixed bottom-5 right-5 z-50 inline-flex h-[52px] w-[52px] items-center justify-center rounded-full border border-white/80 bg-white text-[#0EA5A6] shadow-[0_8px_20px_rgba(15,23,42,0.16)] transition hover:-translate-y-0.5 hover:shadow-[0_12px_26px_rgba(15,23,42,0.16)]"
        >
          <span data-testid="meeting-recorder-idle-dot" className={clsx('absolute right-1 top-1 h-2.5 w-2.5', recordingDotClass(phase, 'shadow-[0_0_0_3px_rgba(239,43,45,0.12)]'))} />
          <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-[#F9FAFB] ring-1 ring-gray-100">
            <Mic className="h-6 w-6" strokeWidth={2.6} />
          </span>
        </button>
      ) : null}

      {shouldRenderRecorderSurface && isMinimized ? (
        <div
          className={minimizedContainerClass}
          style={isRecorderWindow ? undefined : dockedStyle}
          onPointerDown={isRecorderWindow ? undefined : handleMinimizedPointerDown}
        >
          <span
            aria-label={recorderCopy.minimizedDragHandle}
            role="button"
            tabIndex={0}
            data-tauri-drag-region={isRecorderWindow ? 'true' : undefined}
            onPointerDown={(event) => {
              event.stopPropagation()
              beginDrag(event)
            }}
            className="-ml-1 mr-1 h-6 w-2 shrink-0 cursor-grab rounded-full bg-white shadow-[0_0_0_1px_rgba(15,23,42,0.08),0_2px_8px_rgba(15,23,42,0.16)] transition-all hover:w-3 active:cursor-grabbing"
          />
          <button type="button" onClick={handleRestoreClick} aria-label={recorderCopy.restore} className="inline-flex flex-1 items-center gap-3 text-left">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#E5F7F5] text-[#0EA5A6]">
              <Mic className="h-5 w-5" strokeWidth={2.6} />
            </span>
            <span>{recorderCopy.title}</span>
            <span data-testid="meeting-recorder-minimized-dot" className={clsx('h-2.5 w-2.5', recordingDotClass(phase, 'shadow-[0_0_0_4px_rgba(239,43,45,0.10)]'))} />
            <span className="font-mono text-sm font-normal tabular-nums text-[#8B9099]">{elapsedLabel}</span>
            <ChevronDown className="h-5 w-5 text-[#111827]" />
          </button>
        </div>
      ) : null}

      {shouldRenderRecorderSurface && !isMinimized ? (
        <section
          aria-label={recorderCopy.title}
          className={expandedContainerClass}
          style={isRecorderWindow ? undefined : dockedStyle}
          onPointerDown={isRecorderWindow ? undefined : handlePanelPointerDown}
        >
          {confirmDiscardOpen ? (
            <div
              role="dialog"
              aria-label={recorderCopy.discardTitle}
              className="flex min-h-[108px] items-center justify-between gap-3"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-[#111827]">{recorderCopy.discardTitle}</div>
                <p className="mt-1 line-clamp-2 text-xs leading-4 text-[#6B7280]">{recorderCopy.discardBody}</p>
              </div>
              <div className="flex shrink-0 flex-col gap-2">
                <button
                  type="button"
                  onClick={() => {
                    cancelCloseRequest()
                    if (phase === 'paused') handleResume()
                  }}
                  className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-[#111827] hover:bg-gray-50"
                >
                  {recorderCopy.keepRecording}
                </button>
                <button
                  type="button"
                  onClick={() => void handleConfirmDiscard()}
                  className="rounded-lg bg-[#EF2B2D] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#dc2626]"
                >
                  {recorderCopy.discard}
                </button>
              </div>
            </div>
          ) : (
            <>
          <div
            data-testid="recorder-drag-handle"
            data-tauri-drag-region={isRecorderWindow ? 'true' : undefined}
            onMouseDown={isRecorderWindow ? handleNativePanelMouseDown : undefined}
            className="absolute inset-x-0 top-0 h-9 cursor-grab"
            aria-label={recorderCopy.dragRegion}
          />
          <div className="absolute right-3 top-2.5 z-10 flex items-center gap-2.5">
            <button type="button" onClick={handleMinimize} aria-label={recorderCopy.minimize} className="inline-flex h-6 w-6 items-center justify-center rounded-full text-[#8B9099] hover:bg-gray-100">
              <Minus className="h-4 w-4" />
            </button>
            <button type="button" onClick={() => void handleRequestClose()} aria-label={recorderCopy.close} className="inline-flex h-6 w-6 items-center justify-center rounded-full text-[#8B9099] hover:bg-gray-100">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div
            data-tauri-drag-region={isRecorderWindow ? 'true' : undefined}
            onMouseDown={isRecorderWindow ? handleNativePanelMouseDown : undefined}
            className="flex h-full cursor-grab items-center gap-3"
          >
            <div className="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[#E5F7F5] text-[#0EA5A6]">
              <Mic className="h-7 w-7" strokeWidth={2.6} />
            </div>
            <div className="h-16 w-px bg-gray-200" />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold leading-5">{isProcessing || phase === 'failed' ? statusLabel : recorderCopy.title}</div>
              <div className="mt-2 flex items-center gap-2.5">
                <span data-testid="meeting-recorder-expanded-dot" className={clsx('h-2.5 w-2.5', recordingDotClass(phase, 'shadow-[0_0_0_4px_rgba(239,43,45,0.10)]'))} />
                <span className="font-mono text-xl font-semibold leading-none tabular-nums tracking-tight">{elapsedLabel}</span>
              </div>
              {(phase === 'recording' || phase === 'paused') && <div className="mt-3 flex h-6 items-center gap-0.5 overflow-hidden" aria-label={recorderCopy.waveformLabel}>
                {WAVEFORM_BAR_HEIGHTS.map((height, index) => (
                  <span
                    key={`wave-${index}`}
                    className={clsx('w-0.5 rounded-full bg-[#0EA5A6]', phase === 'recording' ? 'animate-pulse' : 'opacity-45')}
                    style={{ height, animationDelay: `${index * 60}ms` }}
                  />
                ))}
              </div>}
              <div role={phase === 'failed' ? 'alert' : 'status'} data-testid="meeting-recorder-status" className={clsx('mt-1 line-clamp-2 max-w-[150px] text-[11px] leading-4', phase === 'failed' ? 'text-red-600' : 'text-[#8B9099]')} title={statusText}>
                {statusText}
              </div>
            </div>
            <div data-testid="meeting-recorder-controls" className="ml-2 mt-1 flex shrink-0 items-center gap-3">
              {isProcessing ? (
                <div className="flex flex-col items-center gap-2 text-xs text-blue-600" role="status">
                  <Loader2 className="h-8 w-8 animate-spin" />
                  <span>{statusLabel}</span>
                </div>
              ) : phase === 'stopped' ? (
                <div className="flex flex-col gap-2">
                  <button type="button" onClick={() => void handleGenerate()} className="rounded-lg bg-primary-light px-3 py-2 text-xs text-white">{language === 'zh-CN' ? '生成会议纪要' : 'Generate minutes'}</button>
                  <button type="button" onClick={() => void handleRequestClose()} className="text-xs text-red-600">{recorderCopy.discard}</button>
                </div>
              ) : phase === 'completed' ? (
                <button type="button" onClick={() => void handleViewNote()} className="rounded-lg bg-primary-light px-3 py-2 text-xs text-white">{recorderCopy.viewNote}</button>
              ) : phase === 'failed' ? (
                <>
                  <button
                    type="button"
                    onClick={handleReRecord}
                    disabled={isProcessing}
                    aria-label={recorderCopy.record}
                    className="group flex flex-col items-center gap-1 text-xs text-[#111827] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <span className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-gray-200 bg-white shadow-sm group-hover:bg-gray-50">
                      <Mic className="h-5 w-5" strokeWidth={2.4} />
                    </span>
                    {recorderCopy.record}
                  </button>
                  {canRetry ? (
                    <button
                      type="button"
                      onClick={() => void handleRetry()}
                      disabled={isProcessing}
                      aria-label={recorderCopy.retry}
                      className="group flex flex-col items-center gap-1 text-xs text-[#111827] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-[#111827] text-white shadow-[0_8px_16px_rgba(17,24,39,0.22)] group-hover:bg-[#0b1220]">
                        <RotateCcw className="h-4 w-4" />
                      </span>
                      {recorderCopy.retry}
                    </button>
                  ) : null}
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={canStart ? () => void handleStart() : phase === 'paused' ? handleResume : handlePause}
                    disabled={isProcessing}
                    aria-label={canStart ? recorderCopy.start : phase === 'paused' ? recorderCopy.resume : recorderCopy.pause}
                    className="group flex flex-col items-center gap-1 text-xs text-[#111827] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <span className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-gray-200 bg-white shadow-sm group-hover:bg-gray-50">
                      {canStart || phase === 'paused' ? <Play className="h-5 w-5" fill="currentColor" /> : <Pause className="h-5 w-5" fill="currentColor" />}
                    </span>
                    {canStart ? recorderCopy.start : phase === 'paused' ? recorderCopy.resume : recorderCopy.pause}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleStop()}
                    disabled={isProcessing || !canStop}
                    aria-label={recorderCopy.stop}
                    className="group flex flex-col items-center gap-1 text-xs text-[#111827] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <span className={clsx(
                      'inline-flex h-10 w-10 items-center justify-center rounded-full text-white shadow-[0_8px_16px_rgba(239,43,45,0.22)]',
                      phase === 'recording' ? 'bg-[#FCA5A5]' : 'bg-[#EF2B2D] group-hover:bg-[#dc2626]',
                    )}>
                      {isProcessing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Square className="h-4 w-4" fill="currentColor" />}
                    </span>
                    {recorderCopy.stop}
                  </button>
                </>
              )}
            </div>
          </div>
            </>
          )}
        </section>
      ) : null}

    </div>
  )
}
