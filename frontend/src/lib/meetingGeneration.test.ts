import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiJson } from './api'
import {
  MEETING_NOTE_SOURCE_TYPE,
  buildMeetingRecordingFile,
  completeMeetingRecordingGeneration,
  createMeetingRecordingTitle,
  submitMeetingRecording,
  waitForMeetingTaskCompletion,
  resumeMeetingTask,
} from './meetingGeneration'

vi.mock('./api', () => ({ apiJson: vi.fn() }))

describe('meetingGeneration', () => {
  beforeEach(() => vi.mocked(apiJson).mockReset())

  it.each(['unknown_error', 'asr_empty_result', 'empty_result_unverified'])('reads non-retryable %s without POST and preserves the server failure stage/message on repeated recovery', async error_code => {
    const message = error_code === 'unknown_error' ? '转写结果尚未确认，原文件已保留。' : '转写服务返回空结果，尚未确认该区间的完整识别结果。原文件已保留，请查看原任务，不要重复提交。'
    vi.mocked(apiJson).mockResolvedValue({ status: 'failed', failed_stage: 'transcribing', retryable: false, error_code, message })
    for (let attempt = 0; attempt < 2; attempt++) {
      await expect(resumeMeetingTask('original-task')).rejects.toMatchObject({
        name: 'MeetingGenerationError', stage: 'transcribing', message,
      })
    }
    expect(vi.mocked(apiJson).mock.calls).toEqual([['/api/task/original-task'], ['/api/task/original-task']])
  })

  it.each([true, undefined])('retains the original task retry contract when retryable=%s', async retryable => {
    vi.mocked(apiJson).mockResolvedValueOnce({ status: 'failed', failed_stage: 'summarizing', retryable, message: 'Summary failed' }).mockResolvedValueOnce({ task_id: 'original-task' })
    await expect(resumeMeetingTask('original-task')).resolves.toEqual({ task_id: 'original-task' })
    expect(vi.mocked(apiJson).mock.calls).toEqual([['/api/task/original-task'], ['/api/task/original-task/retry', { method: 'POST' }]])
  })

  it('preserves the failed stage if a formerly retryable task is rejected during retry', async () => {
    vi.mocked(apiJson).mockResolvedValueOnce({ status: 'failed', failed_stage: 'aligning', retryable: true, message: 'Alignment failed' }).mockRejectedValueOnce(new Error('原任务尚不能安全重试'))
    await expect(resumeMeetingTask('original-task')).rejects.toMatchObject({ stage: 'aligning', message: '原任务尚不能安全重试' })
  })

  it.each(['transcribing', 'success'])('only queries %s tasks without submitting retry', async status => {
    vi.mocked(apiJson).mockResolvedValue({ status, message: status })
    await expect(resumeMeetingTask('original-task')).resolves.toEqual({ task_id: 'original-task' })
    expect(apiJson).toHaveBeenCalledExactlyOnceWith('/api/task/original-task')
  })

  it('keeps MP4 screen recordings named as video files', () => {
    expect(buildMeetingRecordingFile(new Blob(['video'], { type: 'video/mp4' })).name).toMatch(/\.mp4$/)
  })

  it('forwards measured progress and preserves a terminal failure stage without polling forever', async () => {
    const progress = { status: 'transcribing', processed_seconds: 30, total_seconds: 60, progress: 0.5, eta_seconds: 10 }
    const fetchStatus = vi.fn().mockResolvedValueOnce(progress).mockResolvedValueOnce({
      status: 'failed', stage: 'transcribing', failed_stage: 'aligning', message: 'alignment failed',
    })
    const onProgress = vi.fn()
    const delay = vi.fn().mockResolvedValue(undefined)
    await expect(waitForMeetingTaskCompletion({ taskId: 'task', fetchStatus, onProgress, delay })).rejects.toMatchObject({ stage: 'aligning' })
    expect(onProgress).toHaveBeenCalledWith(progress)
    expect(delay).toHaveBeenCalledTimes(1)
    expect(fetchStatus).toHaveBeenCalledTimes(2)
  })

  it('creates a stable meeting recording file from a browser audio blob', () => {
    const file = buildMeetingRecordingFile(
      new Blob(['audio'], { type: 'audio/webm;codecs=opus' }),
      new Date('2026-06-15T10:20:30.000Z'),
    )

    expect(file.name).toBe('meeting-recording-2026-06-15-10-20-30.webm')
    expect(file.type).toBe('audio/webm;codecs=opus')
  })

  it('builds a readable localized meeting title', () => {
    expect(createMeetingRecordingTitle(new Date('2026-06-15T10:20:30+08:00'), 'zh-CN')).toContain('｜待生成纪要')
    expect(createMeetingRecordingTitle(new Date('2026-06-15T10:20:30Z'), 'en')).toContain('｜Notes pending')
  })

  it('submits meeting recordings through the existing upload generation flow', async () => {
    const submitUploadedSource = vi.fn().mockResolvedValue({ task_id: 'task-1' })

    const response = await submitMeetingRecording(
      {
        audioBlob: new Blob(['audio'], { type: 'audio/webm' }),
        startedAt: new Date('2026-06-15T10:20:30.000Z'),
        outputLanguage: 'zh-CN',
        summaryMode: 'accurate',
        modelProfileId: 'model-1',
        sttProfileId: 'stt-1',
        diarize: true,
        speakerCount: 4,
      },
      { submitUploadedSource },
    )

    expect(response.task_id).toBe('task-1')
    expect(submitUploadedSource).toHaveBeenCalledWith(expect.objectContaining({
      sourceType: 'audio',
      style: 'meeting',
      outputLanguage: 'zh-CN',
      summaryMode: 'accurate',
      modelProfileId: 'model-1',
      sttProfileId: 'stt-1',
      diarize: true,
      speakerCount: 4,
    }))
    expect(submitUploadedSource.mock.calls[0][0].file.name).toBe('meeting-recording-2026-06-15-10-20-30.webm')
  })

  it('polls until success, saves the generated note as a meeting recording, and reports progress', async () => {
    const fetchTaskStatus = vi
      .fn()
      .mockResolvedValueOnce({ status: 'transcribing', message: 'Transcribing' })
      .mockResolvedValueOnce({ status: 'summarizing', message: 'Summarizing' })
      .mockResolvedValueOnce({
        status: 'success',
        message: 'Done',
        result: {
          task_id: 'task-1',
          title: 'Weekly Sync',
          markdown: '# Weekly Sync',
        },
      })
    const saveNote = vi.fn().mockResolvedValue({ id: 'note-1' })
    const onProgress = vi.fn()

    const note = await completeMeetingRecordingGeneration({
      taskId: 'task-1',
      workspace: { scope: 'personal' },
      fetchTaskStatus,
      saveNote,
      onProgress,
      delay: () => Promise.resolve(),
    })

    expect(note).toEqual({ id: 'note-1' })
    expect(saveNote).toHaveBeenCalledWith(
      'Weekly Sync',
      '# Weekly Sync',
      undefined,
      'task-1',
      { scope: 'personal' },
      MEETING_NOTE_SOURCE_TYPE,
    )
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ status: 'transcribing' }))
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ status: 'summarizing' }))
  })

  it('surfaces failed generation status with a useful message', async () => {
    await expect(completeMeetingRecordingGeneration({
      taskId: 'task-1',
      workspace: { scope: 'personal' },
      fetchTaskStatus: vi.fn().mockResolvedValue({ status: 'failed', message: 'STT failed' }),
      saveNote: vi.fn(),
      delay: () => Promise.resolve(),
    })).rejects.toThrow('STT failed')
  })
})
