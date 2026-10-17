// Re-encodes the raw blob produced by MediaRecorder into a canonical 16kHz
// mono PCM WAV. Browser MediaRecorder (especially inside Tauri / WKWebView)
// sometimes writes a webm container whose EBML header is missing or shifted,
// which causes libavformat-based transcoders to fail with the generic
// "Invalid data found when processing input" error.
//
// Decoding through `AudioContext.decodeAudioData` validates the bytes and
// extracts the raw PCM samples; encoding back to WAV through an
// `OfflineAudioContext` gives us a header that ffmpeg, faster-whisper, and
// the Whisper C++ pipeline can all consume without warnings.

const TARGET_SAMPLE_RATE = 16000

declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext
  }
}

function getAudioContextCtor(): typeof AudioContext | null {
  if (typeof window === 'undefined') return null
  if (typeof window.AudioContext === 'function') return window.AudioContext
  if (typeof window.webkitAudioContext === 'function') return window.webkitAudioContext
  return null
}

function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const bytesPerSample = 2
  const blockAlign = bytesPerSample
  const byteRate = sampleRate * blockAlign
  const dataSize = samples.length * bytesPerSample
  const buffer = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buffer)

  // RIFF header
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(view, 8, 'WAVE')
  // fmt chunk
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, 16, true) // bits per sample
  // data chunk
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]))
    const value = sample < 0 ? sample * 0x8000 : sample * 0x7fff
    view.setInt16(offset, value, true)
    offset += 2
  }

  return new Blob([buffer], { type: 'audio/wav' })
}

function writeString(view: DataView, offset: number, value: string) {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i))
  }
}

export async function normalizeAudioBlob(blob: Blob): Promise<Blob> {
  const Ctor = getAudioContextCtor()
  if (!Ctor) return blob

  try {
    const arrayBuffer = await blob.arrayBuffer()
    const decodingContext = new Ctor()
    let decoded: AudioBuffer
    try {
      decoded = await decodingContext.decodeAudioData(arrayBuffer.slice(0))
    } finally {
      decodingContext.close?.()
    }

    const duration = decoded.duration
    const channelCount = 1
    const offline = new OfflineAudioContext(channelCount, Math.ceil(duration * TARGET_SAMPLE_RATE), TARGET_SAMPLE_RATE)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start(0)

    const rendered = await offline.startRendering()
    const channelData = rendered.getChannelData(0)
    const wav = encodeWav(channelData, TARGET_SAMPLE_RATE)
    if (wav.size === 0) return blob
    return wav
  } catch (error) {
    // If the browser cannot decode the blob (truly corrupt), surface the
    // original to the caller — the backend will produce a clearer error
    // than silently dropping the user's recording.
    if (typeof console !== 'undefined') {
      console.warn('[audioNormalizer] re-encode failed, returning original blob:', error)
    }
    return blob
  }
}