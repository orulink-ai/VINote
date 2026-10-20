import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { TooltipProvider } from '../ui/tooltip'
import { RecordingRetryBar } from './RecordingRetryBar'
import type { NoteRecord } from '../../stores/noteLibraryStore'
import type { PendingMeeting } from '../../lib/audioStorage'

const mocks = vi.hoisted(() => ({ list: vi.fn(), read: vi.fn(), process: vi.fn(), load: vi.fn(), update: vi.fn(), resume: vi.fn() }))
vi.mock('../../lib/audioStorage', () => ({ listPendingMeetings: mocks.list, getPendingMeeting: mocks.read }))
vi.mock('../../lib/meetingProcessing', () => ({ processSavedMeeting: mocks.process }))
vi.mock('../../lib/meetingGeneration', async original => ({ ...await original<typeof import('../../lib/meetingGeneration')>(), resumeMeetingTask: mocks.resume }))
vi.mock('../../stores/authStore', () => ({ useAuthStore: Object.assign((selector: (state: unknown) => unknown) => selector({ user: { id: 'owner' } }), { getState: () => ({ user: { id: 'owner' } }) }) }))
vi.mock('../../stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => ({ updateNote: mocks.update, loadNoteById: mocks.load }) }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ language: 'zh-CN', copy: { meetingRecorder: { retry: '重试', unknownError: '处理未完成', noRecoverableAudio: '找不到可恢复原任务', phases: { transcribing: '正在转写' } } } }) }))

const note = { id: 'note-1', taskId: 'task-1', status: 'failed', sourceType: 'meeting_recording' } as NoteRecord
let source: PendingMeeting
const show = (row = note) => render(<MemoryRouter initialEntries={['/note/note-1']}><TooltipProvider><RecordingRetryBar note={row} onUpdated={mocks.update} /></TooltipProvider></MemoryRouter>)
beforeEach(() => {
  vi.resetAllMocks()
  source = { id: 'source-1', ownerId: 'owner', draftNoteId: note.id, recordingStatus: 'saved', processingStatus: 'failed', generationConfirmationRequired: true } as PendingMeeting
  mocks.list.mockImplementation(async () => [source]); mocks.read.mockImplementation(async () => source)
})

it('links missing confirmation to the validated original instead of reporting retry success', async () => {
  show()
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  const link = await screen.findByRole('link', { name: '原录制详情 · 确认模型' })
  expect(link.getAttribute('href')).toContain('recordingConfirm=source-1')
  expect(link.getAttribute('href')).toContain('returnTo=%2Fnote%2Fnote-1')
  expect(mocks.process).not.toHaveBeenCalled(); expect(mocks.update).not.toHaveBeenCalled()
})

it('offers a query-only exact-task entrance preserving return context without starting recovery', () => {
  show()
  const link = screen.getByRole('link', { name: '查看原任务状态' })
  const target = new URL(link.getAttribute('href')!, 'https://example.invalid')
  expect(target.pathname).toBe('/generate')
  expect(target.searchParams.get('task')).toBe('task-1')
  expect(target.searchParams.get('returnTo')).toBe('/note/note-1')
  expect(mocks.resume).not.toHaveBeenCalled()
  expect(mocks.process).not.toHaveBeenCalled()
  expect(mocks.update).not.toHaveBeenCalled()
})

it('links to the original after restoring a task reveals expired-operation confirmation', async () => {
  source = { ...source, taskId: 'task-1', generationConfirmationRequired: false }
  mocks.process.mockImplementation(async () => { source = { ...source, generationConfirmationRequired: true, processingError: '原任务已失效' } })
  show()
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByRole('link', { name: '原录制详情 · 确认模型' })).toBeInTheDocument()
  expect(mocks.update).not.toHaveBeenCalled(); expect(mocks.load).not.toHaveBeenCalled()
})

it('never associates unrelated recordings merely because both task IDs are absent', async () => {
  source = { ...source, draftNoteId: 'other-note', taskId: undefined }
  show({ ...note, taskId: undefined })
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByLabelText('找不到可恢复原任务')).toBeInTheDocument()
  expect(mocks.read).not.toHaveBeenCalled(); expect(mocks.process).not.toHaveBeenCalled()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})

it('rejects changed recording ownership after the list was read', async () => {
  mocks.read.mockResolvedValue({ ...source, ownerId: 'other' })
  show()
  await userEvent.click(screen.getByRole('button', { name: '重试' }))
  expect(await screen.findByLabelText('原录制状态未核验，请重新读取。')).toBeInTheDocument()
  expect(mocks.process).not.toHaveBeenCalled(); expect(screen.queryByRole('link', { name: '原录制详情 · 确认模型' })).not.toBeInTheDocument()
})
