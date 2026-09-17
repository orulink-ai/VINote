import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Clock3, FileText, Mic, Play } from 'lucide-react'
import { listPendingMeetings, type PendingMeeting } from '../lib/audioStorage'
import { useAuthStore } from '../stores/authStore'
import { useI18n } from '../lib/i18n'
import { useNoteLibraryStore, type NoteRecord } from '../stores/noteLibraryStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Separator } from '@/components/ui/separator'
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
  const recent = notes.slice(0, 6)
  const formatDate = (value: string) => new Intl.DateTimeFormat(zh ? 'zh-CN' : 'en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))

  return <div className="mx-auto flex max-w-[1260px] flex-col gap-7 px-6 py-8 lg:px-10">
    <header className="animate-in fade-in slide-in-from-bottom-2 duration-300">
      <p className="text-sm text-muted-foreground">{workspaceLabel}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">{zh ? '继续上次的工作' : 'Continue where you left off'}</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{zh ? '查看最近更新、处理已保存的录制，或从左侧进入会议和资料采集。' : 'Review recent updates, process saved recordings, or use Capture to start new work.'}</p>
    </header>
    <Separator />
    <section className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_320px]">
      <section className="min-w-0 animate-in fade-in slide-in-from-bottom-2 duration-500">
        <header className="flex items-center justify-between gap-4 pb-3"><div><h2 className="font-semibold">{zh ? '最近更新' : 'Recent updates'}</h2><p className="mt-1 text-sm text-muted-foreground">{zh ? '会议纪要和笔记的最新改动' : 'Latest changes across meetings and notes'}</p></div>{recent.length ? <Button variant="ghost" size="sm" onClick={() => navigate('/notes')}>{zh ? '打开笔记库' : 'Open library'}<ArrowRight data-icon="inline-end" /></Button> : null}</header>
        {loading ? <div className="flex flex-col gap-3 py-4">{[1,2,3].map(item => <Skeleton key={item} className="h-16 w-full" />)}</div> : recent.length ? <div className="divide-y border-y">{recent.map((note, index) => { const Icon=sourceIcon(note); return <Button key={note.id} variant="ghost" onClick={() => navigate(`/note/${note.id}`)} style={{ animationDelay: `${index * 45}ms` }} className="group h-auto w-full animate-in justify-start rounded-none px-3 py-4 text-left fade-in slide-in-from-bottom-1 duration-300 hover:bg-muted/60"><span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted"><Icon className="text-muted-foreground transition-transform duration-200 group-hover:scale-105" /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{note.title}</span><span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground"><Clock3 />{formatDate(note.updatedAt)} · {note.scope === 'team' ? note.teamName : (zh ? '个人空间' : 'Personal')}</span></span><Badge variant="secondary">{note.sourceType?.includes('meeting') ? (zh ? '会议' : 'Meeting') : (zh ? '笔记' : 'Note')}</Badge><ArrowRight className="text-muted-foreground transition-transform duration-200 group-hover:translate-x-1" /></Button>})}</div> : <Empty className="min-h-72 border-y"><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{zh ? '这里会显示最近更新' : 'Recent updates appear here'}</EmptyTitle><EmptyDescription>{zh ? '从左侧选择“会议”或“链接与文件”开始采集内容。' : 'Choose Meetings or Links & files from Capture to begin.'}</EmptyDescription></EmptyHeader></Empty>}
      </section>
      <aside className="animate-in fade-in slide-in-from-right-2 duration-500"><div className="flex items-center justify-between pb-3"><div><h2 className="font-semibold">{zh ? '待处理录制' : 'Saved recordings'}</h2><p className="mt-1 text-sm text-muted-foreground">{zh ? '录制完成后从这里继续' : 'Continue after recording'}</p></div><Badge variant="secondary">{pending.length}</Badge></div>
        {pending.length ? <div className="overflow-hidden rounded-lg border bg-card">{pending.slice(0,4).map(item => <Button key={item.id} variant="ghost" onClick={() => navigate('/meetings')} className="group h-auto w-full justify-start rounded-none border-b px-4 py-3 text-left transition-all duration-200 last:border-b-0 hover:bg-muted/60"><Mic className="transition-transform duration-200 group-hover:scale-105" /><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{item.options.title || (zh ? '未命名会议' : 'Untitled meeting')}</span><span className="text-xs text-muted-foreground">{Math.max(1,Math.round(item.elapsedSeconds/60))} {zh ? '分钟' : 'min'}</span></span><ArrowRight className="text-muted-foreground transition-transform duration-200 group-hover:translate-x-1" /></Button>)}</div> : <Empty className="min-h-64 border border-dashed"><EmptyHeader><EmptyTitle>{zh ? '暂无待处理录制' : 'No saved recordings'}</EmptyTitle><EmptyDescription>{zh ? '会议页结束录制后会保存在这里。' : 'Finished recordings from Meetings appear here.'}</EmptyDescription></EmptyHeader></Empty>}
      </aside>
    </section>
  </div>
}
