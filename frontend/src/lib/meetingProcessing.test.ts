import { beforeEach, expect, it, vi } from 'vitest'
import type { PendingMeeting, MeetingGenerationSelection } from './audioStorage'

const mocks = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn(), audio: vi.fn(), api: vi.fn(), submit: vi.fn(), resume: vi.fn(), complete: vi.fn(), save: vi.fn(), owner: 'owner', publish: vi.fn(), models: vi.fn(), speech: vi.fn() }))
vi.mock('./audioStorage', () => ({ getPendingMeeting: mocks.read, updatePendingMeeting: mocks.write, getRecordedAudio: mocks.audio }))
vi.mock('./api', () => ({ apiJson: mocks.api }))
vi.mock('./modelProfiles', () => ({ fetchModelProfiles: mocks.models }))
vi.mock('./sttProfiles', () => ({ fetchSTTProfiles: mocks.speech }))
vi.mock('../stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: mocks.owner } }) } }))
vi.mock('../stores/noteLibraryStore', () => ({ useNoteLibraryStore: { getState: () => ({ saveNote: mocks.save }) } }))
vi.mock('./feishu', () => ({ publishToFeishu: mocks.publish }))
vi.mock('./meetingGeneration', async importOriginal => ({ ...await importOriginal<typeof import('./meetingGeneration')>(), submitMeetingRecording: mocks.submit, resumeMeetingTask: mocks.resume, completeMeetingRecordingGeneration: mocks.complete }))
import { processSavedMeeting, isMeetingProcessing } from './meetingProcessing'
import { MissingMeetingTaskError } from './meetingGeneration'

const selection: MeetingGenerationSelection = { mode: 'cloud', asr: 'asr-original', llm: 'llm-original', asrLabel: 'asr-original', llmLabel: 'llm-original' }
let record: PendingMeeting
beforeEach(() => {
  vi.resetAllMocks(); mocks.owner = 'owner'
  record = { id: 'source-recording', ownerId: 'owner', workspace: { scope: 'personal' }, options: { title: '原录制', meetingType: 'audio', screen: false }, startedAt: '2026-10-13T00:00:00Z', elapsedSeconds: 60, recordingStatus: 'saved', processingStatus: 'idle' } as PendingMeeting
  mocks.read.mockImplementation(async () => record)
  mocks.write.mockImplementation(async (_id, patch) => { record = { ...record, ...patch }; return record })
  mocks.audio.mockResolvedValue(new Blob(['audio']))
  mocks.api.mockImplementation(async (path: string) => path.endsWith('/models') ? [{ id: selection.asr, modelType: 'asr', runtimeStatus: 'available' }, { id: selection.llm, modelType: 'llm', runtimeStatus: 'available' }] : { configured: true, mode: 'cloud', asr_model: selection.asr, llm_model: selection.llm })
  mocks.submit.mockResolvedValue({ task_id: 'new-task' }); mocks.resume.mockResolvedValue({ task_id: 'original-task' })
  mocks.save.mockResolvedValue({ id: 'note' }); mocks.complete.mockResolvedValue({ id: 'note' }); mocks.publish.mockResolvedValue(undefined)
})

it('requires explicit model confirmation before first submission', async () => {
  await processSavedMeeting(record, 'zh')
  expect(mocks.submit).not.toHaveBeenCalled()
  expect(record.generationConfirmationRequired).toBe(true)
  expect(record.processingStatus).toBe('idle')
})

it('persists the operation before submission and preserves the source identity', async () => {
  mocks.submit.mockImplementation(async input => {
    expect(record.generationOperation?.selection).toEqual(selection)
    expect(input.meetingSessionId).toBe(record.id)
    return { task_id: 'new-task' }
  })
  await processSavedMeeting(record, 'zh', undefined, { selection })
  expect(mocks.submit).toHaveBeenCalledOnce()
  expect(record.id).toBe('source-recording')
  expect(record.generationOperation?.outputLanguage).toBe('zh')
  expect(record.processingStatus).toBe('completed')
})

it('does not upload when persisting the model confirmation fails', async () => {
  mocks.write.mockRejectedValue(new Error('保存失败'))
  await expect(processSavedMeeting(record, 'zh', undefined, { selection })).rejects.toThrow('保存失败')
  expect(mocks.submit).not.toHaveBeenCalled()
  expect(record.generationOperation).toBeUndefined()
})

it('deduplicates simultaneous workers, including conflicting confirmation', async () => {
  let release!: () => void
  mocks.audio.mockImplementation(() => new Promise<Blob>(resolve => { release = () => resolve(new Blob(['audio'])) }))
  const first = processSavedMeeting(record, 'zh', undefined, { selection })
  const second = processSavedMeeting(record, 'en', undefined, { selection: { ...selection, asr: 'other' } })
  expect(first).toBe(second)
  expect(isMeetingProcessing(record.id)).toBe(true)
  await vi.waitFor(() => expect(release).toBeTypeOf('function'))
  release(); await first
  expect(mocks.submit).toHaveBeenCalledOnce()
  expect(isMeetingProcessing(record.id)).toBe(false)
})

it('restores an existing task without reading newer global model configuration', async () => {
  record = { ...record, taskId: 'original-task', processingStatus: 'failed', generationOperation: { id: 'operation', selection, outputLanguage: 'zh' } }
  await processSavedMeeting(record, 'en')
  expect(mocks.resume).toHaveBeenCalledWith('original-task')
  expect(mocks.submit).not.toHaveBeenCalled(); expect(mocks.api).not.toHaveBeenCalled()
  expect(record.generationOperation?.selection).toEqual(selection)
})

it('retains an expired task and requires a separate confirmed operation', async () => {
  record = { ...record, taskId: 'expired-task', processingStatus: 'failed', generationOperation: { id: 'operation', selection, outputLanguage: 'zh' } }
  mocks.resume.mockRejectedValue(new MissingMeetingTaskError())
  await processSavedMeeting(record, 'zh')
  expect(mocks.submit).not.toHaveBeenCalled(); expect(record.taskId).toBe('expired-task')
  expect(record.generationConfirmationRequired).toBe(true)
  expect(record.processingError).toContain('另建生成操作')
  await processSavedMeeting(record, 'zh', undefined, { selection, previousOperationId: 'operation', previousTaskId: 'expired-task' })
  expect(mocks.submit).toHaveBeenCalledOnce()
  expect(record.generationOperation?.previousTaskId).toBe('expired-task')
  expect(record.generationOperation?.id).not.toBe('operation')
})

it('blocks new uploads if the service configuration drifted from the saved selection', async () => {
  record.generationOperation = { id: 'operation', selection, outputLanguage: 'zh' }
  mocks.api.mockResolvedValue({ mode: 'cloud', asr_model: 'latest', llm_model: 'latest' })
  await processSavedMeeting(record, 'zh')
  expect(mocks.submit).not.toHaveBeenCalled(); expect(record.generationOperation.selection).toEqual(selection)
  expect(record.generationConfirmationRequired).toBe(true)
})

it('rejects stale confirmation rather than replacing a newer operation', async () => {
  record.generationOperation = { id: 'newer', selection, outputLanguage: 'zh' }
  await expect(processSavedMeeting(record, 'zh', undefined, { selection, previousOperationId: 'older' })).rejects.toThrow('处理记录已更新')
  expect(record.generationOperation.id).toBe('newer'); expect(mocks.submit).not.toHaveBeenCalled()
})

it('passes saved local profiles rather than current global selections', async () => {
  const local = { mode: 'local', asr: 'saved-asr', llm: 'saved-llm', asrLabel: '语音 · speech', llmLabel: '总结 · summary' } as const
  record.generationOperation = { id: 'operation', selection: local, outputLanguage: 'en' }
  mocks.api.mockResolvedValue({ mode: 'local' })
  mocks.speech.mockResolvedValue([{ id: local.asr, isActive: true, name: '语音', modelName: 'speech' }])
  mocks.models.mockResolvedValue([{ id: local.llm, isActive: true, name: '总结', modelName: 'summary' }])
  await processSavedMeeting(record, 'zh')
  expect(mocks.submit).toHaveBeenCalledWith(expect.objectContaining({ sttProfileId: 'saved-asr', modelProfileId: 'saved-llm', outputLanguage: 'en' }), expect.anything())
})

it('blocks unavailable cloud models without silently choosing an alternative', async () => {
  record.generationOperation = { id: 'operation', selection, outputLanguage: 'zh' }
  mocks.api.mockImplementation(async (path: string) => path.endsWith('/models') ? [] : { mode: 'cloud', asr_model: selection.asr, llm_model: selection.llm })
  await processSavedMeeting(record, 'zh')
  expect(mocks.submit).not.toHaveBeenCalled()
  expect(record.generationConfirmationRequired).toBe(true)
  expect(record.processingError).toContain('不可用')
})

it('query failure preserves the original task and never becomes a new upload', async () => {
  record = { ...record, taskId: 'original-task', processingStatus: 'failed' }
  mocks.resume.mockRejectedValue(new Error('查询暂不可用'))
  await processSavedMeeting(record, 'zh')
  expect(record.taskId).toBe('original-task')
  expect(record.processingError).toBe('查询暂不可用')
  expect(mocks.submit).not.toHaveBeenCalled()
})

it.each(['service_error', 'rate_limited'])('allows an explicit expired %s retry using the frozen model', async status => {
  mocks.api.mockImplementation(async (path: string) => path.endsWith('/models') ? [
    { id: selection.asr, modelType: 'asr', runtimeStatus: 'not_available', availability: { status, retryAt: Date.now() - 1 } },
    { id: selection.llm, modelType: 'llm', runtimeStatus: 'available' },
  ] : { configured: true, mode: 'cloud', asr_model: selection.asr, llm_model: selection.llm })
  await processSavedMeeting(record, 'zh', undefined, { selection })
  expect(mocks.submit).toHaveBeenCalledOnce()
  expect(record.generationOperation?.selection).toEqual(selection)
})
it.each(['auth_failed', 'quota_exhausted', 'permission_denied'])('blocks %s even with an expired retryAt', async status => {
  mocks.api.mockImplementation(async (path: string) => path.endsWith('/models') ? [
    { id: selection.asr, modelType: 'asr', runtimeStatus: 'not_available', availability: { status, retryAt: 1 } },
    { id: selection.llm, modelType: 'llm', runtimeStatus: 'available' },
  ] : { configured: true, mode: 'cloud', asr_model: selection.asr, llm_model: selection.llm })
  await processSavedMeeting(record, 'zh', undefined, { selection })
  expect(mocks.submit).not.toHaveBeenCalled()
})
