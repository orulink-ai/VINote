export type LiveTranscriptStatus =
  | 'idle' | 'connecting' | 'starting' | 'live' | 'paused'
  | 'finalizing' | 'completed' | 'failed'

export interface LiveTranscriptSegment {
  id: string
  text: string
  speaker?: string
  startMs?: number
  endMs?: number
  final: boolean
  kind?: 'speech' | 'background'
}

export interface LiveTranscriptDiagnostics {
  connectionLatencyMs?: number
  sessionStartLatencyMs?: number
  firstPartialLatencyMs?: number
  completionLatencyMs?: number
  frameCount: number
  sentBytes: number
  partialCount: number
  finalCount: number
  audioDurationMs: number
  closeCode?: number
  errorCode?: string
}
