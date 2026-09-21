import { afterEach, describe, expect, it, vi } from 'vitest'
import { acquireMeetingMicrophone, captureMeetingSources, DISPLAY_CAPTURE_FAILED, DEFAULT_CAPTURE_OPTIONS as AUTOMATIC_CAPTURE_OPTIONS } from './meetingCapture'

const DEFAULT_CAPTURE_OPTIONS = { ...AUTOMATIC_CAPTURE_OPTIONS, systemAudio: false }

class TestStream {
  constructor(private tracks: Array<{ kind: string; stop: () => void }>) {}
  getTracks() { return this.tracks }
  getAudioTracks() { return this.tracks.filter(track => track.kind === 'audio') }
  getVideoTracks() { return this.tracks.filter(track => track.kind === 'video') }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('meeting source capture', () => {
  it('waits for screen selection beyond 20 seconds and remains cancellable', async () => {
    vi.useFakeTimers()
    const stop = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: {
      getUserMedia: vi.fn().mockResolvedValue(new TestStream([{ kind: 'audio', stop }])),
      getDisplayMedia: vi.fn(() => new Promise(() => {})),
    } })
    const controller = new AbortController()
    const pending = captureMeetingSources({ ...AUTOMATIC_CAPTURE_OPTIONS, screen: true }, controller.signal)
    const settled = vi.fn()
    void pending.then(settled, settled)
    const failure = expect(pending).rejects.toThrow('display_request_cancelled')
    await vi.advanceTimersByTimeAsync(60000)
    expect(settled).not.toHaveBeenCalled()
    controller.abort()
    await failure
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
    expect(stop).not.toHaveBeenCalled()
  })

  it('allows a temporarily muted microphone without requesting screen sharing', async () => {
    const track = { kind: 'audio', muted: true, stop: vi.fn() }
    const getDisplayMedia = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: {
      getUserMedia: vi.fn().mockResolvedValue(new TestStream([track])), getDisplayMedia,
    } })
    vi.stubGlobal('MediaStream', TestStream)
    const capture = await captureMeetingSources(DEFAULT_CAPTURE_OPTIONS)
    expect(capture.stream.getAudioTracks()).toEqual([track])
    expect(getDisplayMedia).not.toHaveBeenCalled()
    capture.cleanup()
  })

  it('releases the screen on cancellation and stops a late microphone result', async () => {
    const stopScreen = vi.fn()
    const stopMic = vi.fn()
    let resolveMic!: (stream: TestStream) => void
    const getUserMedia = vi.fn(() => new Promise<TestStream>(resolve => { resolveMic = resolve }))
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia,
      getDisplayMedia: vi.fn().mockResolvedValue(new TestStream([{ kind: 'video', stop: stopScreen }])) } })
    const controller = new AbortController()
    const pending = captureMeetingSources({ ...DEFAULT_CAPTURE_OPTIONS, screen: true }, controller.signal)
    const failure = expect(pending).rejects.toThrow('microphone_request_cancelled')
    await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledOnce())
    controller.abort()
    await failure
    expect(stopScreen).toHaveBeenCalledOnce()
    resolveMic(new TestStream([{ kind: 'audio', stop: stopMic }]))
    await vi.waitFor(() => expect(stopMic).toHaveBeenCalledOnce())
  })

  it('times out a meeting microphone prompt and releases the already selected screen', async () => {
    vi.useFakeTimers()
    const stop = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(() => new Promise(() => {})),
      getDisplayMedia: vi.fn().mockResolvedValue(new TestStream([{ kind: 'video', stop }])) } })
    const pending = captureMeetingSources({ ...DEFAULT_CAPTURE_OPTIONS, screen: true })
    const failure = expect(pending).rejects.toThrow('microphone_request_timeout')
    await vi.advanceTimersByTimeAsync(20000)
    await failure
    expect(stop).toHaveBeenCalledOnce()
  })
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

  it('falls back to the system default when the selected endpoint is stale', async () => {
    const stream = new TestStream([{ kind: 'audio', stop: vi.fn() }])
    const getUserMedia = vi.fn()
      .mockRejectedValueOnce(new DOMException('', 'OverconstrainedError'))
      .mockResolvedValueOnce(stream)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })

    await expect(acquireMeetingMicrophone('old-headset-id')).resolves.toBe(stream)
    expect(getUserMedia).toHaveBeenNthCalledWith(1, { audio: { deviceId: { exact: 'old-headset-id' } } })
    expect(getUserMedia).toHaveBeenNthCalledWith(2, { audio: true })
  })

  it('retries a temporary Windows audio endpoint failure once', async () => {
    vi.useFakeTimers()
    const stream = new TestStream([{ kind: 'audio', stop: vi.fn() }])
    const getUserMedia = vi.fn()
      .mockRejectedValueOnce(new DOMException('', 'NotReadableError'))
      .mockResolvedValueOnce(stream)
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })

    const pending = acquireMeetingMicrophone('headset-id')
    await vi.advanceTimersByTimeAsync(250)
    await expect(pending).resolves.toBe(stream)
    expect(getUserMedia).toHaveBeenCalledTimes(2)
  })

  it('does not retry when microphone permission is denied', async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException('', 'NotAllowedError'))
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })

    await expect(acquireMeetingMicrophone('headset-id')).rejects.toMatchObject({ name: 'NotAllowedError' })
    expect(getUserMedia).toHaveBeenCalledOnce()
  })

  it('records screen video with microphone audio without requesting display audio', async () => {
    const stopDisplay = vi.fn()
    const stopMic = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue(new TestStream([{ kind: 'audio', stop: stopMic }]))
    const getDisplayMedia = vi.fn().mockResolvedValue(new TestStream([{ kind: 'video', stop: stopDisplay }]))
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia, getDisplayMedia } })
    vi.stubGlobal('MediaStream', TestStream)

    const capture = await captureMeetingSources({ ...DEFAULT_CAPTURE_OPTIONS, screen: true, systemAudio: true })

    expect(getDisplayMedia).toHaveBeenCalledWith(expect.objectContaining({ audio: false }))
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(capture.stream.getVideoTracks()).toHaveLength(1)
    expect(capture.stream.getAudioTracks()).toHaveLength(1)
    capture.cleanup()
    expect(stopDisplay).toHaveBeenCalledOnce()
    expect(stopMic).toHaveBeenCalledOnce()
  })

  it('releases the selected screen when microphone access fails', async () => {
    const stop = vi.fn()
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(new Error('denied')), getDisplayMedia: vi.fn().mockResolvedValue(new TestStream([{ kind: 'video', stop }])) } })
    await expect(captureMeetingSources({ ...DEFAULT_CAPTURE_OPTIONS, screen: true })).rejects.toThrow('denied')
    expect(stop).toHaveBeenCalledOnce()
  })
})
