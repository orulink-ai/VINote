import { describe, expect, it, vi } from 'vitest'
import {
  MEETING_NOTE_SOURCE_TYPE,
  buildMeetingRecordingFile,
  completeMeetingRecordingGeneration,
  createMeetingRecordingTitle,
  submitMeetingRecording,
} from './meetingGeneration'

describe('meetingGeneration', () => {
  it('creates a stable meeting recording file from a browser audio blob', () => {
    const file = buildMeetingRecordingFile(
      new Blob(['audio'], { type: 'audio/webm;codecs=opus' }),
      new Date('2026-06-15T10:20:30.000Z'),
    )

    expect(file.name).toBe('meeting-recording-2026-06-15-10-20-30.webm')
    expect(file.type).toBe('audio/webm;codecs=opus')
  })

  it('builds a readable localized meeting title', () => {
    expect(createMeetingRecordingTitle(new Date('2026-06-15T10:20:30+08:00'), 'zh-CN')).toContain('会议录音')
    expect(createMeetingRecordingTitle(new Date('2026-06-15T10:20:30Z'), 'en')).toContain('Meeting recording')
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
