import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useAudioRecorder } from './useAudioRecorder'

const disk = vi.hoisted(() => ({ name: 'meeting-11111111-1111-1111-1111-111111111111.webm', remove: vi.fn(), append: vi.fn(), finish: vi.fn() }))
vi.mock('../lib/recordingFile', () => ({ createRecordingFile: async () => disk }))
vi.mock('../lib/meetingCapture', () => ({ captureMeetingSources: async () => ({ stream: { getAudioTracks: () => [{}], getTracks: () => [] }, cleanup: vi.fn() }) }))

class Recorder {
  static isTypeSupported() { return true }
  state = 'inactive'
  mimeType = 'video/webm'
  onstop?: () => void
  start() { this.state = 'recording' }
  requestData() {}
  stop() { this.state = 'inactive'; queueMicrotask(() => this.onstop?.()) }
}

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks() })

it.each([true, false])('keeps the OPFS file only after history accepts ownership: %s', async retained => {
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn() } })
  disk.finish.mockResolvedValue(new Blob(['video'], { type: 'video/webm' }))
  const { result, unmount } = renderHook(() => useAudioRecorder())
  await act(async () => { await result.current.start({ title: '', microphoneId: '', screen: true, systemAudio: false, diarize: true }) })
  await act(async () => { await result.current.stop() })
  expect(result.current.getRecordingFileName()).toBe(disk.name)
  if (retained) result.current.retainRecordingFile()
  act(() => result.current.reset())
  unmount()
  expect(disk.remove).toHaveBeenCalledTimes(retained ? 0 : 1)
})
