export interface TranscriptEvidenceSegment {
  start: number
  end: number
  text: string
  raw_text?: string | null
  cleaned_text?: string | null
  speaker_id?: string | null
  speaker_label?: string | null
}

export interface TranscriptEvidence {
  language?: string | null
  full_text: string
  segments: TranscriptEvidenceSegment[]
  aliases: Record<string, string>
  metadata?: Record<string, unknown>
}

export type TranscriptTextMode = 'clean' | 'raw'

export function transcriptText(segment: TranscriptEvidenceSegment, mode: TranscriptTextMode) {
  if (mode === 'raw') {
    return segment.raw_text || segment.text
  }
  return segment.cleaned_text || segment.text
}

export function formatTranscriptTimestamp(seconds: number) {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  const minutes = Math.floor(safeSeconds / 60)
  const remainder = safeSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
}

export function findActiveTranscriptSegment(segments: TranscriptEvidenceSegment[], seconds: number) {
  let previous = -1
  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index]
    if (seconds >= segment.start) {
      previous = index
    }
    if (segment.end > segment.start && seconds >= segment.start && seconds < segment.end) {
      return index
    }
  }
  return previous
}

export function renderTranscriptMarkdown(
  evidence: TranscriptEvidence,
  mode: TranscriptTextMode,
) {
  return evidence.segments
    .map((segment) => {
      const speakerId = segment.speaker_id || 'speaker_unknown'
      const speaker = evidence.aliases[speakerId] || segment.speaker_label || 'Speaker'
      return `**${speaker}** _${formatTranscriptTimestamp(segment.start)}_\n\n${transcriptText(segment, mode)}`
    })
    .join('\n\n---\n\n')
}
