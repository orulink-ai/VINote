import { useEffect, useRef, useState } from 'react'
import { Check, MessageSquareText, Wand2, X } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Conversation, ConversationContent, ConversationEmptyState, ConversationMessage, ConversationScrollButton } from '@/components/ui/conversation'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Toggle } from '@/components/ui/toggle'
import { useI18n } from '../../lib/i18n'
import { findActiveTranscriptSegment, formatTranscriptTimestamp, transcriptText, type TranscriptEvidence, type TranscriptTextMode } from '../../lib/noteTranscript'

interface Props { evidence: TranscriptEvidence | null; loading: boolean; currentTimestamp: number; textMode: TranscriptTextMode; onTextModeChange: (mode: TranscriptTextMode) => void; onSeek: (seconds: number) => void; onSaveAlias: (speakerId: string, label: string) => Promise<void> }

export function TranscriptEvidencePanel({ evidence, loading, currentTimestamp, textMode, onTextModeChange, onSeek, onSaveAlias }: Props) {
  const turnRefs = useRef<Array<HTMLDivElement | null>>([]); const lastScrolled = useRef(-1)
  const { locale } = useI18n(); const zh = locale.startsWith('zh')
  const [editingSpeakerId, setEditingSpeakerId] = useState(''); const [speakerDraft, setSpeakerDraft] = useState(''); const [error, setError] = useState('')
  const segments = evidence?.segments ?? []; const metadata = evidence?.metadata ?? {}; const activeIndex = findActiveTranscriptSegment(segments, currentTimestamp)
  const hasRawText = segments.some(segment => Boolean(segment.raw_text && segment.raw_text !== segment.cleaned_text))
  useEffect(() => { if (activeIndex < 0 || activeIndex === lastScrolled.current) return; lastScrolled.current = activeIndex; turnRefs.current[activeIndex]?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) }, [activeIndex])
  const saveAlias = async () => { if (!editingSpeakerId) return; try { await onSaveAlias(editingSpeakerId, speakerDraft.trim()); setEditingSpeakerId(''); setSpeakerDraft(''); setError('') } catch { setError(zh ? '无法保存说话人名称' : 'Unable to save speaker name') } }
  if (loading) return <div className="grid flex-1 gap-4 p-6"><Skeleton className="h-24 w-4/5" /><Skeleton className="ml-auto h-24 w-4/5" /><Skeleton className="h-24 w-4/5" /></div>
  return <section className="flex min-h-0 flex-1 flex-col bg-background">
    <div className="flex flex-wrap items-center gap-2 border-b px-5 py-3">{evidence?.language ? <Badge variant="outline">{zh ? '语言' : 'Language'} · {evidence.language}</Badge> : null}<Badge variant="outline">{zh ? '片段' : 'Segments'} · {segments.length}</Badge>{Object.entries(metadata).slice(0, 4).map(([key, value]) => value === null || value === undefined || typeof value === 'object' ? null : <Badge key={key} variant="secondary">{key} · {String(value)}</Badge>)}{hasRawText ? <Toggle pressed={textMode === 'clean'} onPressedChange={() => onTextModeChange(textMode === 'clean' ? 'raw' : 'clean')} aria-label={textMode === 'clean' ? (zh ? '显示原始转写' : 'Show raw ASR') : (zh ? '显示智能整理' : 'Show smart cleanup')}><Wand2 />{textMode === 'clean' ? (zh ? '智能整理' : 'Smart cleanup') : (zh ? '原始转写' : 'Raw ASR')}</Toggle> : null}</div>
    {error ? <Alert variant="destructive" className="m-4 mb-0"><AlertDescription>{error}</AlertDescription></Alert> : null}
    <Conversation><ConversationContent className="mx-auto w-full max-w-4xl px-6 py-5">{segments.length ? segments.map((segment, index) => { const speakerId = segment.speaker_id || 'speaker_unknown'; const fallback = segment.speaker_label || (zh ? '说话人' : 'Speaker'); const label = evidence?.aliases[speakerId] || fallback; const active = activeIndex === index; const editing = editingSpeakerId === speakerId; return <div key={`${segment.start}-${speakerId}-${index}`} ref={node => { turnRefs.current[index] = node }}><ConversationMessage speaker={label} time={formatTranscriptTimestamp(segment.start)} active={active}><div className="grid gap-2"><Button type="button" variant="ghost" className="h-auto w-full justify-start whitespace-normal p-0 text-left font-normal hover:bg-transparent" aria-current={active ? 'true' : undefined} onClick={() => onSeek(segment.start)}>{transcriptText(segment, textMode)}</Button>{editing ? <div className="flex gap-2"><Input autoFocus aria-label={`Rename ${speakerId}`} value={speakerDraft} maxLength={80} onChange={event => setSpeakerDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') void saveAlias(); if (event.key === 'Escape') setEditingSpeakerId('') }} /><Button size="icon" variant="secondary" title={zh ? '保存说话人名称' : 'Save speaker name'} onClick={() => void saveAlias()}><Check /></Button><Button size="icon" variant="ghost" title={zh ? '取消重命名' : 'Cancel speaker rename'} onClick={() => setEditingSpeakerId('')}><X /></Button></div> : <Button variant="link" size="sm" className="w-fit px-0 text-muted-foreground" aria-label={`Rename ${speakerId}`} onClick={() => { setEditingSpeakerId(speakerId); setSpeakerDraft(label); setError('') }}>{zh ? '重命名说话人' : 'Rename speaker'}</Button>}</div></ConversationMessage></div> }) : <ConversationEmptyState icon={<MessageSquareText />} title={zh ? '暂无逐字稿' : 'Transcript unavailable'} description={zh ? '处理完成后，这里会按说话人显示完整对话。' : 'The transcript will appear here as a speaker based conversation after processing.'} />}</ConversationContent><ConversationScrollButton /></Conversation>
  </section>
}
