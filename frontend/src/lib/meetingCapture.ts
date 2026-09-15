export interface MeetingCaptureOptions {
  title: string
  microphoneId: string
  screen: boolean
  systemAudio: boolean
  diarize: boolean
  speakerCount?: number
}

export const START_MEETING_EVENT = 'vinote-start-meeting'
export const DEFAULT_CAPTURE_OPTIONS: MeetingCaptureOptions = {
  title: '', microphoneId: '', screen: false, systemAudio: false, diarize: true,
}

/** Permission prompts cannot be dismissed programmatically; dispose late results after cancellation. */
function acquireStream(request: Promise<MediaStream>, signal?: AbortSignal) {
  return new Promise<MediaStream>((resolve, reject) => {
    let settled = false
    const finish = () => { settled = true; clearTimeout(timer); signal?.removeEventListener('abort', abort) }
    const abort = () => { if (!settled) { finish(); reject(new Error('microphone_request_cancelled')) } }
    const timer = setTimeout(() => { if (!settled) { finish(); reject(new Error('microphone_request_timeout')) } }, 20000)
    signal?.addEventListener('abort', abort, { once: true })
    if (signal?.aborted) abort()
    request.then(stream => {
      if (settled) { stream.getTracks().forEach(track => track.stop()); return }
      finish(); resolve(stream)
    }, error => { if (!settled) { finish(); reject(error) } })
  })
}

/** Call in the originating click handler: screen capture requires user activation. */
export async function captureMeetingSources(options: MeetingCaptureOptions, signal?: AbortSignal) {
  const streams: MediaStream[] = []
  let context: AudioContext | undefined
  let closed = false
  const cleanup = () => {
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
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('当前桌面环境不支持屏幕采集。')
      display = await acquireStream(navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: 10, max: 15 }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: options.systemAudio,
      }), signal)
      streams.push(display)
      checkCancelled()
      if (options.systemAudio && !display.getAudioTracks().length) {
        throw new Error('未采集到会议声音。请重新选择支持共享声音的屏幕并勾选共享音频，或关闭会议声音选项。')
      }
    }
    const microphone = await acquireStream(navigator.mediaDevices.getUserMedia({
      audio: options.microphoneId ? { deviceId: { exact: options.microphoneId } } : true,
    }), signal)
    streams.push(microphone)
    checkCancelled()
    let audioTracks = microphone.getAudioTracks()
    if (display?.getAudioTracks().length) {
      context = new AudioContext()
      await context.resume()
      checkCancelled()
      const destination = context.createMediaStreamDestination()
      streams.push(destination.stream)
      context.createMediaStreamSource(microphone).connect(destination)
      context.createMediaStreamSource(new MediaStream(display.getAudioTracks())).connect(destination)
      audioTracks = destination.stream.getAudioTracks()
    }
    return {
      stream: new MediaStream([...audioTracks, ...(options.screen ? display?.getVideoTracks() || [] : [])]),
      display,
      cleanup,
    }
  } catch (error) {
    cleanup()
    throw error
  }
}
