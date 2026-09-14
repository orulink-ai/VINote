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

/** Call in the originating click handler: screen capture requires user activation. */
export async function captureMeetingSources(options: MeetingCaptureOptions) {
  const streams: MediaStream[] = []
  let context: AudioContext | undefined
  try {
    let display: MediaStream | undefined
    if (options.screen || options.systemAudio) {
      if (!navigator.mediaDevices?.getDisplayMedia) throw new Error('当前桌面环境不支持屏幕采集。')
      display = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: 10, max: 15 }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: options.systemAudio,
      })
      streams.push(display)
      if (options.systemAudio && !display.getAudioTracks().length) {
        throw new Error('未采集到会议声音。请重新选择支持共享声音的屏幕并勾选共享音频，或关闭会议声音选项。')
      }
    }
    const microphone = await navigator.mediaDevices.getUserMedia({
      audio: options.microphoneId ? { deviceId: { exact: options.microphoneId } } : true,
    })
    streams.push(microphone)
    let audioTracks = microphone.getAudioTracks()
    if (display?.getAudioTracks().length) {
      context = new AudioContext()
      await context.resume()
      const destination = context.createMediaStreamDestination()
      context.createMediaStreamSource(microphone).connect(destination)
      context.createMediaStreamSource(new MediaStream(display.getAudioTracks())).connect(destination)
      audioTracks = destination.stream.getAudioTracks()
    }
    return {
      stream: new MediaStream([...audioTracks, ...(options.screen ? display?.getVideoTracks() || [] : [])]),
      display,
      cleanup: () => { streams.forEach(stream => stream.getTracks().forEach(track => track.stop())); void context?.close() },
    }
  } catch (error) {
    streams.forEach(stream => stream.getTracks().forEach(track => track.stop()))
    void context?.close()
    throw error
  }
}
