import { apiJson } from './api'
import { startLivePcmCapture } from './livePcmCapture'
import { encodeVla2AudioFrame, parseRealtimeEvent } from './vilabRealtimeProtocol'
import type { LiveTranscriptDiagnostics, LiveTranscriptSegment, LiveTranscriptStatus } from '../types/liveTranscript'

interface RealtimeConnection { url: string; language: string }
interface RealtimeCallbacks {
  onStatus: (status: LiveTranscriptStatus, error?: string) => void
  onSegments: (segments: LiveTranscriptSegment[]) => void
  onDiagnostics?: (diagnostics: LiveTranscriptDiagnostics) => void
}

const emptyDiagnostics = (): LiveTranscriptDiagnostics => ({
  frameCount: 0, sentBytes: 0, partialCount: 0, finalCount: 0, audioDurationMs: 0,
})

function eventText(event: Record<string, unknown>) {
  const stable = typeof event.stableText === 'string' ? event.stableText : ''
  const unstable = typeof event.unstableText === 'string' ? event.unstableText : ''
  return stable || unstable ? `${stable}${unstable}` : typeof event.text === 'string' ? event.text : ''
}

export class VILabRealtimeClient {
  private socket: WebSocket | null = null
  private capture: Awaited<ReturnType<typeof startLivePcmCapture>> | null = null
  private sequence = 0
  private segments: LiveTranscriptSegment[] = []
  private partialId = ''
  private diagnostics = emptyDiagnostics()
  private connectedAt = 0
  private audioStartedAt = 0
  private completion: ((value: void) => void) | null = null
  private completionTimer: number | null = null
  private finishing = false

  constructor(
    private callbacks: RealtimeCallbacks,
    initialSegments: LiveTranscriptSegment[] = [],
  ) {
    this.segments = [...initialSegments]
  }

  async start(stream: MediaStream, sessionId: string) {
    await this.cancel()
    this.callbacks.onStatus('connecting')
    this.connectedAt = performance.now()
    this.sequence = 0
    this.partialId = ''
    this.finishing = false
    this.diagnostics = emptyDiagnostics()
    const connection = await apiJson<RealtimeConnection>('/api/vilab/realtime-connection')
    const socket = new WebSocket(connection.url)
    this.socket = socket
    socket.binaryType = 'arraybuffer'

    await new Promise<void>((resolve, reject) => {
      const fail = (error: Error) => { reject(error) }
      socket.addEventListener('open', () => {
        this.diagnostics.connectionLatencyMs = Math.round(performance.now() - this.connectedAt)
        this.callbacks.onStatus('starting')
        socket.send(JSON.stringify({
          type: 'session.start', language: connection.language || 'zh-CN', profileId: 'meeting',
          clientSessionId: sessionId, audio: { encoding: 'pcm_s16le', sampleRate: 16000, channels: 1 },
        }))
      }, { once: true })
      socket.addEventListener('error', () => fail(new Error('realtime_websocket_failed')), { once: true })
      socket.addEventListener('close', event => {
        if (this.socket !== socket) return
        this.diagnostics.closeCode = event.code
        this.callbacks.onDiagnostics?.({ ...this.diagnostics })
        if (!this.finishing && event.code !== 1000) this.fail(new Error(`realtime_websocket_closed_${event.code}`))
      })
      socket.addEventListener('message', async message => {
        if (typeof message.data !== 'string') return
        const event = parseRealtimeEvent(message.data)
        if (!event) return
        if (event.type === 'session.started') {
          this.diagnostics.sessionStartLatencyMs = Math.round(performance.now() - this.connectedAt)
          try {
            this.capture = await startLivePcmCapture(stream, frame => this.sendFrame(frame))
            this.audioStartedAt = performance.now()
            this.callbacks.onStatus('live')
            resolve()
          } catch (error) { reject(error) }
          return
        }
        this.handleEvent(event)
      })
    }).catch(error => {
      this.fail(error)
      throw error
    })
  }

  private sendFrame(frame: Uint8Array, last = false) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return
    this.socket.send(encodeVla2AudioFrame(frame, this.sequence, last))
    this.sequence += 1
    this.diagnostics.frameCount += 1
    this.diagnostics.sentBytes += frame.byteLength
    this.diagnostics.audioDurationMs += Math.round(frame.byteLength / 32)
    this.callbacks.onDiagnostics?.({ ...this.diagnostics })
  }

  private handleEvent(event: Record<string, unknown>) {
    const type = String(event.type || '')
    if (type === 'asr.partial' || type === 'asr.final') {
      const text = eventText(event).trim()
      if (!text) return
      if (!this.diagnostics.firstPartialLatencyMs) this.diagnostics.firstPartialLatencyMs = Math.round(performance.now() - this.audioStartedAt)
      const final = type === 'asr.final'
      final ? this.diagnostics.finalCount += 1 : this.diagnostics.partialCount += 1
      const id = final ? `final-${Date.now()}-${this.diagnostics.finalCount}` : (this.partialId ||= `partial-${Date.now()}`)
      const segment: LiveTranscriptSegment = {
        id, text, final,
        speaker: typeof event.speaker === 'string' ? event.speaker : undefined,
        startMs: typeof event.startMs === 'number' ? event.startMs : undefined,
        endMs: typeof event.endMs === 'number' ? event.endMs : undefined,
      }
      this.segments = this.segments.filter(item => item.id !== this.partialId)
      this.segments.push(segment)
      if (final) this.partialId = ''
      this.callbacks.onSegments([...this.segments])
      this.callbacks.onDiagnostics?.({ ...this.diagnostics })
      return
    }
    if (type === 'session.completed') {
      this.diagnostics.completionLatencyMs = Math.round(performance.now() - this.connectedAt)
      this.callbacks.onStatus('completed')
      this.completion?.(); this.completion = null
      this.closeSocket(1000, 'completed')
      return
    }
    if (type === 'error') this.fail(new Error(String(event.message || event.code || 'realtime_service_failed')))
  }

  async finish() {
    if (!this.socket) return
    this.finishing = true
    this.callbacks.onStatus('finalizing')
    const tail = this.capture?.stop() || new Uint8Array()
    this.capture = null
    if (this.socket.readyState === WebSocket.OPEN) this.sendFrame(tail, true)
    await new Promise<void>(resolve => {
      this.completion = resolve
      this.completionTimer = window.setTimeout(() => {
        this.completionTimer = null
        this.completion = null
        resolve()
      }, 8000)
    })
    this.closeSocket(1000, 'client finished')
  }

  async cancel() {
    this.finishing = true
    this.capture?.stop(); this.capture = null
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'session.cancel', reason: 'client_cancelled' }))
    }
    this.closeSocket(1000, 'cancelled')
  }

  getSegments() { return [...this.segments] }
  getDiagnostics() { return { ...this.diagnostics } }

  private fail(error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    this.diagnostics.errorCode = message
    this.capture?.stop(); this.capture = null
    this.callbacks.onDiagnostics?.({ ...this.diagnostics })
    this.callbacks.onStatus('failed', message)
    if (this.completionTimer !== null) window.clearTimeout(this.completionTimer)
    this.completionTimer = null
    this.completion?.(); this.completion = null
    this.closeSocket(1000, 'realtime failed')
  }

  private closeSocket(code: number, reason: string) {
    if (this.completionTimer !== null) window.clearTimeout(this.completionTimer)
    this.completionTimer = null
    const socket = this.socket
    this.socket = null
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(code, reason)
  }
}
