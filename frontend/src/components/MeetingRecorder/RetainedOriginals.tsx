import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FileAudio, ArrowRight } from 'lucide-react'
import { apiJson } from '@/lib/api'
import type { LibraryNote } from '@/hooks/useLibraryNotes'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

type Original = { available: boolean; filename: string; size_bytes: number }

/** Verify retained files; a synced text note alone never implies local media. */
export function RetainedOriginals({ notes, excludedIds, owner }: { notes: LibraryNote[]; excludedIds: string[]; owner?: string }) {
  const candidates = [...new Map(notes.filter(n => n.taskId && (!n.workspaceKey || n.localId) && !excludedIds.includes(n.localId || n.id)).map(n => [n.taskId, { id: n.localId || n.id, title: n.title }])).values()]
  const signature = JSON.stringify(candidates)
  const [files, setFiles] = useState<Array<{ id: string; title: string; info: Original }>>([])
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    setFiles([]); setError(''); setLoading(true)
    const load = async () => {
      const retained = []
      let failed = 0
      // Sequential metadata-only requests; never pre-load audio into memory.
      for (const candidate of JSON.parse(signature) as typeof candidates) {
        if (!active) return
        try { const info = await apiJson<Original>(`/api/notes/${encodeURIComponent(candidate.id)}/recording`, { signal: controller.signal }); if (info.available) retained.push({ ...candidate, info }) }
        catch { if (!active) return; failed++ }
      }
      if (active) { setFiles(retained); setLoading(false); if (failed) setError(`${failed} 个原件状态暂未读取，已确认的文件仍可打开。`) }
    }
    void load()
    return () => { active = false; controller.abort() }
  }, [signature, owner, attempt])
  if (!candidates.length) return null
  return <section aria-label="已整理的会议与笔记" className="border-t pt-6">
    <h2 className="text-base font-medium">已生成纪要</h2><p className="mt-2 text-xs text-muted-foreground">原始录音或视频保存在当前电脑，打开会议可播放并查看纪要。</p>
    {loading && <Skeleton className="mt-4 h-16" />}
    {files.map(file => <Link key={file.id} to={`/note/${encodeURIComponent(file.id)}`} state={{ returnTo: '/meetings' }} className="flex items-center gap-3 border-b py-4 focus-visible:outline focus-visible:outline-ring"><FileAudio aria-hidden="true" className="size-5 shrink-0 text-muted-foreground" /><span className="min-w-0 flex-1"><span className="block truncate text-sm">{file.title}</span><span className="mt-1 block text-xs text-muted-foreground">{file.info.filename} · {(file.info.size_bytes / 1048576).toFixed(1)} MB</span></span><ArrowRight aria-hidden="true" className="size-4" /></Link>)}
    {error && <div role="alert" className="flex items-center justify-between gap-4 py-4 text-sm"><span>{error}</span><Button variant="outline" disabled={loading} onClick={() => setAttempt(n => n + 1)}>重新核验</Button></div>}
    {!loading && !error && !files.length && <p className="py-4 text-sm text-muted-foreground">没有已核验的保留文件。内容库中的文字与版本仍可使用。</p>}
  </section>
}
