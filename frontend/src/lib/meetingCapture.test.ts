import { afterEach, describe, expect, it, vi } from 'vitest'
import { captureMeetingSources, DEFAULT_CAPTURE_OPTIONS } from './meetingCapture'

class TestStream {
  constructor(private tracks: Array<{ kind: string; stop: () => void }>) {}
  getTracks() { return this.tracks }
  getAudioTracks() { return this.tracks.filter(track => track.kind === 'audio') }
  getVideoTracks() { return this.tracks.filter(track => track.kind === 'video') }
}

afterEach(() => vi.unstubAllGlobals())

describe('meeting source capture', () => {
  it('requests the selected microphone and releases all sources', async () => {
    const stop = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue(new TestStream([{ kind: 'audio', stop }]))
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
    vi.stubGlobal('MediaStream', TestStream)
    const capture = await captureMeetingSources({ ...DEFAULT_CAPTURE_OPTIONS, microphoneId: 'usb-mic' })
    expect(getUserMedia).toHaveBeenCalledWith({ audio: { deviceId: { exact: 'usb-mic' } } })
    capture.cleanup()
    expect(stop).toHaveBeenCalledOnce()
  })

  it('rejects missing system audio instead of silently recording only the microphone', async () => {
    const stop = vi.fn()
    const getUserMedia = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia, getDisplayMedia: vi.fn().mockResolvedValue(new TestStream([{ kind: 'video', stop }])) } })
    await expect(captureMeetingSources({ ...DEFAULT_CAPTURE_OPTIONS, systemAudio: true })).rejects.toThrow('未采集到会议声音')
    expect(stop).toHaveBeenCalledOnce()
    expect(getUserMedia).not.toHaveBeenCalled()
  })

  it('releases the selected screen when microphone access fails', async () => {
    const stop = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(new Error('denied')), getDisplayMedia: vi.fn().mockResolvedValue(new TestStream([{ kind: 'video', stop }])) } })
    await expect(captureMeetingSources({ ...DEFAULT_CAPTURE_OPTIONS, screen: true })).rejects.toThrow('denied')
    expect(stop).toHaveBeenCalledOnce()
  })
})
