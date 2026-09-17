import { FileText, Users } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'
import { useI18n } from '../../lib/i18n'
import type { NoteRecord } from '../../stores/noteLibraryStore'

interface NoteGridProps { notes: NoteRecord[]; loading?: boolean; emptyTitle: string; emptyBody: string; onOpen: (note: NoteRecord) => void }
const failedRecording = (note: NoteRecord) => note.sourceType === 'meeting_recording' && ['transcribing_failed', 'generation_failed'].includes(note.status || '')

export function NoteGrid({ notes, loading = false, emptyTitle, emptyBody, onOpen }: NoteGridProps) {
  const { copy, formatDate, locale } = useI18n()
  const zh = locale.startsWith('zh')
  if (loading) return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map(item => <Card key={item}><CardHeader><Skeleton className="h-5 w-3/4" /></CardHeader><CardContent className="grid gap-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" /><Skeleton className="h-4 w-2/3" /></CardContent></Card>)}</div>
  if (!notes.length) return <Empty className="min-h-64 border border-dashed bg-card"><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{emptyTitle}</EmptyTitle><EmptyDescription>{emptyBody}</EmptyDescription></EmptyHeader></Empty>
  return <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{notes.map(note => <Card key={note.id} className="group flex min-h-56 flex-col transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
    <CardHeader className="flex-row items-start justify-between gap-3"><CardTitle className="line-clamp-2 text-base leading-6">{note.title}</CardTitle><Badge variant={note.scope === 'team' ? 'default' : 'secondary'} className="shrink-0"><Users className="size-3" />{note.scope === 'team' ? note.teamName || (zh ? '团队' : 'Team') : (zh ? '个人' : 'Personal')}</Badge></CardHeader>
    <CardContent className="flex-1"><p className="line-clamp-4 text-sm leading-6 text-muted-foreground">{note.content || copy.notes.noContent}</p>{failedRecording(note) ? <Badge variant="destructive" className="mt-3">{zh ? '处理失败，可打开重试' : 'Processing failed'}</Badge> : null}</CardContent>
    <CardFooter className="justify-between border-t pt-4"><span className="text-xs text-muted-foreground">{formatDate(note.updatedAt || note.createdAt)}</span><Button variant="ghost" size="sm" onClick={() => onOpen(note)}>{zh ? '打开' : 'Open'}</Button></CardFooter>
  </Card>)}</div>
}
