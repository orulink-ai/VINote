import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Clock3, FileText, FileUp, Link, Mic, Play } from 'lucide-react'
import { listPendingMeetings, type PendingMeeting } from '../lib/audioStorage'
import { useAuthStore } from '../stores/authStore'
import { useI18n } from '../lib/i18n'
import { useNoteLibraryStore, type NoteRecord } from '../stores/noteLibraryStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Skeleton } from '@/components/ui/skeleton'

function sourceIcon(note: NoteRecord) {
  if (note.sourceType?.includes('meeting')) return Mic
  if (note.sourceType === 'video' || note.sourceType === 'audio') return Play
  return FileText
}

export function Home() {
  const navigate = useNavigate()
  const userId = useAuthStore(state => state.user?.id)
  const { locale } = useI18n()
  const { notes, loading, loadNotes } = useNoteLibraryStore()
  const { currentWorkspace, teams } = useTeamStore()
  const [pending, setPending] = useState<PendingMeeting[]>([])
  const zh = locale.startsWith('zh')
  const workspaceLabel = getWorkspaceLabel(currentWorkspace, teams, zh ? '个人空间' : 'Personal workspace')
  useEffect(() => { void loadNotes(currentWorkspace) }, [currentWorkspace, loadNotes])
  useEffect(() => { if (userId) void listPendingMeetings(userId).then(setPending).catch(() => setPending([])) }, [userId])
  const recent = notes.slice(0, 5)
  const formatDate = (value: string) => new Intl.DateTimeFormat(zh ? 'zh-CN' : 'en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
  return <div className="mx-auto flex max-w-[1320px] flex-col gap-8 px-6 py-8 lg:px-10">
    <section className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
      <div className="flex flex-col gap-2"><p className="text-sm text-muted-foreground">{workspaceLabel}</p><h1 className="text-3xl font-semibold tracking-tight">{zh ? '开始新的工作' : 'Start new work'}</h1><p className="text-sm text-muted-foreground">{zh ? '记录会议，或把链接和文件整理成笔记。' : 'Record a meeting or organize links and files into notes.'}</p></div>
      <div className="flex flex-wrap gap-2"><Button onClick={() => navigate('/meetings')}><Mic />{zh ? '开始会议' : 'Start meeting'}</Button><Button variant="outline" onClick={() => navigate('/generate?mode=url')}><Link />{zh ? '整理链接' : 'Organize link'}</Button><Button variant="outline" onClick={() => navigate('/generate?mode=file')}><FileUp />{zh ? '导入文件' : 'Import file'}</Button></div>
    </section>
    <section className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_320px]">
      <section className="overflow-hidden border-t"><header className="flex items-center justify-between py-4"><div><h2 className="font-semibold">{zh ? '最近内容' : 'Recent'}</h2><p className="mt-1 text-sm text-muted-foreground">{zh ? '继续编辑最近的会议和笔记' : 'Continue your recent meetings and notes'}</p></div><Button variant="ghost" size="sm" onClick={() => navigate('/notes')}>{zh ? '查看全部' : 'View all'}<ArrowRight /></Button></header>
          {loading ? <div className="flex flex-col gap-3 p-5">{[1,2,3].map(item => <Skeleton key={item} className="h-14 w-full" />)}</div> : recent.length ? <div className="divide-y">{recent.map(note => { const Icon=sourceIcon(note); return <Button key={note.id} variant="ghost" onClick={() => navigate(`/note/${note.id}`)} className="h-auto w-full justify-start rounded-none px-5 py-4 text-left"><span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background"><Icon className="size-4 text-muted-foreground" /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{note.title}</span><span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground"><Clock3 className="size-3" />{formatDate(note.updatedAt)} · {note.scope === 'team' ? note.teamName : (zh ? '个人空间' : 'Personal')}</span></span><Badge variant="secondary">{note.sourceType?.includes('meeting') ? (zh ? '会议' : 'Meeting') : (zh ? '笔记' : 'Note')}</Badge><ArrowRight className="size-4 text-muted-foreground" /></Button>})}</div> : <Empty className="py-12"><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{zh ? '还没有笔记' : 'No notes yet'}</EmptyTitle><EmptyDescription>{zh ? '从一次会议、链接或文件开始。' : 'Start with a meeting, link or file.'}</EmptyDescription></EmptyHeader><EmptyContent><Button onClick={() => navigate('/generate')}>{zh ? '整理第一条资料' : 'Create first note'}</Button></EmptyContent></Empty>}
      </section>
      <aside className="flex flex-col gap-3"><div className="flex items-center justify-between"><h2 className="text-sm font-medium">{zh ? '本地录制' : 'Local recordings'}</h2><Badge variant="secondary">{pending.length}</Badge></div>
        {pending.length ? <div className="overflow-hidden rounded-lg border bg-card">{pending.slice(0,4).map(item => <Button key={item.id} variant="ghost" onClick={() => navigate('/meetings')} className="h-auto w-full justify-start rounded-none border-b px-4 py-3 text-left last:border-b-0"><Mic /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{item.options.title || (zh ? '未命名会议' : 'Untitled meeting')}</span><span className="text-xs text-muted-foreground">{Math.max(1,Math.round(item.elapsedSeconds/60))} {zh ? '分钟' : 'min'}</span></span></Button>)}</div> : <Empty className="min-h-48 border border-dashed"><EmptyHeader><EmptyTitle>{zh ? '没有待处理录制' : 'No saved recordings'}</EmptyTitle><EmptyDescription>{zh ? '结束录制后会保存在这里。' : 'Finished recordings appear here.'}</EmptyDescription></EmptyHeader></Empty>}
      </aside>
    </section>
  </div>
}
