import { useEffect, useMemo, useState } from 'react'
import { Grid2X2, List, Plus, Search } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useI18n } from '../lib/i18n'
import { NoteGrid } from '../components/Notes/NoteGrid'
import { useNoteLibraryStore } from '../stores/noteLibraryStore'
import { getWorkspaceLabel, useTeamStore } from '../stores/teamStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { Card, CardContent } from '@/components/ui/card'

type Filter = 'all' | 'meeting' | 'media' | 'text'
export function Notes() {
  const navigate = useNavigate()
  const { copy, locale, formatDate } = useI18n()
  const { notes, loading, loadNotes } = useNoteLibraryStore()
  const { currentWorkspace, teams } = useTeamStore()
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const zh = locale.startsWith('zh')
  const workspaceLabel = getWorkspaceLabel(currentWorkspace, teams, zh ? '个人空间' : 'Personal workspace')
  useEffect(() => { void loadNotes(currentWorkspace) }, [currentWorkspace, loadNotes])
  const filtered = useMemo(() => notes.filter(note => {
    const source = note.sourceType || ''
    const matchesType = filter === 'all' || (filter === 'meeting' && source.startsWith('meeting')) || (filter === 'media' && ['video', 'audio'].some(type => source.includes(type))) || (filter === 'text' && !source.startsWith('meeting') && !['video', 'audio'].some(type => source.includes(type)))
    const needle = query.trim().toLowerCase()
    return matchesType && (!needle || `${note.title} ${note.content || ''}`.toLowerCase().includes(needle))
  }), [filter, notes, query])
  const filters: Array<[Filter, string]> = [['all', zh ? '全部' : 'All'], ['meeting', zh ? '会议' : 'Meetings'], ['media', zh ? '音视频' : 'Media'], ['text', zh ? '文章与文本' : 'Text']]

  return <div className="mx-auto flex max-w-7xl flex-col gap-6 p-6 lg:p-10">
    <header className="flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[.18em] text-primary">{workspaceLabel}</p><h1 className="mt-2 text-3xl font-bold tracking-tight">{copy.notes.title}</h1><p className="mt-2 text-sm text-muted-foreground">{zh ? '统一管理会议、链接、文件和团队共享笔记。' : 'Manage meetings, links, files and shared notes.'}</p></div><Button onClick={() => navigate('/generate')}><Plus />{zh ? '新建笔记' : 'New note'}</Button></header>
    <div className="flex flex-col gap-3 rounded-2xl border bg-card p-3 shadow-sm lg:flex-row lg:items-center">
      <div className="relative flex-1"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"/><Input value={query} onChange={event => setQuery(event.target.value)} placeholder={zh ? '搜索标题和内容' : 'Search title and content'} className="border-0 bg-muted pl-9 shadow-none"/></div>
      <ToggleGroup type="single" value={filter} onValueChange={value => value && setFilter(value as Filter)}>{filters.map(([value,label]) => <ToggleGroupItem key={value} value={value}>{label}</ToggleGroupItem>)}</ToggleGroup>
      <div className="flex gap-1"><Button variant={view==='grid'?'secondary':'ghost'} size="icon" onClick={() => setView('grid')}><Grid2X2/></Button><Button variant={view==='list'?'secondary':'ghost'} size="icon" onClick={() => setView('list')}><List/></Button></div>
    </div>
    <div className="flex items-center justify-between text-sm text-muted-foreground"><span>{zh ? `${filtered.length} 条笔记` : `${filtered.length} notes`}</span>{filter!=='all'?<Badge variant="secondary">{filters.find(item=>item[0]===filter)?.[1]}</Badge>:null}</div>
    {view === 'grid' ? <NoteGrid notes={filtered} loading={loading} emptyTitle={copy.notes.emptyTitle} emptyBody={copy.notes.emptyBody} onOpen={note => navigate(`/note/${note.id}`)} /> : <Card><CardContent className="divide-y p-0">{filtered.map(note => <Button key={note.id} variant="ghost" onClick={() => navigate(`/note/${note.id}`)} className="h-auto w-full justify-between rounded-none px-5 py-4 text-left"><span className="min-w-0"><span className="block truncate font-medium">{note.title}</span><span className="mt-1 block truncate text-sm font-normal text-muted-foreground">{note.content || copy.notes.noContent}</span></span><span className="shrink-0 text-xs font-normal text-muted-foreground">{formatDate(note.updatedAt || note.createdAt)}</span></Button>)}</CardContent></Card>}
  </div>
}
