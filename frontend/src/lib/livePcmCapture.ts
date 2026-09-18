const TARGET_RATE = 16000
const FRAME_SAMPLES = 1600

function resample(input: Float32Array, sourceRate: number) {
  if (sourceRate === TARGET_RATE) return input
  const ratio = sourceRate / TARGET_RATE
  const output = new Float32Array(Math.max(1, Math.floor(input.length / ratio)))
  for (let index = 0; index < output.length; index += 1) {
    const position = index * ratio
    const left = Math.floor(position)
    const right = Math.min(input.length - 1, left + 1)
    const weight = position - left
    output[index] = input[left] * (1 - weight) + input[right] * weight
  }
  return output
}

function toPcm16(samples: Float32Array) {
  const bytes = new Uint8Array(samples.length * 2)
  const view = new DataView(bytes.buffer)
  samples.forEach((sample, index) => {
    const clamped = Math.max(-1, Math.min(1, sample))
    view.setInt16(index * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
  })
  return bytes
}

/** Reads the already acquired meeting stream. It never requests another device. */
export async function startLivePcmCapture(stream: MediaStream, onFrame: (frame: Uint8Array) => void) {
  const Context = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Context) throw new Error('audio_context_unsupported')
  const context = new Context()
  await context.resume()
  const source = context.createMediaStreamSource(stream)
  const processor = context.createScriptProcessor(4096, Math.max(1, source.channelCount), 1)
  const silent = context.createGain()
  silent.gain.value = 0
  let queued: number[] = []
  let stopped = false

  processor.onaudioprocess = event => {
    if (stopped) return
    const channels = event.inputBuffer.numberOfChannels
    const mono = new Float32Array(event.inputBuffer.length)
    for (let channel = 0; channel < channels; channel += 1) {
      const values = event.inputBuffer.getChannelData(channel)
      for (let index = 0; index < values.length; index += 1) mono[index] += values[index] / channels
    }
    queued.push(...resample(mono, context.sampleRate))
    while (queued.length >= FRAME_SAMPLES) {
      onFrame(toPcm16(Float32Array.from(queued.splice(0, FRAME_SAMPLES))))
    }
  }
  source.connect(processor)
  processor.connect(silent)
  silent.connect(context.destination)

  return {
    stop() {
      if (stopped) return new Uint8Array()
      stopped = true
      processor.onaudioprocess = null
      source.disconnect(); processor.disconnect(); silent.disconnect()
      void context.close()
      const tail = queued.length ? toPcm16(Float32Array.from(queued)) : new Uint8Array()
      queued = []
      return tail
    },
  }
}
