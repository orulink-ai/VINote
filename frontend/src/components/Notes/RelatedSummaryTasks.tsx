import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiJson } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { getWorkspaceLabel, useTeamStore } from '@/stores/teamStore'
import { useNoteLibraryStore } from '@/stores/noteLibraryStore'
import { Button } from '@/components/ui/button'
import { depthLabels, presentationLabels } from '@/lib/summaryPresentation'

type Child = { task_id: string; operation_id: string; content_depth?: string | null; presentation?: string | null }
type Children = { canonical_task_id: string; items: Child[] }
type Task = { task_id: string; status: string; updated_at?: string | null; result?: { task_id?: string; title?: string; markdown?: string } }
type DisplayChild = Child & { status: string; updatedAt?: string }
const timeValue = (value?: string) => { const time = value ? Date.parse(value) : NaN; return Number.isFinite(time) ? time : null }
const modeLabel = (item: Child) => {
  const depth = item.content_depth && Object.prototype.hasOwnProperty.call(depthLabels, item.content_depth) ? depthLabels[item.content_depth as keyof typeof depthLabels] : ''
  const presentation = item.presentation && Object.prototype.hasOwnProperty.call(presentationLabels, item.presentation) ? presentationLabels[item.presentation as keyof typeof presentationLabels] : ''
  return [depth, presentation].filter(Boolean).join(' · ') || '模式未记录'
}
const validId = (id: string) => /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(id)
const statusLabel = (status: string) => ({ success: '已完成', failed: '处理失败', error: '处理失败', not_found: '任务未找到', unavailable: '状态无法读取', uploaded: '已接收', preparing: '准备中', downloading: '读取来源中', transcribing: '转写中', summarizing: '整理中', processing: '处理中', pending: '等待处理', queued: '等待处理' } as Record<string, string>)[status] || '状态未识别'

export function RelatedSummaryTasks({ canonical, owner, sourceType, returnTo }: { canonical: string; owner: string; sourceType?: string; returnTo: string }) {
  const navigate = useNavigate()
  const workspace = useTeamStore(s => s.currentWorkspace)
  const teams = useTeamStore(s => s.teams)
  const [items, setItems] = useState<DisplayChild[]>([])
  const [message, setMessage] = useState('正在读取关联生成记录…')
  const [confirm, setConfirm] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const active = useRef(true)
  const context = useRef('')
  context.current = JSON.stringify([owner, canonical, workspace, returnTo])
  useEffect(() => { setConfirm(null) }, [workspace.scope, workspace.scope === 'team' ? workspace.teamId : ''])
  useEffect(() => {
    active.current = true
    let cancelled = false
    setItems([]); setMessage('正在读取关联生成记录…'); setConfirm(null)
    const read = async () => {
      try {
        const data = await apiJson<Children>(`/api/task/${encodeURIComponent(canonical)}/summary-children`)
        if (data.canonical_task_id !== canonical || !Array.isArray(data.items)) throw new Error()
        const children = data.items.filter(item => validId(item.task_id) && validId(item.operation_id))
        const result = await Promise.all(children.map(async item => {
          try { const task = await apiJson<Task>(`/api/task/${encodeURIComponent(item.task_id)}`); return task.task_id === item.task_id && typeof task.status === 'string' ? { ...item, status: task.status, updatedAt: typeof task.updated_at === 'string' && timeValue(task.updated_at) !== null ? task.updated_at : undefined } : { ...item, status: 'unavailable' } }
          catch { return { ...item, status: 'unavailable' } }
        }))
        result.sort((a, b) => (timeValue('updatedAt' in b ? b.updatedAt : undefined) ?? -Infinity) - (timeValue('updatedAt' in a ? a.updatedAt : undefined) ?? -Infinity))
        if (!cancelled && useAuthStore.getState().user?.id === owner) { setItems(result); setMessage(result.length ? '' : '暂无关联的纪要生成记录。') }
      } catch { if (!cancelled && useAuthStore.getState().user?.id === owner) setMessage('关联记录暂时无法读取，请稍后重新打开原件。') }
    }
    void read()
    return () => { cancelled = true; active.current = false }
  }, [canonical, owner])
  const recover = async (child: Child) => {
    if (lock.current || !owner) return
    lock.current = true; setBusy(true); setMessage('正在核验任务与保存位置…')
    const binding = context.current
    const same = () => active.current && context.current === binding && useAuthStore.getState().user?.id === owner && JSON.stringify(useTeamStore.getState().currentWorkspace) === JSON.stringify(workspace)
    try {
      const links = await apiJson<Children>(`/api/task/${encodeURIComponent(canonical)}/summary-children`)
      if (!same()) return
      if (links.canonical_task_id !== canonical || !Array.isArray(links.items) || !links.items.some(item => item.task_id === child.task_id && item.operation_id === child.operation_id)) throw new Error('任务与原件的关联无法确认。')
      const task = await apiJson<Task>(`/api/task/${encodeURIComponent(child.task_id)}`)
      if (!same()) return
      if (task.task_id !== child.task_id || task.status !== 'success' || !task.result?.title?.trim() || !task.result.markdown?.trim() || task.result.task_id && task.result.task_id !== child.task_id) throw new Error('任务结果尚未完整确认。')
      const query = workspace.scope === 'team' ? `?scope=team&team_id=${encodeURIComponent(workspace.teamId)}` : '?scope=personal'
      const notes = await apiJson<{ id: string; task_id: string | null }[]>(`/api/notes${query}`)
      if (!same()) return
      if (!Array.isArray(notes)) throw new Error('无法核验目标空间中的已有内容。')
      const existing = notes.find(note => note.task_id === child.task_id)
      const note = existing || await useNoteLibraryStore.getState().saveNote(task.result.title, task.result.markdown, undefined, child.task_id, workspace, ['video', 'meeting_video'].includes(sourceType || '') ? 'meeting_video' : 'meeting_recording')
      if (!same()) return
      if (!note?.id) throw new Error('保存结果尚未确认，请重新读取目标空间后再操作。')
      navigate(`/note/${encodeURIComponent(note.id)}`, { state: { returnTo } })
    } catch (error) { if (same()) setMessage(error instanceof Error ? error.message : '核验失败，请稍后重试。') }
    finally { lock.current = false; if (active.current) setBusy(false) }
  }
  const newestKnown = items.find(item => timeValue(item.updatedAt) !== null)
  const summary = items.length ? items.some(item => timeValue(item.updatedAt) === null) ? '部分记录时间不可用，无法确定最近状态' : `最近状态 · ${statusLabel(newestKnown!.status)}` : ''
  return <section aria-label="关联纪要生成记录" className="grid gap-2">
    <details>
      <summary className="cursor-pointer text-sm font-medium">处理记录 · {items.length}次{summary && <span className="ml-2 font-normal text-muted-foreground">{summary}</span>}</summary>
      <div className="mt-3 grid gap-3">{items.map(item => <div key={item.task_id} className="grid gap-2 border-t pt-3 text-sm">
        <p>{item.updatedAt ? `状态更新于 ${new Date(item.updatedAt).toLocaleString()}` : '更新时间未记录'} · {modeLabel(item)} · {statusLabel(item.status)}</p>
        <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => navigate(`/generate?meeting=1&task=${encodeURIComponent(item.task_id)}`, { state: { returnTo, readOnlyTask: { id: item.task_id, owner, meeting: true } } })}>查看处理记录</Button>{item.status === 'success' && <Button variant="outline" disabled={busy} onClick={() => { setConfirm(item.task_id); setMessage('') }}>恢复保存</Button>}</div>
        <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">技术信息</summary><p className="mt-2 break-all">任务编号：{item.task_id}</p><p className="break-all">操作编号：{item.operation_id}</p></details>
        {confirm === item.task_id && <div className="grid gap-2"><p>将此已完成结果保存到：{getWorkspaceLabel(workspace, teams, '个人空间')}。保存前会检查是否已有该任务的笔记。</p><div className="flex gap-2"><Button disabled={busy} onClick={() => void recover(item)}>{busy ? '正在核验…' : '确认保存到此空间'}</Button><Button variant="ghost" disabled={busy} onClick={() => setConfirm(null)}>取消</Button></div></div>}
      </div>)}</div>
    </details>
    {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
  </section>
}
