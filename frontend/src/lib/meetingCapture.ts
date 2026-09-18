import { captureDiagnostic, captureFailure } from './captureDiagnostics'

export type MeetingMode = 'recording' | 'minutes'
export type MeetingType = 'audio' | 'video'

export interface MeetingCaptureOptions {
  sessionId: string
  mode: MeetingMode
  meetingType: MeetingType
  title: string
  microphoneId: string
  screen: boolean
  systemAudio: boolean
  diarize: boolean
  speakerCount?: number
}

export const SYSTEM_AUDIO_UNAVAILABLE = '当前共享未包含电脑音频。可以继续录制麦克风，但不会录到电脑中播放的其他参会人声音。'
export const DISPLAY_CAPTURE_FAILED = '屏幕共享未能启动。请重新选择共享，或仅录麦克风继续。'

export const START_MEETING_EVENT = 'vinote-start-meeting'
export const DEFAULT_CAPTURE_OPTIONS: MeetingCaptureOptions = {
  sessionId: '', mode: 'recording', meetingType: 'audio',
  title: '', microphoneId: '', screen: false, systemAudio: true, diarize: true,
}

/** Permission prompts cannot be dismissed programmatically; dispose late results after cancellation. */
type CaptureStage = 'display' | 'microphone'

function captureStageError(stage: CaptureStage, reason: string) {
  return new Error(`${stage}_${reason}`)
}

function acquireStream(request: Promise<MediaStream>, signal?: AbortSignal, stage: CaptureStage = 'microphone') {
  const startedAt = Date.now()
  captureDiagnostic(`${stage}.requested`)
  return new Promise<MediaStream>((resolve, reject) => {
    let settled = false
    const finish = () => { settled = true; clearTimeout(timer); signal?.removeEventListener('abort', abort) }
    const abort = () => {
      if (!settled) {
        const error = captureStageError(stage, 'request_cancelled')
        captureFailure(`${stage}.cancelled`, error, startedAt)
        finish(); reject(error)
      }
    }
    // The screen picker is user-driven. Expiring it while it is still open
    // discards a subsequently authorized stream and looks like capture failure.
    // Explicit cancellation still releases any late result. Device startup
    // keeps its timeout because it does not require choosing a shared surface.
    const timer = stage === 'display' ? undefined : setTimeout(() => {
      if (!settled) {
        const error = captureStageError(stage, 'request_timeout')
        captureFailure(`${stage}.timeout`, error, startedAt)
        finish(); reject(error)
      }
    }, 20000)
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) abort()
    request.then(stream => {
      if (settled) { captureDiagnostic(`${stage}.late-result-released`); stream.getTracks().forEach(track => track.stop()); return }
      captureDiagnostic(`${stage}.acquired`, { elapsedMs: Date.now() - startedAt, audioTracks: stream.getAudioTracks().length, videoTracks: stream.getVideoTracks().length })
      finish(); resolve(stream)
    }, error => { captureFailure(`${stage}.rejected`, error, startedAt); if (!settled) { finish(); reject(error) } })
  })
}

function mediaErrorName(error: unknown) {
  return error instanceof DOMException ? error.name : error instanceof Error ? error.name : ''
}

function isPermissionFailure(error: unknown) {
  return ['NotAllowedError', 'SecurityError'].includes(mediaErrorName(error))
}

function isStaleDeviceSelection(error: unknown) {
  return ['OverconstrainedError', 'ConstraintNotSatisfiedError', 'NotFoundError', 'DevicesNotFoundError'].includes(mediaErrorName(error))
}

function isTemporaryDeviceFailure(error: unknown) {
  const name = mediaErrorName(error)
  if (['NotReadableError', 'AbortError', 'TrackStartError'].includes(name)) return true
  const message = error instanceof Error ? error.message.toLowerCase() : String(error || '').toLowerCase()
  return message.includes('could not start audio source') || message.includes('device is busy') || message.includes('track start')
}

function waitForDeviceRelease(signal?: AbortSignal, delayMs = 250) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) { reject(new Error('microphone_request_cancelled')); return }
    const abort = () => { window.clearTimeout(timer); reject(new Error('microphone_request_cancelled')) }
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, delayMs)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

async function requestMicrophone(constraints: MediaTrackConstraints | true, signal?: AbortSignal) {
  return acquireStream(navigator.mediaDevices.getUserMedia({ audio: constraints }), signal, 'microphone')
}

/**
 * Windows can replace a headset's communication endpoint while it remains connected.
 * Retry a transient driver start once, then fall back from a stale selected endpoint to
 * the current system default. Permission failures are never retried or hidden.
 */
export async function acquireMeetingMicrophone(microphoneId = '', signal?: AbortSignal) {
  const selected = microphoneId ? { deviceId: { exact: microphoneId } } : true
  try {
    return await requestMicrophone(selected, signal)
  } catch (firstError) {
    if (isPermissionFailure(firstError)) throw firstError
    if (isTemporaryDeviceFailure(firstError)) {
      await waitForDeviceRelease(signal)
      try {
        return await requestMicrophone(selected, signal)
      } catch (retryError) {
        if (isPermissionFailure(retryError)) throw retryError
        if (!microphoneId || (!isTemporaryDeviceFailure(retryError) && !isStaleDeviceSelection(retryError))) throw retryError
      }
    } else if (!microphoneId || !isStaleDeviceSelection(firstError)) {
      throw firstError
    }
    return requestMicrophone(true, signal)
  }
}

/** Call in the originating click handler: screen capture requires user activation. */
export async function captureMeetingSources(options: MeetingCaptureOptions, signal?: AbortSignal) {
  const startedAt = Date.now()
  captureDiagnostic('capture.started', { screen: options.screen, systemAudio: options.systemAudio, selectedMicrophone: Boolean(options.microphoneId) })
  const streams: MediaStream[] = []
  let context: AudioContext | undefined
  let closed = false
  let disposed = false
  const registerStream = (stream: MediaStream) => {
    if (disposed) {
      stream.getTracks().forEach(track => track.stop())
      return stream
    }
    streams.push(stream)
    return stream
  }
  const cleanup = () => {
    captureDiagnostic('capture.cleanup')
    disposed = true
    streams.forEach(stream => stream.getTracks().forEach(track => track.stop()))
    streams.length = 0
    if (!closed && context) { closed = true; void context.close().catch(() => undefined) }
    signal?.removeEventListener('abort', cleanup)
  }
  const checkCancelled = () => { if (signal?.aborted) throw new Error('microphone_request_cancelled') }
  signal?.addEventListener('abort', cleanup, { once: true })
  try {
    checkCancelled()
    let display: MediaStream | undefined
    if (options.screen || options.systemAudio) {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error(`${DISPLAY_CAPTURE_FAILED}（当前桌面环境不支持屏幕采集 API）`)
      // Request display capture from the click, then open the microphone once
      // display acquisition completes. Do not initialize both audio sources concurrently.
      display = await acquireStream(navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: 10, max: 15 }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: options.systemAudio,
        systemAudio: 'include',
      } as DisplayMediaStreamOptions & { systemAudio: string }), signal, 'display').then(registerStream).catch(error => {
        if (signal?.aborted) throw error
        const reason = error instanceof Error ? `${error.name}: ${error.message}` : String(error)
        throw new Error(`${DISPLAY_CAPTURE_FAILED}（${reason}）`)
      })
    }
    checkCancelled()
    if (options.systemAudio && display && !display.getAudioTracks().length) {
      throw new Error(SYSTEM_AUDIO_UNAVAILABLE)
    }
    const microphone = await acquireMeetingMicrophone(options.microphoneId, signal).then(registerStream)
    checkCancelled()
    let audioTracks = microphone.getAudioTracks()
    if (display?.getAudioTracks().length) {
      captureDiagnostic('mixing.started')
      context = new AudioContext()
      await context.resume()
      checkCancelled()
      const destination = context.createMediaStreamDestination()
      streams.push(destination.stream)
      context.createMediaStreamSource(microphone).connect(destination)
      context.createMediaStreamSource(new MediaStream(display.getAudioTracks())).connect(destination)
      audioTracks = destination.stream.getAudioTracks()
      captureDiagnostic('mixing.ready')
    }
    return {
      stream: new MediaStream([...audioTracks, ...(options.screen ? display?.getVideoTracks() || [] : [])]),
      display,
      cleanup,
    }
  } catch (error) {
    captureFailure('capture.failed', error, startedAt)
    cleanup()
    throw error
  }
}
