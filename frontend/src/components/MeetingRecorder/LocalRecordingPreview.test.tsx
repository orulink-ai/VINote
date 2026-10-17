import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const storage = vi.hoisted(() => ({ remove: vi.fn(), read: vi.fn(), pending: vi.fn(), process: vi.fn(), busy: vi.fn() }))
vi.mock('@/lib/audioStorage', () => ({ deleteLocalRecording: storage.remove, getRecordedAudio: storage.read, getPendingMeeting: storage.pending }))
vi.mock('../../lib/meetingProcessing', () => ({ processSavedMeeting: storage.process, isMeetingProcessing: storage.busy }))
vi.mock('../Settings/ModelSourcePanel', () => ({ ModelSourcePanel: () => <div>现有转写与总结选择组件</div> }))
vi.mock('../../lib/i18n', () => ({ useI18n: () => ({ locale: 'zh' }) }))
vi.mock('./RecordingTitleEditor', () => ({ RecordingTitleEditor: () => null }))
vi.mock('../../lib/recordingDownload', () => ({ downloadRecording: vi.fn() }))
import { LocalRecordingPreview } from './LocalRecordingPreview'
import type { PendingMeeting } from '../../lib/audioStorage'
import { useAppModeStore } from '../../stores/appModeStore'
import { useModelProfileStore } from '../../stores/modelProfileStore'
import { useSTTProfileStore } from '../../stores/sttProfileStore'

const recording = { id: 'recording-1', ownerId: 'owner', options: { title: '设计评审', meetingType: 'audio' }, processingStatus: 'idle' } as PendingMeeting
beforeEach(() => {
  storage.remove.mockReset(); storage.read.mockReset()
  storage.pending.mockReset(); storage.process.mockReset(); storage.busy.mockReturnValue(false)
  useAppModeStore.setState({ config: { mode: 'cloud', configured: true, asr_model: 'asr-confirmed', llm_model: 'llm-confirmed' }, saving: false, error: '', load: vi.fn().mockResolvedValue(undefined) })
  useModelProfileStore.setState({ loading: false, error: '' }); useSTTProfileStore.setState({ loading: false, error: '' })
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:recording'), revokeObjectURL: vi.fn() })
})

it('opens model confirmation without starting a worker, and cancellation retains the recording', async () => {
  render(<LocalRecordingPreview recording={recording} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '生成会议纪要' }))
  expect(screen.getByText('现有转写与总结选择组件')).toBeInTheDocument()
  expect(storage.process).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '暂不生成' }))
  expect(screen.queryByRole('region', { name: '确认生成模型' })).not.toBeInTheDocument()
  expect(storage.remove).not.toHaveBeenCalled()
})

it('submits only the explicitly confirmed model selection', async () => {
  storage.pending.mockResolvedValue({ ...recording, processingStatus: 'completed' })
  render(<LocalRecordingPreview recording={recording} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '生成会议纪要' }))
  await userEvent.click(screen.getByRole('button', { name: '确认模型并生成' }))
  expect(storage.process).toHaveBeenCalledWith(recording, 'zh', undefined, expect.objectContaining({ selection: expect.objectContaining({ asr: 'asr-confirmed', llm: 'llm-confirmed' }) }))
})

it('keeps failed confirmation available for retry and shows the storage error', async () => {
  storage.process.mockRejectedValueOnce(new Error('选择保存失败'))
  render(<LocalRecordingPreview recording={recording} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '生成会议纪要' }))
  await userEvent.click(screen.getByRole('button', { name: '确认模型并生成' }))
  expect(await screen.findByText('选择保存失败')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '确认模型并生成' })).toBeEnabled()
})

it('restores a known task without exposing new global choices', async () => {
  const retry = { ...recording, processingStatus: 'failed', taskId: 'original-task' } as PendingMeeting
  render(<LocalRecordingPreview recording={retry} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '重试会后处理' }))
  expect(storage.process).toHaveBeenCalledWith(retry, 'zh', undefined, undefined)
  expect(screen.queryByText('现有转写与总结选择组件')).not.toBeInTheDocument()
})

it('requires explicit new-operation confirmation for an expired task', async () => {
  const expired = { ...recording, processingStatus: 'failed', taskId: 'expired-task', generationConfirmationRequired: true, generationOperation: { id: 'original-operation', selection: { mode: 'cloud', asr: 'old-asr', llm: 'old-llm', asrLabel: 'old-asr', llmLabel: 'old-llm' }, outputLanguage: 'zh' } } as PendingMeeting
  render(<LocalRecordingPreview recording={expired} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '重试会后处理' }))
  expect(screen.getByText('确认另建生成操作')).toBeInTheDocument()
  expect(storage.process).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '确认模型并生成' }))
  expect(storage.process).toHaveBeenCalledWith(expired, 'zh', undefined, expect.objectContaining({ previousTaskId: 'expired-task', previousOperationId: 'original-operation' }))
})

it('blocks confirmation when concrete model choices are missing', async () => {
  useAppModeStore.setState({ config: { mode: 'cloud', configured: true, asr_model: '', llm_model: '' } })
  render(<LocalRecordingPreview recording={recording} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '生成会议纪要' }))
  expect(screen.getByRole('button', { name: '确认模型并生成' })).toBeDisabled()
  expect(storage.process).not.toHaveBeenCalled()
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('retains failed deletion confirmation and permits retry without losing the recording', async () => {
  const deleted = vi.fn()
  storage.remove.mockRejectedValueOnce(new Error('存储暂不可用')).mockResolvedValueOnce(undefined)
  render(<LocalRecordingPreview recording={recording} onDeleted={deleted} />)
  await userEvent.click(screen.getByRole('button', { name: '删除录制文件' }))
  await userEvent.click(screen.getByRole('button', { name: '确认删除文件' }))
  await within(screen.getByRole('alertdialog')).findByText('存储暂不可用')
  expect(deleted).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '确认删除文件' }))
  expect(deleted).toHaveBeenCalledOnce()
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
})

it('recovers a player failure by reloading the original on demand', async () => {
  storage.read.mockResolvedValue(new Blob(['audio']))
  render(<LocalRecordingPreview recording={recording} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: '预览' }))
  fireEvent.error(await screen.findByLabelText('录音回放'))
  expect(screen.getByText(/文件暂时无法播放/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: '重新加载并回放' }))
  expect(await screen.findByLabelText('录音回放')).toBeInTheDocument()
  expect(storage.read).toHaveBeenCalledTimes(2)
})
