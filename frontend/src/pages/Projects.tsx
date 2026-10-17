import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Folder, ArrowRight } from 'lucide-react'
import { useLibraryNotes } from '@/hooks/useLibraryNotes'
import { useNoteLibraryStore } from '@/stores/noteLibraryStore'
import { useTeamStore } from '@/stores/teamStore'
import { PageHeading } from '@/components/Layout/PageHeading'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

/** Projects are views over saved content; opening one never copies its notes. */
export function Projects() {
  const notes = useLibraryNotes()
  const { loading, error, loadNotes } = useNoteLibraryStore()
  const { currentWorkspace } = useTeamStore()
  useEffect(() => { void loadNotes(currentWorkspace) }, [loadNotes, currentWorkspace])
  const projects = [...new Set(notes.filter(n => !n.archived).map(n => n.project).filter((p): p is string => !!p))].sort()
  return <div className="workspace-page">
    <PageHeading title="项目" description="按项目查看同一份内容。项目与标签在内容详情中管理。" />
    {error && <div role="alert" className="flex items-center justify-between gap-4 rounded-lg border p-4"><span>{error}</span><Button variant="outline" disabled={loading} onClick={() => void loadNotes(currentWorkspace)}>重新加载</Button></div>}
    {loading && !notes.length ? <Skeleton className="h-40" /> : <section aria-label="项目列表" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {projects.map(project => <Link key={project} to={`/notes?project=${encodeURIComponent(project)}`} className="object-card group flex flex-col gap-5 rounded-xl border p-5 focus-visible:outline focus-visible:outline-ring">
        <Folder className="size-5 text-muted-foreground" aria-hidden="true" /><h2 className="text-base font-medium break-words">{project}</h2>
        <span className="flex items-center justify-between text-sm text-muted-foreground"><span>{notes.filter(n => !n.archived && n.project === project).length} 份内容</span><ArrowRight className="size-4" aria-hidden="true" /></span>
      </Link>)}
    </section>}
    {!loading && !projects.length && !error && <section className="empty-region"><h2>还没有项目</h2><p>打开一份内容，在详情里设置项目，即可在这里集中查看。</p><Button asChild variant="outline"><Link to="/notes">选择内容</Link></Button></section>}
  </div>
}
