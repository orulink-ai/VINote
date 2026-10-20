import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SavedRecordingChoice } from './SavedRecordingChoice'
import { getPendingMeeting } from '../../lib/audioStorage'
import { processSavedMeeting } from '../../lib/meetingProcessing'
import { DEFAULT_CAPTURE_OPTIONS } from '../../lib/meetingCapture'
import { useAppModeStore } from '../../stores/appModeStore'
import { useModelProfileStore } from '../../stores/modelProfileStore'
import { useSTTProfileStore } from '../../stores/sttProfileStore'

vi.mock('../../lib/audioStorage', () => ({ getPendingMeeting: vi.fn(), getRecordedAudio: vi.fn(), deleteLocalRecording: vi.fn() }))
vi.mock('../../lib/meetingProcessing', () => ({ processSavedMeeting: vi.fn().mockResolvedValue(undefined), isMeetingProcessing: vi.fn(() => false) }))
vi.mock('../../stores/authStore', () => ({ useAuthStore: Object.assign((selector: (state: unknown) => unknown) => selector({ user: { id: 'owner' } }), { getState: () => ({ user: { id: 'owner' } }) }) }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))
vi.mock('./RecordingTitleEditor', () => ({ RecordingTitleEditor: () => null }))
vi.mock('../Settings/ModelSourcePanel', () => ({ ModelSourcePanel: () => <div>真实详情中的现有模型选择入口</div> }))

const recording = { id: 'recording-1', ownerId: 'owner', workspace: { scope: 'personal' as const }, options: DEFAULT_CAPTURE_OPTIONS, startedAt: '2026-09-29T10:00:00Z', elapsedSeconds: 15, recordingStatus: 'saved' as const, processingStatus: 'idle' as const }
const renderChoice = () => render(<MemoryRouter initialEntries={['/meetings?recordingSaved=recording-1']}><SavedRecordingChoice /></MemoryRouter>)
function LocationProbe() { const location = useLocation(); return <output aria-label="当前路径">{location.pathname + location.search}</output> }

describe('SavedRecordingChoice', () => {
  beforeEach(() => {
    vi.clearAllMocks(); vi.mocked(getPendingMeeting).mockResolvedValue(recording)
    useAppModeStore.setState({ config: { configured: true, mode: 'cloud', asr_model: 'asr-confirmed', llm_model: 'llm-confirmed' }, saving: false, error: '', load: vi.fn().mockResolvedValue(undefined) })
    useModelProfileStore.setState({ error: '', loading: false }); useSTTProfileStore.setState({ error: '', loading: false })
  })
  it('waits for durable saved metadata before offering generation', async () => {
    let finish!: (row: typeof recording) => void
    vi.mocked(getPendingMeeting).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    renderChoice()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(processSavedMeeting).not.toHaveBeenCalled()
    await act(async () => finish(recording))
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    expect(processSavedMeeting).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '生成会议纪要' }))
    expect(processSavedMeeting).not.toHaveBeenCalled()
    const confirmation = await screen.findByRole('dialog', { name: '确认本次生成' })
    expect(within(confirmation).getByRole('button', { name: '确认模型并开始生成' })).toBeEnabled()
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: '确认模型并开始生成' }))
    expect(processSavedMeeting).toHaveBeenCalledExactlyOnceWith(recording, 'zh-CN', undefined, expect.objectContaining({ selection: expect.objectContaining({ asr: 'asr-confirmed', llm: 'llm-confirmed' }) }))
  })
  it('opens the actual confirmation component directly from the source-details route', async () => {
    render(<MemoryRouter initialEntries={['/meetings?recordingConfirm=recording-1']}><SavedRecordingChoice /></MemoryRouter>)
    expect(await screen.findByText('真实详情中的现有模型选择入口')).toBeInTheDocument()
    expect(processSavedMeeting).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '确认模型并开始生成' }))
    expect(processSavedMeeting).toHaveBeenCalledOnce()
  })
  it('shows a retryable read failure without exposing a false empty or starting generation', async () => {
    vi.mocked(getPendingMeeting).mockRejectedValueOnce(new Error('读取失败')).mockResolvedValue(recording)
    render(<MemoryRouter initialEntries={['/meetings?recordingConfirm=recording-1']}><SavedRecordingChoice /></MemoryRouter>)
    expect(await screen.findByRole('alert')).toHaveTextContent('读取失败')
    await userEvent.click(screen.getByRole('button', { name: '重新读取原录制' }))
    expect(await screen.findByRole('button', { name: '确认模型并开始生成' })).toBeInTheDocument()
    expect(processSavedMeeting).not.toHaveBeenCalled()
  })
  it('rejects a direct link for another account before mounting model confirmation', async () => {
    vi.mocked(getPendingMeeting).mockResolvedValue({ ...recording, ownerId: 'other' })
    render(<MemoryRouter initialEntries={['/meetings?recordingConfirm=recording-1']}><SavedRecordingChoice /></MemoryRouter>)
    expect(await screen.findByRole('alert')).toHaveTextContent('不属于当前账号')
    expect(screen.queryByRole('button', { name: '确认模型并开始生成' })).not.toBeInTheDocument()
    expect(processSavedMeeting).not.toHaveBeenCalled()
  })
  it('refreshes the source after confirmed generation and exposes the saved minutes', async () => {
    vi.mocked(processSavedMeeting).mockImplementationOnce(async () => { vi.mocked(getPendingMeeting).mockResolvedValue({ ...recording, processingStatus: 'completed', noteId: 'saved-note' }) })
    render(<MemoryRouter initialEntries={['/meetings?recordingConfirm=recording-1']}><SavedRecordingChoice /><LocationProbe /></MemoryRouter>)
    await userEvent.click(await screen.findByRole('button', { name: '确认模型并开始生成' }))
    await userEvent.click(await screen.findByRole('button', { name: '查看会议纪要' }))
    expect(screen.getByLabelText('当前路径')).toHaveTextContent('/note/saved-note')
  })
  it('returns to the validated original content path', async () => {
    render(<MemoryRouter initialEntries={['/meetings?recordingConfirm=recording-1&returnTo=%2Fnote%2Fnote-1%3Ftab%3Dsummary']}><SavedRecordingChoice /><LocationProbe /></MemoryRouter>)
    const confirmation = await screen.findByRole('dialog', { name: '确认本次生成' })
    expect(processSavedMeeting).not.toHaveBeenCalled()
    await userEvent.click(within(confirmation).getByRole('button', { name: '暂不生成' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '确认本次生成' })).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: '返回来源页面' }))
    expect(processSavedMeeting).not.toHaveBeenCalled()
    expect(screen.getByLabelText('当前路径')).toHaveTextContent('/note/note-1?tab=summary')
  })
  it('dismisses without uploading or processing when notes are declined', async () => {
    renderChoice()
    await userEvent.click(await screen.findByRole('button', { name: '暂不生成' }))
    expect(processSavedMeeting).not.toHaveBeenCalled()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
  it.each([{ ...recording, ownerId: 'other' }, { ...recording, processingStatus: 'completed' as const }])('does not offer another account or already processed recording', async row => {
    vi.mocked(getPendingMeeting).mockResolvedValue(row)
    await act(async () => { renderChoice() })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(processSavedMeeting).not.toHaveBeenCalled()
  })
})
