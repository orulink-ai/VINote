import { useEffect, useState } from 'react'
import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { deliveryStatus, openExternal, type Delivery } from '@/lib/feishu'
import { Button } from '@/components/ui/button'
import { feishuFormattingMessage } from '@/lib/feishuFormatting'

/** Read-only document reference. Publishing remains an explicit delivery action. */
export function FeishuDocumentFooter({ noteId, revision }: { noteId: string; revision?: string }) {
  const [job, setJob] = useState<Delivery | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    setBusy(true); setError(''); setJob(null)
    void deliveryStatus(noteId).then(next => { if (active) setJob(next) }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '飞书状态读取失败') }).finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [noteId, revision, attempt])
  return <div className="mx-6 mb-6 border-t py-4 lg:mx-8">
    <div className="flex items-center justify-between gap-3 text-xs"><span className="flex items-center gap-2 text-muted-foreground"><FileText className="size-3.5" />{busy ? '正在读取飞书文档…' : job?.document_url ? `飞书文档 · ${job.status === 'completed' ? '已交付' : job.status === 'failed' ? '交付需处理' : '交付中'}` : '飞书 · 尚未交付'}</span>{job?.document_url ? <Button size="sm" variant="ghost" onClick={() => void openExternal(job.document_url).catch(cause => setError(cause.message))}>查看文档 ↗</Button> : <Link to="/settings/feishu" className="underline underline-offset-4">集成设置</Link>}</div>
    {!busy && job && <p role="status" className="mt-2 text-xs text-muted-foreground">{feishuFormattingMessage(job.formatting, job.status)}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}<Button variant="ghost" size="sm" disabled={busy} onClick={() => setAttempt(value => value + 1)}>重新读取</Button></p>}
    {job?.error && <p className="mt-2 text-xs text-destructive">{job.error} · 可在右上方交付中重试失败步骤。</p>}
  </div>
}
