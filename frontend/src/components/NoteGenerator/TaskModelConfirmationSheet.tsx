import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { apiJson, ApiError } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'

type Selection = { mode: 'cloud'; server_url: string; asr_model: string; llm_model: string }
type RecoveryContext = {
  task_id: string
  source: { title: string; type: string }
  requires_confirmation: boolean
  can_confirm?: boolean
  selection?: Selection
}

export function TaskModelConfirmationSheet({ taskId, owner, onClose, onAccepted, onQuery }: {
  taskId: string; owner: string
  onClose: () => void; onAccepted: () => void; onQuery: () => void
}) {
  const [context, setContext] = useState<RecoveryContext | null>(null)
  const frozen = useRef<RecoveryContext | null>(null)
  const [phase, setPhase] = useState<'loading' | 'ready' | 'posting' | 'failed' | 'unknown'>('loading')
  const [message, setMessage] = useState('')
  const epoch = useRef(0)
  const locked = useRef(false)
  const valid = (version: number) => version === epoch.current && useAuthStore.getState().user?.id === owner

  const load = async () => {
    if (locked.current) return
    const version = ++epoch.current
    setPhase('loading'); setMessage('')
    try {
      const value = await apiJson<RecoveryContext>(`/api/task/${encodeURIComponent(taskId)}/model-confirmation`, { cache: 'no-store' })
      if (!valid(version)) return
      if (value.task_id !== taskId || !value.source?.title?.trim() || typeof value.requires_confirmation !== 'boolean') throw new Error('恢复信息与原任务不一致，请返回核验原任务。')
      if (!value.requires_confirmation) throw new Error('原任务已有冻结模型，请返回查询原任务状态；此处不能更换模型。')
      const selection = value.selection
      if (!selection || selection.mode !== 'cloud' || !selection.asr_model?.trim() || !selection.llm_model?.trim() || typeof value.can_confirm !== 'boolean') throw new Error('缺少具体服务或模型，无法确认恢复。')
      const origin = new URL(selection.server_url)
      if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password || origin.search || origin.hash) throw new Error('模型服务来源无效，请返回核验。')
      if (frozen.current && JSON.stringify(frozen.current.selection) !== JSON.stringify(selection)) throw new Error('模型设置已变化，原确认选择已保留。请返回后重新打开确认，不会静默换模型。')
      frozen.current = value
      setContext(value); setPhase('ready')
      if (!value.can_confirm) setMessage('所选模型当前不可用，已保留原选择。请刷新状态后重试。')
    } catch (cause) {
      if (valid(version)) { setPhase('failed'); setMessage(cause instanceof Error ? cause.message : '无法读取恢复信息，请重试。') }
    }
  }

  useEffect(() => {
    frozen.current = null
    setContext(null)
    void load()
    return () => { epoch.current++ }
    // This sheet is mounted for one immutable owner/task; parent replaces it on navigation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, owner])

  const confirm = async () => {
    const value = frozen.current
    if (locked.current || phase !== 'ready' || !value?.can_confirm || !value.selection || useAuthStore.getState().user?.id !== owner) return
    locked.current = true
    const version = ++epoch.current
    setPhase('posting'); setMessage('')
    try {
      const result = await apiJson<{ task_id: string; status: string }>(`/api/task/${encodeURIComponent(taskId)}/retry`, {
        method: 'POST', body: JSON.stringify({ confirmed: true, ...value.selection }),
      })
      if (!valid(version)) return
      if (result.task_id !== taskId || !['uploaded', 'pending', 'preparing', 'transcribing', 'summarizing', 'screenshots', 'success'].includes(result.status)) throw new Error('恢复是否排队尚未确认，请查询原任务状态。')
      onAccepted()
    } catch (cause) {
      if (!valid(version)) return
      const knownFailure = cause instanceof ApiError && cause.status >= 400 && cause.status < 500
      setPhase(knownFailure ? 'failed' : 'unknown')
      setMessage(knownFailure ? cause.message : '恢复结果尚未确认。原任务与模型选择已保留，请先查询原任务状态，不重复提交确认。')
    } finally { locked.current = false }
  }

  const posting = phase === 'posting'
  return <Sheet open onOpenChange={open => { if (!open && !posting) onClose() }}>
    <SheetContent className="overflow-y-auto sm:max-w-md" onEscapeKeyDown={event => { if (posting) event.preventDefault() }} onInteractOutside={event => { if (posting) event.preventDefault() }}>
      <SheetHeader><SheetTitle>确认原任务的恢复模型</SheetTitle><SheetDescription>原任务未保留模型快照。请确认以下当前选择；确认后固定到原任务，继续使用原来源。</SheetDescription></SheetHeader>
      <div className="grid gap-5 py-6">
        {phase === 'loading' && <p role="status" className="text-sm text-muted-foreground">正在核验原来源与模型…</p>}
        {context && <>
          <dl className="grid gap-4 text-sm"><div><dt className="text-muted-foreground">原来源</dt><dd className="mt-1 break-words">{context.source.title}</dd></div><div><dt className="text-muted-foreground">模型服务</dt><dd className="mt-1 break-all">{context.selection?.server_url}</dd></div></dl>
          {(['asr_model', 'llm_model'] as const).map(key => <div key={key} className="grid gap-2"><Label htmlFor={`retry-${key}`}>{key === 'asr_model' ? '语音转写模型' : '内容总结模型'}</Label><Select disabled value={context.selection![key]}><SelectTrigger id={`retry-${key}`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value={context.selection![key]}>{context.selection![key]}</SelectItem></SelectContent></Select></div>)}
          <p className="text-xs leading-5 text-muted-foreground">此处不切换模型。需要其他模型时，请保留原件并另建确认的生成操作。</p>
        </>}
        {message && <Alert variant="destructive"><AlertDescription>{message}</AlertDescription></Alert>}
        {posting && <p role="status" className="text-sm text-muted-foreground">正在保存模型确认并恢复原任务…</p>}
        <div className="flex flex-wrap gap-3">
          {phase !== 'unknown' && <Button disabled={phase !== 'ready' || !context?.can_confirm} onClick={() => void confirm()}>{posting ? '正在恢复…' : '确认模型并恢复原任务'}</Button>}
          {phase !== 'posting' && phase !== 'unknown' && <Button variant="outline" disabled={phase === 'loading'} onClick={() => void load()}>{context ? '刷新模型状态' : '重试读取'}</Button>}
          {phase === 'unknown' && <Button onClick={onQuery}>查询原任务状态</Button>}
          <Button variant="ghost" disabled={posting} onClick={onClose}>返回原任务</Button>
        </div>
      </div>
    </SheetContent>
  </Sheet>
}
