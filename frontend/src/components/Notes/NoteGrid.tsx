import { noteOrigin } from '@/lib/noteOrigin'
import { ArrowUpRight, FileText, Mic2, Users } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '../../lib/i18n'
import type { NoteRecord } from '../../stores/noteLibraryStore'

interface NoteGridProps { notes: NoteRecord[]; loading?: boolean; emptyTitle: string; emptyBody: string; onOpen: (note: NoteRecord) => void }
const failedRecording = (note: NoteRecord) => ['meeting_recording', 'meeting_video'].includes(note.sourceType || '') && ['failed', 'transcribing_failed', 'generation_failed'].includes(note.status || '')

export function NoteGrid({ notes, loading = false, emptyTitle, emptyBody, onOpen }: NoteGridProps) {
  const { copy, formatDate, locale } = useI18n()
  const zh = locale.startsWith('zh')
  if (loading) return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2, 3, 4, 5].map(item => <div key={item} className="grid min-h-52 gap-3 rounded-2xl border p-5"><Skeleton className="size-10 rounded-xl" /><Skeleton className="h-5 w-2/3" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-4/5" /></div>)}</div>
  if (!notes.length) return <Empty className="min-h-64 border border-dashed bg-card"><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{emptyTitle}</EmptyTitle><EmptyDescription>{emptyBody}</EmptyDescription></EmptyHeader></Empty>
  return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{notes.map((note, index) => { const meeting = note.sourceType?.startsWith('meeting'); return <button key={note.id} type="button" onClick={() => onOpen(note)} style={{ animationDelay: `${Math.min(index, 8) * 55}ms` }} className="interactive-card motion-rise group flex min-h-56 flex-col rounded-2xl border bg-card p-5 text-left shadow-sm hover:border-foreground/20">
    <div className="flex items-start justify-between gap-3"><span className="grid size-10 place-items-center rounded-xl bg-muted text-muted-foreground transition-colors group-hover:bg-foreground group-hover:text-background">{meeting ? <Mic2 className="size-4" /> : <FileText className="size-4" />}</span><ArrowUpRight className="size-4 text-muted-foreground opacity-0 transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:opacity-100" /></div>
    <h3 className="mt-5 line-clamp-2 font-semibold leading-6">{note.title}</h3><p className="mt-2 line-clamp-3 text-sm leading-6 text-muted-foreground">{note.content || copy.notes.noContent}</p>
    <div className="mt-auto flex items-end justify-between gap-3 pt-5 text-xs text-muted-foreground"><div className="grid gap-2"><span>{noteOrigin(note.generationClient, zh)} · {formatDate(note.updatedAt || note.createdAt)}</span>{failedRecording(note) ? <Badge variant="destructive">{zh ? '处理失败' : 'Processing failed'}</Badge> : null}</div><Badge variant={note.scope === 'team' ? 'default' : 'secondary'} className="shrink-0"><Users className="size-3" />{note.scope === 'team' ? note.teamName || (zh ? '团队' : 'Team') : (zh ? '个人' : 'Personal')}</Badge></div>
  </button>})}</div>
}
