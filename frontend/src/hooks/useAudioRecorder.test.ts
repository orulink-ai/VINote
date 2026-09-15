import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAudioRecorder } from './useAudioRecorder'

type RecorderBehavior = 'normal' | 'missing-stop-event' | 'empty'

let recorderBehavior: RecorderBehavior = 'normal'
let lastRecorder: FakeMediaRecorder | null = null
let stopTrack: ReturnType<typeof vi.fn>

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true)

  state: RecordingState = 'inactive'
  mimeType = 'audio/webm'
  ondataavailable: ((event: BlobEvent) => void) | null = null
  onerror: (() => void) | null = null
  onstop: (() => void) | null = null
  start = vi.fn(() => {
    this.state = 'recording'
  })
  pause = vi.fn(() => {
    this.state = 'paused'
  })
  resume = vi.fn(() => {
    this.state = 'recording'
  })
  requestData = vi.fn(() => {
    if (recorderBehavior === 'empty') return
    this.emitChunk('request-data')
  })
  stop = vi.fn(() => {
    this.state = 'inactive'
    if (recorderBehavior !== 'empty') {
      this.emitChunk('stop-data')
    }
    if (recorderBehavior === 'normal' || recorderBehavior === 'empty') {
      this.onstop?.()
    }
  })

  constructor() {
    lastRecorder = this
  }

  private emitChunk(value: string) {
    this.ondataavailable?.({
      data: new Blob([value], { type: this.mimeType }),
    } as BlobEvent)
  }
}

describe('useAudioRecorder', () => {
  beforeEach(() => {
    vi.useRealTimers()
    recorderBehavior = 'normal'
    lastRecorder = null
    stopTrack = vi.fn()
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getAudioTracks: () => [{ stop: stopTrack }],
          getTracks: () => [{ stop: stopTrack }],
        }),
      },
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('flushes pending media data before stopping', async () => {
    const { result } = renderHook(() => useAudioRecorder())

    await act(async () => {
      await result.current.start()
    })
    const blob = await act(async () => result.current.stop())

    expect(lastRecorder?.requestData).toHaveBeenCalledTimes(1)
    expect(lastRecorder?.stop).toHaveBeenCalledTimes(1)
    expect(blob.size).toBeGreaterThan(0)
    expect(stopTrack).toHaveBeenCalledTimes(1)
    expect(result.current.status).toBe('stopped')
  })

  it('releases the microphone immediately when the recorder fails at runtime', async () => {
    const { result } = renderHook(() => useAudioRecorder())
    await act(async () => { await result.current.start() })
    act(() => { lastRecorder?.onerror?.() })
    expect(stopTrack).toHaveBeenCalledOnce()
    expect(lastRecorder?.stop).toHaveBeenCalledOnce()
    expect(result.current.status).toBe('failed')
  })

  it('times out pending permission and releases a late microphone stream', async () => {
    vi.useFakeTimers()
    let resolveStream!: (stream: MediaStream) => void
    vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementation(() => new Promise(resolve => { resolveStream = resolve }))
    const { result } = renderHook(() => useAudioRecorder())
    let failure = ''
    await act(async () => { void result.current.start().catch(error => { failure = error.message }) })
    await act(async () => { await vi.advanceTimersByTimeAsync(20000) })
    expect(failure).toBe('microphone_request_timeout')
    expect(result.current.status).toBe('failed')
    await act(async () => { resolveStream({ getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream) })
    expect(stopTrack).toHaveBeenCalledOnce()
    expect(lastRecorder).toBeNull()
  })

  it('returns the exact MediaRecorder container instead of re-encoding it in the browser', async () => {
    const { result } = renderHook(() => useAudioRecorder())

    await act(async () => {
      await result.current.start()
    })
    const blob = await act(async () => result.current.stop())

    expect(blob.type).toContain('audio/webm')
    const payload = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result))
      reader.onerror = () => reject(reader.error)
      reader.readAsText(blob)
    })
    expect(payload).toBe('request-datastop-data')
  })

  it('finalizes the recording if the WebView never fires onstop', async () => {
    vi.useFakeTimers()
    recorderBehavior = 'missing-stop-event'
    const { result } = renderHook(() => useAudioRecorder())

    await act(async () => {
      await result.current.start()
    })

    let stopPromise: Promise<Blob>
    await act(async () => {
      stopPromise = result.current.stop()
    })
    await act(async () => {
      vi.advanceTimersByTime(3000)
    })

    const blob = await stopPromise!
    expect(blob.size).toBeGreaterThan(0)
    expect(stopTrack).toHaveBeenCalledTimes(1)
    expect(result.current.status).toBe('stopped')
  })

  it('rejects when MediaRecorder produces no audio bytes', async () => {
    recorderBehavior = 'empty'
    const { result } = renderHook(() => useAudioRecorder())

    await act(async () => {
      await result.current.start()
    })

    await expect(act(async () => result.current.stop())).rejects.toThrow('microphone_no_audio')
    expect(stopTrack).toHaveBeenCalledTimes(1)
  })
})
