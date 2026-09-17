import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, CalendarDays, Clock3, FileText, FileUp, Link, Mic, Play, Sparkles, Users } from 'lucide-react'
import { listPendingMeetings, type PendingMeeting } from '../lib/audioStorage'
import { useAuthStore } from '../stores/authStore'
import { useI18n } from '../lib/i18n'
import { useNoteLibraryStore, type NoteRecord } from '../stores/noteLibraryStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
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
  const meetingCount = notes.filter(note => note.sourceType?.includes('meeting')).length
  const formatDate = (value: string) => new Intl.DateTimeFormat(zh ? 'zh-CN' : 'en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
  const stats = [
    { icon: Mic, value: meetingCount, label: zh ? '会议纪要' : 'Meeting notes', action: '/meetings' },
    { icon: FileText, value: notes.length, label: zh ? '空间笔记' : 'Workspace notes', action: '/notes' },
    { icon: Users, value: teams.length, label: zh ? '协作团队' : 'Teams', action: '/team' },
  ]
  return <div className="mx-auto flex max-w-[1440px] flex-col gap-6 px-5 py-6 lg:px-8">
    <section className="flex flex-col gap-4 border-b pb-6 lg:flex-row lg:items-end lg:justify-between">
      <div className="flex flex-col gap-2"><Badge variant="outline" className="w-fit"><span className="mr-2 size-2 rounded-full bg-emerald-500" />{workspaceLabel}</Badge><h1 className="text-2xl font-semibold tracking-tight lg:text-3xl">{zh ? '今天要整理什么？' : 'What are you working on today?'}</h1><p className="text-sm text-muted-foreground">{zh ? '录下讨论，导入资料，把零散信息变成可以继续工作的知识。' : 'Capture discussions and turn scattered material into useful knowledge.'}</p></div>
      <div className="flex flex-wrap gap-2"><Button onClick={() => navigate('/meetings')}><Mic />{zh ? '开始会议' : 'Start meeting'}</Button><Button variant="outline" onClick={() => navigate('/generate?mode=url')}><Link />{zh ? '整理链接' : 'Organize link'}</Button><Button variant="outline" onClick={() => navigate('/generate?mode=file')}><FileUp />{zh ? '导入文件' : 'Import file'}</Button></div>
    </section>
    <section className="grid gap-6 xl:grid-cols-[minmax(0,1.65fr)_minmax(320px,.75fr)]">
      <div className="flex min-w-0 flex-col gap-6">
        <Card className="overflow-hidden"><CardHeader className="flex-row items-center justify-between"><div><CardTitle>{zh ? '继续工作' : 'Continue working'}</CardTitle><CardDescription>{zh ? '最近更新的笔记与会议纪要' : 'Recently updated notes and meeting minutes'}</CardDescription></div><Button variant="ghost" size="sm" onClick={() => navigate('/notes')}>{zh ? '全部笔记' : 'All notes'}<ArrowRight /></Button></CardHeader><CardContent className="p-0">
          {loading ? <div className="flex flex-col gap-3 p-5">{[1,2,3].map(item => <Skeleton key={item} className="h-14 w-full" />)}</div> : recent.length ? <div className="divide-y">{recent.map(note => { const Icon=sourceIcon(note); return <Button key={note.id} variant="ghost" onClick={() => navigate(`/note/${note.id}`)} className="h-auto w-full justify-start rounded-none px-5 py-4 text-left"><span className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background"><Icon className="size-4 text-muted-foreground" /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{note.title}</span><span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground"><Clock3 className="size-3" />{formatDate(note.updatedAt)} · {note.scope === 'team' ? note.teamName : (zh ? '个人空间' : 'Personal')}</span></span><Badge variant="secondary">{note.sourceType?.includes('meeting') ? (zh ? '会议' : 'Meeting') : (zh ? '笔记' : 'Note')}</Badge><ArrowRight className="size-4 text-muted-foreground" /></Button>})}</div> : <Empty className="py-12"><EmptyHeader><EmptyMedia variant="icon"><FileText /></EmptyMedia><EmptyTitle>{zh ? '还没有笔记' : 'No notes yet'}</EmptyTitle><EmptyDescription>{zh ? '从一次会议、链接或文件开始。' : 'Start with a meeting, link or file.'}</EmptyDescription></EmptyHeader><EmptyContent><Button onClick={() => navigate('/generate')}>{zh ? '整理第一条资料' : 'Create first note'}</Button></EmptyContent></Empty>}
        </CardContent></Card>
        <div className="grid gap-3 md:grid-cols-3">{stats.map(item => <Card key={item.label} className="transition-shadow hover:shadow-md"><CardContent className="flex items-center gap-4 p-4"><span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary"><item.icon className="size-5" /></span><span className="min-w-0 flex-1"><span className="block text-xl font-semibold">{item.value}</span><span className="text-xs text-muted-foreground">{item.label}</span></span><Button variant="ghost" size="icon" onClick={() => navigate(item.action)}><ArrowRight /></Button></CardContent></Card>)}</div>
      </div>
      <aside className="flex flex-col gap-4">
        <Card className="border-primary/20 bg-primary text-primary-foreground"><CardHeader><span className="mb-3 flex size-10 items-center justify-center rounded-lg bg-primary-foreground/10"><Sparkles className="size-5" /></span><CardTitle>{zh ? '会议工作台' : 'Meeting studio'}</CardTitle><CardDescription className="text-primary-foreground/70">{zh ? '录制时展示设备和保存状态；停止后生成说话人逐字稿、决策与待办。' : 'See capture status while recording, then generate speaker transcript, decisions and actions.'}</CardDescription></CardHeader><CardFooter><Button variant="secondary" className="w-full" onClick={() => navigate('/meetings')}>{zh ? '进入会议工作台' : 'Open meeting studio'}<ArrowRight /></Button></CardFooter></Card>
        <Card><CardHeader className="flex-row items-center justify-between"><div><CardTitle className="flex items-center gap-2 text-base"><CalendarDays className="size-4" />{zh ? '待处理录制' : 'Saved recordings'}</CardTitle><CardDescription>{zh ? '已安全保存到本机' : 'Safely stored locally'}</CardDescription></div><Badge variant="secondary">{pending.length}</Badge></CardHeader><CardContent className="p-0">{pending.length ? <div className="divide-y">{pending.slice(0,3).map(item => <Button key={item.id} variant="ghost" onClick={() => navigate('/meetings')} className="h-auto w-full justify-start rounded-none p-4 text-left"><span className="flex size-9 items-center justify-center rounded-full bg-destructive/10"><Mic className="size-4 text-destructive" /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{item.options.title || (zh ? '未命名会议' : 'Untitled meeting')}</span><span className="text-xs text-muted-foreground">{Math.max(1,Math.round(item.elapsedSeconds/60))} {zh ? '分钟 · 等待生成' : 'min · Ready to process'}</span></span></Button>)}</div> : <Empty className="py-8"><EmptyHeader><EmptyTitle>{zh ? '暂无待处理录制' : 'Nothing waiting'}</EmptyTitle><EmptyDescription>{zh ? '停止会议后会先保存在这里。' : 'Finished recordings appear here.'}</EmptyDescription></EmptyHeader></Empty>}</CardContent></Card>
      </aside>
    </section>
  </div>
}
