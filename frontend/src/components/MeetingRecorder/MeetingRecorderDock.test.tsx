import { getRecordedAudio, savePendingMeeting } from '../../lib/audioStorage'
import { START_MEETING_EVENT, DEFAULT_CAPTURE_OPTIONS } from '../../lib/meetingCapture'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MeetingRecorderDock } from './MeetingRecorderDock'
import { I18nProvider } from '../../lib/i18n'
import { useMeetingRecorderStore } from '../../stores/meetingRecorderStore'

const navigate = vi.fn()
const audioRecorderMock = vi.hoisted(() => ({
  start: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  stop: vi.fn(),
  reset: vi.fn(),
}))
const meetingGenerationMock = vi.hoisted(() => ({
  submitMeetingRecording: vi.fn(),
  completeMeetingRecordingGeneration: vi.fn(),
  fetchMeetingAudioBlob: vi.fn(),
}))
const desktopRecorderWindowMock = vi.hoisted(() => ({
  isTauriRuntime: vi.fn(() => false),
  isRecorderWindowRoute: vi.fn(() => false),
  openRecorderWindowWhenReady: vi.fn(),
  setRecorderActive: vi.fn(),
  setRecorderWindowLayout: vi.fn(),
  setRecorderWindowSize: vi.fn(),
  showMainWindow: vi.fn(),
  closeCurrentRecorderWindow: vi.fn(),
  startCurrentRecorderWindowDrag: vi.fn(),
  emitRecorderWindowState: vi.fn(),
  emitRecorderOpenPanel: vi.fn(),
  emitRecorderWindowReady: vi.fn(),
  listenRecorderWindowState: vi.fn(),
  listenDesktopNavigation: vi.fn(),
  listenRecorderOpenPanel: vi.fn(),
}))
const saveNoteMock = vi.hoisted(() => vi.fn())
const updateNoteMock = vi.hoisted(() => vi.fn())
const sttProfileStoreMock = vi.hoisted(() => ({
  state: {
    profiles: [] as Array<{ id: string; isDefault: boolean; isActive: boolean }>,
    selectedProfileId: '',
    loadProfiles: vi.fn(),
    selectProfile: vi.fn((id: string) => {
      sttProfileStoreMock.state.selectedProfileId = id
    }),
  },
}))

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigate }
})

vi.mock('../../hooks/useAudioRecorder', () => ({
  useAudioRecorder: () => ({
    isSupported: true,
    elapsedSeconds: 0,
    error: '',
    start: audioRecorderMock.start,
    pause: audioRecorderMock.pause,
    resume: audioRecorderMock.resume,
    stop: audioRecorderMock.stop,
    reset: audioRecorderMock.reset,
  }),
}))

vi.mock('../../stores/authStore', () => ({
  useAuthStore: () => ({ initialized: true, user: { id: 'user-1' } }),
}))

vi.mock('../../stores/languageStore', () => ({
  useLanguageStore: () => ({
    language: 'zh-CN',
    setLanguage: vi.fn(),
    syncWithAccount: vi.fn(),
  }),
}))

vi.mock('../../stores/modelProfileStore', () => ({
  useModelProfileStore: () => ({ selectedProfileId: '', loadProfiles: vi.fn() }),
}))

vi.mock('../../stores/sttProfileStore', () => ({
  useSTTProfileStore: Object.assign(
    () => ({
      selectedProfileId: sttProfileStoreMock.state.selectedProfileId,
      loadProfiles: sttProfileStoreMock.state.loadProfiles,
    }),
    {
      getState: () => sttProfileStoreMock.state,
    },
  ),
}))

vi.mock('../../stores/teamStore', () => ({
  useTeamStore: () => ({ currentWorkspace: { scope: 'personal' } }),
}))

vi.mock('../../stores/noteLibraryStore', () => ({
  useNoteLibraryStore: () => ({ saveNote: saveNoteMock, updateNote: updateNoteMock }),
}))

vi.mock('../../lib/meetingGeneration', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/meetingGeneration')>()
  return {
    ...actual,
    submitMeetingRecording: meetingGenerationMock.submitMeetingRecording,
    completeMeetingRecordingGeneration: meetingGenerationMock.completeMeetingRecordingGeneration,
    fetchMeetingAudioBlob: meetingGenerationMock.fetchMeetingAudioBlob,
  }
})

vi.mock('../../lib/desktopRecorderWindow', () => desktopRecorderWindowMock)
vi.mock('../../lib/meetingController', () => ({
  openMeetingController: vi.fn().mockResolvedValue(undefined),
  publishMeetingState: vi.fn().mockResolvedValue(undefined),
  listenMeetingActions: vi.fn().mockResolvedValue(() => {}),
}))

function renderDock(props?: { autoStart?: boolean }) {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <MeetingRecorderDock {...props} />
      </I18nProvider>
    </MemoryRouter>,
  )
}

vi.mock('../../lib/audioStorage', async (importOriginal) => ({ ...(await importOriginal<object>()), savePendingMeeting: vi.fn(), deletePendingMeeting: vi.fn(), deleteLocalRecording: vi.fn().mockResolvedValue(undefined), getRecordedAudio: vi.fn().mockResolvedValue(null) }))

async function startMeeting() {
  act(() => { window.dispatchEvent(new CustomEvent(START_MEETING_EVENT, { detail: DEFAULT_CAPTURE_OPTIONS })) })
  await waitFor(() => expect(audioRecorderMock.start).toHaveBeenCalled())
}

async function restoreSavedRecording() {
  await waitFor(() => expect(savePendingMeeting).toHaveBeenCalled())
  await waitFor(() => expect(useMeetingRecorderStore.getState().phase).toBe('idle'))
  vi.mocked(getRecordedAudio).mockResolvedValueOnce(new Blob(['audio'], { type: 'audio/webm' }))
  const pending = vi.mocked(savePendingMeeting).mock.calls.at(-1)![0]
  act(() => { window.dispatchEvent(new CustomEvent('vinote-restore-meeting', { detail: pending })) })
}

describe('MeetingRecorderDock', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useMeetingRecorderStore.getState().resetSession()
    audioRecorderMock.start.mockResolvedValue(undefined)
    audioRecorderMock.stop.mockResolvedValue(new Blob(['audio'], { type: 'audio/webm' }))
    meetingGenerationMock.submitMeetingRecording.mockResolvedValue({ task_id: 'task-1' })
    meetingGenerationMock.completeMeetingRecordingGeneration.mockImplementation(async ({ saveNote }) => saveNote('会议录音 2026/07/01', '# Summary'))
    saveNoteMock.mockResolvedValue({ id: 'draft-1', title: '会议录音', content: '# Draft', taskId: 'task-1', status: 'pending' })
    updateNoteMock.mockResolvedValue({ id: 'draft-1', title: '会议录音', content: '# Summary', taskId: 'task-1', status: 'done' })
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(false)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(false)
    desktopRecorderWindowMock.openRecorderWindowWhenReady.mockResolvedValue('created')
    desktopRecorderWindowMock.setRecorderActive.mockResolvedValue(undefined)
    desktopRecorderWindowMock.setRecorderWindowLayout.mockResolvedValue(undefined)
    desktopRecorderWindowMock.setRecorderWindowSize.mockResolvedValue(undefined)
    desktopRecorderWindowMock.showMainWindow.mockResolvedValue(undefined)
    desktopRecorderWindowMock.closeCurrentRecorderWindow.mockResolvedValue(undefined)
    desktopRecorderWindowMock.startCurrentRecorderWindowDrag.mockResolvedValue(undefined)
    desktopRecorderWindowMock.emitRecorderWindowState.mockResolvedValue(undefined)
    desktopRecorderWindowMock.emitRecorderOpenPanel.mockResolvedValue(undefined)
    desktopRecorderWindowMock.emitRecorderWindowReady.mockResolvedValue(undefined)
    desktopRecorderWindowMock.listenRecorderWindowState.mockResolvedValue(undefined)
    desktopRecorderWindowMock.listenDesktopNavigation.mockResolvedValue(undefined)
    desktopRecorderWindowMock.listenRecorderOpenPanel.mockResolvedValue(undefined)
    sttProfileStoreMock.state.profiles = []
    sttProfileStoreMock.state.selectedProfileId = ''
    sttProfileStoreMock.state.loadProfiles.mockResolvedValue(undefined)
    sttProfileStoreMock.state.selectProfile.mockClear()
    meetingGenerationMock.fetchMeetingAudioBlob.mockResolvedValue(new Blob(['audio-restored'], { type: 'audio/webm' }))
  })

  it('does not render a global recording shortcut while idle', () => {
    renderDock()
    expect(screen.queryByRole('button', { name: '开始会议录音' })).not.toBeInTheDocument()
    expect(audioRecorderMock.start).not.toHaveBeenCalled()
  })

  it('allows stopping directly while recording', async () => {
    renderDock()

    await startMeeting()

    const stopWhileRecording = screen.getByRole('button', { name: '停止' })
    expect(stopWhileRecording).toBeEnabled()
    await userEvent.click(stopWhileRecording)
    expect(audioRecorderMock.stop).toHaveBeenCalledOnce()
    await waitFor(() => expect(savePendingMeeting).toHaveBeenCalled())
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/meetings'))
    expect(useMeetingRecorderStore.getState().recordedAudio).toBeUndefined()
    expect(meetingGenerationMock.submitMeetingRecording).not.toHaveBeenCalled()
  })

  it('starts desktop capture in the initiating window to retain screen-picker activation', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    renderDock()
    await startMeeting()
    expect(audioRecorderMock.start).toHaveBeenCalledWith(DEFAULT_CAPTURE_OPTIONS)
    expect(desktopRecorderWindowMock.openRecorderWindowWhenReady).not.toHaveBeenCalled()
    expect(screen.getByRole('region', { name: '会议录音' })).toBeInTheDocument()
  })

  it('auto-starts recording when mounted inside the native recorder window', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(true)
    renderDock({ autoStart: true })

    await waitFor(() => expect(audioRecorderMock.start).toHaveBeenCalledTimes(1))
    expect(desktopRecorderWindowMock.emitRecorderWindowReady).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('region', { name: '会议录音' })).toBeInTheDocument()
    expect(desktopRecorderWindowMock.setRecorderWindowLayout).toHaveBeenCalledWith('expanded')
  })

  it('renders recorder-window content without in-app fixed overlay positioning', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(true)
    renderDock({ autoStart: true })

    const region = await screen.findByRole('region', { name: '会议录音' })

    expect(screen.getByTestId('meeting-recorder-native-surface')).toBeInTheDocument()
    expect(region).not.toHaveClass('fixed')
    expect(region).toHaveClass('relative')
    expect(region).toHaveClass('min-h-[132px]')
    // The drag region lives on the title bar, not the whole section, so the
    // close/minimize buttons remain clickable inside the panel.
    expect(screen.getByTestId('recorder-drag-handle')).toHaveAttribute('data-tauri-drag-region', 'true')
  })

  it('uses native dragging from the recorder-window panel surface', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(true)
    renderDock({ autoStart: true })

    const dragHandle = await screen.findByTestId('recorder-drag-handle')
    fireEvent.mouseDown(dragHandle)

    expect(desktopRecorderWindowMock.startCurrentRecorderWindowDrag).toHaveBeenCalled()
  })

  it('resizes the native recorder window when minimizing and restoring', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(true)
    renderDock({ autoStart: true })

    await waitFor(() => expect(audioRecorderMock.start).toHaveBeenCalledTimes(1))
    desktopRecorderWindowMock.setRecorderWindowLayout.mockClear()

    await userEvent.click(screen.getByRole('button', { name: '最小化' }))
    expect(desktopRecorderWindowMock.setRecorderWindowLayout).toHaveBeenCalledWith('minimized')

    await userEvent.click(screen.getByRole('button', { name: '恢复会议录音悬浮窗' }))
    expect(desktopRecorderWindowMock.setRecorderWindowLayout).toHaveBeenCalledWith('expanded')
  })

  it('stops recording, creates an audio draft, and completes the same note', async () => {
    renderDock()

    await startMeeting()
    await userEvent.click(screen.getByRole('button', { name: '暂停' }))
    await userEvent.click(screen.getByRole('button', { name: '停止' }))
    await restoreSavedRecording()
    await userEvent.click(await screen.findByRole('button', { name: '生成会议纪要' }))

    await waitFor(() => {
      expect(saveNoteMock).toHaveBeenCalledWith(
        expect.stringContaining('会议录音'),
        expect.stringContaining('/api/task/task-1/artifacts/media/source_audio.webm'),
        undefined,
        'task-1',
        { scope: 'personal' },
        'meeting_recording',
        'pending',
      )
      expect(updateNoteMock).toHaveBeenCalledWith('draft-1', '会议录音 2026/07/01', '# Summary', 'done')
    })
    expect(screen.getByRole('button', { name: '查看纪要' })).toBeInTheDocument()
  })

  it('keeps recorded audio after generation failure and offers regenerate vs re-record', async () => {
    meetingGenerationMock.completeMeetingRecordingGeneration.mockRejectedValue(new Error('Error code: 401 - invalid_api_key'))
    renderDock()

    await startMeeting()
    await userEvent.click(screen.getByRole('button', { name: '暂停' }))
    await userEvent.click(screen.getByRole('button', { name: '停止' }))
    await restoreSavedRecording()
    await userEvent.click(await screen.findByRole('button', { name: '生成会议纪要' }))
    const statusLine = await screen.findByTestId('meeting-recorder-status')
    expect(statusLine).toHaveTextContent('音频已保留')
    expect(statusLine).toHaveTextContent('请先配置可用的 LLM 和 STT API Key')
    expect(useMeetingRecorderStore.getState().recordedAudio).toBeInstanceOf(Blob)
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '录制' })).toBeInTheDocument()
  })

  it('does not offer retry when the microphone produced no audio', async () => {
    audioRecorderMock.stop.mockRejectedValueOnce(new Error('microphone_no_audio'))
    renderDock()

    await startMeeting()
    await userEvent.click(screen.getByRole('button', { name: '暂停' }))
    await userEvent.click(screen.getByRole('button', { name: '停止' }))

    const statusLine = await screen.findByTestId('meeting-recorder-status')
    expect(statusLine).toHaveTextContent('没有采集到麦克风音频')
    expect(statusLine).not.toHaveTextContent('音频已保留')
    expect(screen.getByRole('button', { name: '录制' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument()
  })

  it('requires explicit confirmation before discarding an active recording', async () => {
    renderDock()

    await startMeeting()
    await userEvent.click(screen.getByRole('button', { name: '关闭' }))

    expect(screen.getByRole('dialog', { name: '放弃这段会议录音？' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '会议录音' })).toBeInTheDocument()
    expect(audioRecorderMock.reset).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: '继续录音' }))
    expect(screen.queryByRole('dialog', { name: '放弃这段会议录音？' })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: '会议录音' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '关闭' }))
    await userEvent.click(screen.getByRole('button', { name: '放弃' }))

    expect(audioRecorderMock.reset).toHaveBeenCalledTimes(1)
    await waitFor(() =>
      expect(screen.queryByRole('region', { name: '会议录音' })).not.toBeInTheDocument(),
    )
  })

  it('keeps minimized recorder minimized after drag', async () => {
    renderDock()

    await startMeeting()
    await userEvent.click(screen.getByRole('button', { name: '最小化' }))

    const dragHandle = screen.getByLabelText('拖动已最小化的会议录音')
    await userEvent.pointer([
      { target: dragHandle, keys: '[MouseLeft>]', coords: { x: 900, y: 600 } },
      { target: dragHandle, coords: { x: 930, y: 620 } },
      { target: dragHandle, keys: '[/MouseLeft]', coords: { x: 930, y: 620 } },
    ])

    expect(screen.queryByRole('region', { name: '会议录音' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '恢复会议录音悬浮窗' })).toBeInTheDocument()
  })

  it('syncs recorder-window state events into the main window store without mirroring the desktop panel', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    let handler: ((snapshot: { isPanelOpen: boolean; phase: 'recording'; elapsedSeconds: number }) => void) | undefined
    desktopRecorderWindowMock.listenRecorderWindowState.mockImplementation(async (nextHandler) => {
      handler = nextHandler
      return undefined
    })
    renderDock()

    act(() => handler?.({ isPanelOpen: true, phase: 'recording', elapsedSeconds: 12 }))

    expect(useMeetingRecorderStore.getState().phase).toBe('recording')
    expect(useMeetingRecorderStore.getState().elapsedSeconds).toBe(12)
    expect(screen.queryByRole('region', { name: '会议录音' })).not.toBeInTheDocument()
  })

  it('closes (destroys) the native recorder window on close when no recoverable recording exists', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(true)
    renderDock({ autoStart: true })

    await waitFor(() => expect(audioRecorderMock.start).toHaveBeenCalledTimes(1))
    act(() => {
      useMeetingRecorderStore.getState().resetSession()
      useMeetingRecorderStore.getState().openPanel()
      useMeetingRecorderStore.getState().setPhase('completed')
    })

    await userEvent.click(screen.getByRole('button', { name: '关闭' }))

    expect(desktopRecorderWindowMock.closeCurrentRecorderWindow).toHaveBeenCalled()
  })

  it('does not render an idle desktop recording shortcut', () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    renderDock()
    expect(screen.queryByRole('button', { name: '开始会议录音' })).not.toBeInTheDocument()
    expect(desktopRecorderWindowMock.openRecorderWindowWhenReady).not.toHaveBeenCalled()
  })

  it('re-opens the recorder panel when the open-panel event fires in recorder-window mode', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(true)
    let openHandler: (() => void) | undefined
    desktopRecorderWindowMock.listenRecorderOpenPanel.mockImplementation(async (handler) => {
      openHandler = handler
      return undefined
    })

    renderDock({ autoStart: true })

    await waitFor(() => expect(audioRecorderMock.start).toHaveBeenCalledTimes(1))
    // Force a non-active state so the listener resets to idle on re-open.
    act(() => {
      useMeetingRecorderStore.getState().resetSession()
      useMeetingRecorderStore.getState().openPanel()
      useMeetingRecorderStore.getState().setPhase('completed')
      useMeetingRecorderStore.getState().closePanel()
    })
    expect(screen.queryByRole('region', { name: '会议录音' })).not.toBeInTheDocument()

    act(() => openHandler?.())

    await waitFor(() => expect(screen.getByRole('region', { name: '会议录音' })).toBeInTheDocument())
    expect(useMeetingRecorderStore.getState().phase).toBe('idle')
  })

  it('falls back to fetching the saved audio from the server when recordedAudio is missing but taskId is present', async () => {
    renderDock()

    act(() => {
      useMeetingRecorderStore.getState().resetSession()
      useMeetingRecorderStore.getState().setTaskId('task-recovered')
      useMeetingRecorderStore.getState().setPhase('failed')
      useMeetingRecorderStore.getState().failStage('uploading', 'network')
    })

    await userEvent.click(screen.getByRole('button', { name: '重试' }))

    await waitFor(() =>
      expect(meetingGenerationMock.fetchMeetingAudioBlob).toHaveBeenCalledWith('task-recovered'),
    )
    await waitFor(() =>
      expect(meetingGenerationMock.submitMeetingRecording).toHaveBeenCalled(),
    )
  })

  it('keeps the native recorder window at 132 px across all states, including discard confirmation', async () => {
    desktopRecorderWindowMock.isTauriRuntime.mockReturnValue(true)
    desktopRecorderWindowMock.isRecorderWindowRoute.mockReturnValue(true)
    renderDock({ autoStart: true })

    await waitFor(() => expect(audioRecorderMock.start).toHaveBeenCalledTimes(1))
    expect(desktopRecorderWindowMock.setRecorderWindowSize).toHaveBeenLastCalledWith(360, 132)

    act(() => {
      useMeetingRecorderStore.getState().setPhase('failed')
      useMeetingRecorderStore.getState().failStage('summarizing', 'boom')
    })
    await waitFor(() => expect(desktopRecorderWindowMock.setRecorderWindowSize).toHaveBeenLastCalledWith(360, 132))

    act(() => {
      useMeetingRecorderStore.getState().setPhase('completed')
      useMeetingRecorderStore.getState().complete('note-99')
    })
    await waitFor(() => expect(desktopRecorderWindowMock.setRecorderWindowSize).toHaveBeenLastCalledWith(360, 132))

    act(() => useMeetingRecorderStore.getState().dismissNotification())
    await waitFor(() => expect(desktopRecorderWindowMock.setRecorderWindowSize).toHaveBeenLastCalledWith(360, 132))

    // Discard confirmation replaces the compact panel without resizing it.
    act(() => {
      useMeetingRecorderStore.setState({ noteId: undefined, phase: 'recording', recordedAudio: new Blob(['a'], { type: 'audio/webm' }) })
    })
    await userEvent.click(screen.getByRole('button', { name: '关闭' }))
    expect(screen.getByRole('dialog', { name: '放弃这段会议录音？' })).toBeInTheDocument()
    await waitFor(() => expect(desktopRecorderWindowMock.setRecorderWindowSize).toHaveBeenLastCalledWith(360, 132))
  })
})
