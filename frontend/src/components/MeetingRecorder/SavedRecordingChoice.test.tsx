import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SavedRecordingChoice } from './SavedRecordingChoice'
import { getPendingMeeting } from '../../lib/audioStorage'
import { processSavedMeeting } from '../../lib/meetingProcessing'
import { DEFAULT_CAPTURE_OPTIONS } from '../../lib/meetingCapture'

vi.mock('../../lib/audioStorage', () => ({ getPendingMeeting: vi.fn() }))
vi.mock('../../lib/meetingProcessing', () => ({ processSavedMeeting: vi.fn().mockResolvedValue(undefined) }))
vi.mock('../../stores/authStore', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ user: { id: 'owner' } }) }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))

const recording = { id: 'recording-1', ownerId: 'owner', workspace: { scope: 'personal' as const }, options: DEFAULT_CAPTURE_OPTIONS, startedAt: '2026-09-29T10:00:00Z', elapsedSeconds: 15, recordingStatus: 'saved' as const, processingStatus: 'idle' as const }
const renderChoice = () => render(<MemoryRouter initialEntries={['/meetings?recordingSaved=recording-1']}><SavedRecordingChoice /></MemoryRouter>)

describe('SavedRecordingChoice', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(getPendingMeeting).mockResolvedValue(recording) })
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
    expect(processSavedMeeting).toHaveBeenCalledExactlyOnceWith(recording, 'zh-CN')
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
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
