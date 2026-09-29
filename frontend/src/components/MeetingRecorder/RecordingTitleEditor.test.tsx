import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RecordingTitleEditor } from './RecordingTitleEditor'
import { getPendingMeeting, updatePendingMeeting } from '../../lib/audioStorage'
import { DEFAULT_CAPTURE_OPTIONS } from '../../lib/meetingCapture'

vi.mock('../../lib/audioStorage', () => ({ getPendingMeeting: vi.fn(), updatePendingMeeting: vi.fn() }))
vi.mock('../../stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: 'owner' } }) } }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))
const recording = { id: 'rec-1', ownerId: 'owner', workspace: { scope: 'personal' as const }, options: DEFAULT_CAPTURE_OPTIONS, startedAt: '2026-09-24T02:03:00Z', elapsedSeconds: 10, recordingStatus: 'saved' as const, processingStatus: 'idle' as const }

describe('RecordingTitleEditor', () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(getPendingMeeting).mockResolvedValue(recording); vi.mocked(updatePendingMeeting).mockResolvedValue(recording) })
  it('persists a manual title marker before closing', async () => {
    const onSaved = vi.fn()
    render(<RecordingTitleEditor recording={recording} title="原标题" onSaved={onSaved} />)
    await userEvent.click(screen.getByRole('button', { name: '修改录制标题' }))
    await userEvent.clear(screen.getByRole('textbox', { name: '录制标题' }))
    await userEvent.type(screen.getByRole('textbox', { name: '录制标题' }), '新标题')
    await userEvent.click(screen.getByRole('button', { name: '保存标题' }))
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith('新标题'))
    expect(updatePendingMeeting).toHaveBeenCalledWith('rec-1', { titleEdited: true, options: { ...DEFAULT_CAPTURE_OPTIONS, title: '新标题' } })
  })
  it('keeps the editor open and reports storage failures', async () => {
    vi.mocked(updatePendingMeeting).mockRejectedValue(new Error('storage failed'))
    const onSaved = vi.fn()
    render(<RecordingTitleEditor recording={recording} title="原标题" onSaved={onSaved} />)
    await userEvent.click(screen.getByRole('button', { name: '修改录制标题' }))
    await userEvent.click(screen.getByRole('button', { name: '保存标题' }))
    expect(await screen.findByText('storage failed')).toBeInTheDocument()
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(onSaved).not.toHaveBeenCalled()
  })
})
