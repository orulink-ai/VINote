import { useEffect, useRef, useState } from 'react'
import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { deliveryStatus, deliveryById, readAutomaticDelivery, checkAutomaticDelivery, openExternal, type Delivery, type AutomaticDeliveryLocal } from '@/lib/feishu'
import { useAuthStore } from '@/stores/authStore'
import { publishScope } from '@/lib/feishuPublishReceipt'
import { Button } from '@/components/ui/button'
import { feishuFormattingMessage } from '@/lib/feishuFormatting'

const MAX_READ_ROUNDS = 12
const READ_INTERVAL_MS = 3000
const needsRefresh = (state: AutomaticDeliveryLocal | null, receipt: Delivery | null) => !!state && (
  state.status === 'queued' || state.status === 'submitting' ||
  (state.status === 'accepted' && (!receipt || receipt.status === 'queued' || receipt.status === 'processing'))
)

/** Read-only document reference. Publishing remains an explicit delivery action. */
export function FeishuDocumentFooter({ noteId, revision }: { noteId: string; revision?: string }) {
  const owner = useAuthStore(state => state.user?.id)
  const [job, setJob] = useState<Delivery | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const [automatic, setAutomatic] = useState<AutomaticDeliveryLocal | null>(null)
  const [automaticError, setAutomaticError] = useState('')
  const [checking, setChecking] = useState(false)
  const [pollExhausted, setPollExhausted] = useState(false)
  const sequence = useRef(0), checkPending = useRef(false)
  const readSequence = useRef(0)
  const timer = useRef<number>()
  const budget = useRef({ key: '', remaining: MAX_READ_ROUNDS })
  const scopeKey = JSON.stringify([owner, noteId, revision])
  const exactClaim = useRef<{ key: string; jobId: string; receipt: Delivery | null; guard: () => void } | null>(null)
  const claimJob = (jobId: string, guard: () => void) => {
    if (exactClaim.current?.key !== scopeKey || exactClaim.current.jobId !== jobId) {
      setJob(null)
      exactClaim.current = { key: scopeKey, jobId, receipt: null, guard }
    }
    return exactClaim.current
  }
  const renderedRequest = sequence.current, renderedScope = owner ? publishScope(owner) : null
  useEffect(() => {
    let active = true
    const request = ++sequence.current, scope = owner ? publishScope(owner) : null
    const current = () => { try { scope?.(); return active && !!scope && sequence.current === request } catch { return false } }
    const key = JSON.stringify([owner, noteId, revision])
    // Manual attempt changes do not replenish this scope's automatic-read budget.
    if (budget.current.key !== key) budget.current = { key, remaining: MAX_READ_ROUNDS }
    // A refresh changes the request epoch, not the already confirmed source.
    if (exactClaim.current?.key !== key) exactClaim.current = null
    else { try { exactClaim.current.guard() } catch { exactClaim.current = null } }
    const genericCurrent = () => current() && exactClaim.current?.key !== key
    setBusy(true); setError(''); setJob(exactClaim.current?.receipt || null)
    setAutomatic(null); setAutomaticError(''); setChecking(false); setPollExhausted(false); checkPending.current = false
    if (!owner) { setBusy(false); return () => { active = false } }
    if (!exactClaim.current) void deliveryStatus(noteId).then(next => { if (genericCurrent()) setJob(next) }).catch(cause => { if (genericCurrent()) setError(cause instanceof Error ? cause.message : '飞书状态读取失败') }).finally(() => { if (current()) setBusy(false) })
    const readRound = async () => {
      if (!current()) return
      const round = ++readSequence.current
      const readCurrent = () => current() && round === readSequence.current
      if (budget.current.remaining > 0) --budget.current.remaining
      try {
        const next = await readAutomaticDelivery(noteId)
        if (!readCurrent()) return
        setAutomatic(next)
        let receipt: Delivery | null = null
        const jobId = next?.job_id || exactClaim.current?.jobId
        if (jobId) {
          const claim = claimJob(jobId, scope!)
          receipt = await deliveryById(jobId)
          if (!readCurrent()) return
          if (receipt.id !== jobId) throw new Error('交付回执不属于原任务，请重新核验')
          claim.receipt = receipt
          setJob(receipt); setError(''); setBusy(false)
        }
        if (needsRefresh(next, receipt)) {
          if (budget.current.remaining > 0) timer.current = window.setTimeout(() => {
            timer.current = undefined
            if (readCurrent()) void readRound()
          }, READ_INTERVAL_MS)
          else setPollExhausted(true)
        }
      } catch (cause) { if (readCurrent()) { setAutomaticError(cause instanceof Error ? cause.message : '自动交付状态读取失败'); setBusy(false) } }
    }
    void readRound()
    return () => { active = false; ++sequence.current; ++readSequence.current; window.clearTimeout(timer.current); timer.current = undefined }
  }, [owner, noteId, revision, attempt])
  const check = async () => {
    try { if (!renderedScope || renderedRequest !== sequence.current) return; renderedScope() } catch { return }
    if (!owner || checkPending.current || automatic?.can_check !== true) return
    const request = sequence.current, scope = publishScope(owner)
    const current = () => { try { scope(); return request === sequence.current } catch { return false } }
    ++readSequence.current; window.clearTimeout(timer.current); timer.current = undefined
    checkPending.current = true; setChecking(true); setAutomaticError('')
    try {
      const next = await checkAutomaticDelivery(noteId)
      if (!current()) return
      setAutomatic(next)
      let receipt: Delivery | null = null
      if (next?.job_id) { const claim = claimJob(next.job_id, scope); receipt = await deliveryById(next.job_id); if (receipt.id !== next.job_id) throw new Error('交付回执不属于原任务，请重新核验'); if (current()) { claim.receipt = receipt; setJob(receipt); setError(''); setBusy(false) } }
      if (current()) {
        if (needsRefresh(next, receipt) && budget.current.remaining > 0) setAttempt(value => value + 1)
        else setPollExhausted(needsRefresh(next, receipt))
      }
    } catch (cause) { if (current()) setAutomaticError(cause instanceof Error ? cause.message : '交付结果核验失败，请稍后再核验') }
    finally { if (current()) { checkPending.current = false; setChecking(false) } }
  }
  return <div className="mx-6 mb-6 border-t py-4 lg:mx-8">
    <div className="flex items-center justify-between gap-3 text-xs"><span className="flex items-center gap-2 text-muted-foreground"><FileText className="size-3.5" />{busy ? '正在读取飞书文档…' : job?.document_url ? `飞书文档 · ${job.status === 'completed' ? '已交付' : job.status === 'failed' ? '交付需处理' : '交付中'}` : '飞书 · 尚未交付'}</span>{job?.document_url ? <Button size="sm" variant="ghost" onClick={() => void openExternal(job.document_url).catch(cause => setError(cause.message))}>查看文档 ↗</Button> : <Link to="/settings/feishu" className="underline underline-offset-4">集成设置</Link>}</div>
    {!busy && job && <p role="status" className="mt-2 text-xs text-muted-foreground">{feishuFormattingMessage(job.formatting, job.status)}</p>}
    {automatic && <div className="mt-2 flex flex-col gap-2 text-xs text-muted-foreground">
      <p role="status">{automatic.status === 'queued' ? '纪要已保存，正在等待自动交付；尚未交给服务的任务需要应用保持运行。' : automatic.status === 'submitting' || automatic.status === 'unknown' ? '自动交付结果尚未确认，请先核验；确认前不会再次发送。' : automatic.status === 'accepted' ? '自动交付已由服务接收，可查看文档交付进度。' : automatic.status === 'cancelled' ? '自动交付已停止，原纪要继续保留。' : '自动交付失败，原纪要继续保留；可通过右上方交付手动发布。'}</p>
      {automatic.error && <p role="alert" className="text-destructive">{automatic.error}</p>}
      {['unknown', 'submitting'].includes(automatic.status) && automatic.can_check === true && <Button variant="outline" size="sm" disabled={checking} onClick={() => void check()}>{checking ? '正在核验…' : '核验交付结果'}</Button>}
    </div>}
    {pollExhausted && <p role="status" className="mt-2 text-xs text-muted-foreground">已暂停自动刷新，可手动查看最新交付进度。<Button variant="outline" size="sm" onClick={() => setAttempt(value => value + 1)}>刷新交付状态</Button></p>}
    {automaticError && <p role="alert" className="mt-2 text-xs text-destructive">{automaticError}<Button variant="ghost" size="sm" onClick={() => setAttempt(value => value + 1)}>重新读取交付状态</Button></p>}
    {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}<Button variant="ghost" size="sm" disabled={busy} onClick={() => setAttempt(value => value + 1)}>重新读取</Button></p>}
    {job?.error && <p className="mt-2 text-xs text-destructive">{job.error} · 可在右上方交付中重试失败步骤。</p>}
  </div>
}
