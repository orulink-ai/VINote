import { useEffect, useRef, useState } from 'react'
import { Check, MessageSquareText, Wand2, X } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Conversation, ConversationContent, ConversationEmptyState, ConversationMessage, ConversationScrollButton } from '@/components/ui/conversation'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Toggle } from '@/components/ui/toggle'
import { findActiveTranscriptSegment, formatTranscriptTimestamp, transcriptText, type TranscriptEvidence, type TranscriptTextMode } from '../../lib/noteTranscript'

interface Props { evidence: TranscriptEvidence | null; loading: boolean; currentTimestamp: number; textMode: TranscriptTextMode; onTextModeChange: (mode: TranscriptTextMode) => void; onSeek: (seconds: number) => void; onSaveAlias: (speakerId: string, label: string) => Promise<void> }

export function TranscriptEvidencePanel({ evidence, loading, currentTimestamp, textMode, onTextModeChange, onSeek, onSaveAlias }: Props) {
  const turnRefs = useRef<Array<HTMLDivElement | null>>([]); const lastScrolled = useRef(-1)
  const [editingSpeakerId, setEditingSpeakerId] = useState(''); const [speakerDraft, setSpeakerDraft] = useState(''); const [error, setError] = useState('')
  const segments = evidence?.segments ?? []; const metadata = evidence?.metadata ?? {}; const activeIndex = findActiveTranscriptSegment(segments, currentTimestamp)
  const hasRawText = segments.some(segment => Boolean(segment.raw_text && segment.raw_text !== segment.cleaned_text))
  useEffect(() => { if (activeIndex < 0 || activeIndex === lastScrolled.current) return; lastScrolled.current = activeIndex; turnRefs.current[activeIndex]?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) }, [activeIndex])
  const saveAlias = async () => { if (!editingSpeakerId) return; try { await onSaveAlias(editingSpeakerId, speakerDraft.trim()); setEditingSpeakerId(''); setSpeakerDraft(''); setError('') } catch { setError('Unable to save speaker name') } }
  if (loading) return <div className="grid flex-1 gap-4 p-6"><Skeleton className="h-24 w-4/5" /><Skeleton className="ml-auto h-24 w-4/5" /><Skeleton className="h-24 w-4/5" /></div>
  return <section className="flex min-h-0 flex-1 flex-col bg-background">
    <div className="flex flex-wrap items-center gap-2 border-b p-4">{evidence?.language ? <Badge variant="outline">Language · {evidence.language}</Badge> : null}<Badge variant="outline">Segments · {segments.length}</Badge>{Object.entries(metadata).slice(0, 4).map(([key, value]) => value === null || value === undefined || typeof value === 'object' ? null : <Badge key={key} variant="secondary">{key} · {String(value)}</Badge>)}{hasRawText ? <Toggle pressed={textMode === 'clean'} onPressedChange={() => onTextModeChange(textMode === 'clean' ? 'raw' : 'clean')} aria-label={textMode === 'clean' ? 'Show raw ASR' : 'Show smart cleanup'}><Wand2 />{textMode === 'clean' ? 'Smart cleanup' : 'Raw ASR'}</Toggle> : null}</div>
    {error ? <Alert variant="destructive" className="m-4 mb-0"><AlertDescription>{error}</AlertDescription></Alert> : null}
    <Conversation><ConversationContent>{segments.length ? segments.map((segment, index) => { const speakerId = segment.speaker_id || 'speaker_unknown'; const fallback = segment.speaker_label || 'Speaker'; const label = evidence?.aliases[speakerId] || fallback; const active = activeIndex === index; const editing = editingSpeakerId === speakerId; return <div key={`${segment.start}-${speakerId}-${index}`} ref={node => { turnRefs.current[index] = node }}><ConversationMessage speaker={label} time={formatTranscriptTimestamp(segment.start)} active={active}><div className="grid gap-3"><Button type="button" className="text-left" aria-current={active ? 'true' : undefined} onClick={() => onSeek(segment.start)}>{transcriptText(segment, textMode)}</Button>{editing ? <div className="flex gap-2"><Input autoFocus aria-label={`Rename ${speakerId}`} value={speakerDraft} maxLength={80} onChange={event => setSpeakerDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void saveAlias(); if (event.key === 'Escape') setEditingSpeakerId('') }} /><Button size="icon" variant="secondary" title="Save speaker name" onClick={() => void saveAlias()}><Check /></Button><Button size="icon" variant="ghost" title="Cancel speaker rename" onClick={() => setEditingSpeakerId('')}><X /></Button></div> : <Button variant="link" size="sm" className="w-fit px-0" aria-label={`Rename ${speakerId}`} onClick={() => { setEditingSpeakerId(speakerId); setSpeakerDraft(label); setError('') }}>{'Rename speaker'}</Button>}</div></ConversationMessage></div> }) : <ConversationEmptyState icon={<MessageSquareText />} title="Transcript unavailable" description="The transcript will appear here as a speaker based conversation after processing." />}</ConversationContent><ConversationScrollButton /></Conversation>
  </section>
}
