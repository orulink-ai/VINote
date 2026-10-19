import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore, type ModelSourceConfig } from '@/stores/appModeStore'
import type { WorkspaceSelection } from '@/stores/teamStore'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'

type SummaryContext = { parent_task_id: string; context_revision: string; source: { version: string; type: string }; can_regenerate_summary: boolean }
type Receipt = { operation_id: string; task_id: string; state: string; source_type?: string }
type Props = { noteId: string; taskId: string; workspace: WorkspaceSelection; returnTo: string; disabled?: boolean }

export function RegenerateMeetingSummary(props: Props) {
  const owner = useAuthStore(s => s.user?.id)
  const config = useAppModeStore(s => s.config)
  const location = useLocation()
  // A changed route/account/Origin remounts the confirmation, including ABA changes.
  return <SummaryAction key={JSON.stringify([owner, config?.mode, config?.server_url, location.key, location.pathname, location.search, props.noteId, props.taskId])} {...props} owner={owner} />
}

function SummaryAction({ noteId, taskId, workspace, returnTo, disabled, owner }: Props & { owner?: string }) {
  const navigate = useNavigate()
  const [confirmation, setConfirmation] = useState<{ context: SummaryContext; config: ModelSourceConfig } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const lock = useRef(false)
  const mounted = useRef(true)
  const origin = useAppModeStore.getState().config?.server_url
  const active = () => mounted.current && owner === useAuthStore.getState().user?.id && origin === useAppModeStore.getState().config?.server_url
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const pointerKey = `vinote:summary-operation:${owner}:${origin || ''}:${noteId}:${taskId}`
  const openOperation = (operationId: string) => navigate('/generate?' + new URLSearchParams({ meeting: '1', operation: operationId }), { state: { returnTo } })

  async function prepare() {
    if (!owner || disabled || lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      const previous = localStorage.getItem(pointerKey)
      if (previous) { openOperation(previous); return }
      const [context, currentConfig] = await Promise.all([
        apiJson<SummaryContext>(`/api/task/${encodeURIComponent(taskId)}/summary-context`),
        apiJson<ModelSourceConfig>('/api/vilab/config'),
      ])
      if (!active()) return
      if (context.parent_task_id !== taskId || context.can_regenerate_summary !== true || !/^[0-9a-f]{64}$/.test(context.context_revision) || !/^[0-9a-f]{64}$/.test(context.source?.version)) throw new Error('当前没有可核验的纪要来源。')
      if (!currentConfig.configured || currentConfig.mode !== 'cloud' || !currentConfig.llm_model?.trim() || currentConfig.server_url !== origin) throw new Error('请先在模型设置中明确选择当前云端总结模型，再重新打开此操作。')
      setConfirmation({ context, config: currentConfig })
    } catch (cause) {
      if (active()) setError(cause instanceof ApiError && cause.status === 409 ? '当前资料不可重新生成纪要，请保留原文件与已有处理记录。' : cause instanceof Error ? cause.message : '无法核验来源，请稍后重试。')
    } finally { lock.current = false; if (active()) setBusy(false) }
  }

  async function confirm() {
    if (!confirmation || !owner || disabled || lock.current || !active()) return
    const selected = useAppModeStore.getState()
    if (selected.saving || selected.config?.mode !== 'cloud' || selected.config.llm_model !== confirmation.config.llm_model) {
      setConfirmation(null); setError('模型选择已变化，请重新核验并确认。'); return
    }
    lock.current = true; setBusy(true); setError('')
    const operationId = crypto.randomUUID()
    const key = `vinote:source-receipt:${owner}:${operationId}`
    const pending = { operationId, createdAt: new Date().toISOString(), submissionState: 'unknown', workspace, meeting: true, mode: 'file', independentGeneration: true, summaryOnly: true, summaryNoteId: noteId, parentTaskId: taskId, sourceType: confirmation.context.source.type, summaryContext: confirmation.context, modelName: confirmation.config.llm_model, origin }
    let protectedOperation = false
    try {
      const existing = localStorage.getItem(pointerKey)
      if (existing) { openOperation(existing); return }
      const serialized = JSON.stringify(pending)
      localStorage.setItem(key, serialized)
      localStorage.setItem(pointerKey, operationId)
      if (localStorage.getItem(key) !== serialized || localStorage.getItem(pointerKey) !== operationId) throw new Error('无法保存本次操作记录，未开始处理。')
      protectedOperation = true
      if (!active()) return
      const result = await apiJson<Receipt>(`/api/task/${encodeURIComponent(taskId)}/regenerate-summary`, { method: 'POST', body: JSON.stringify({ operation_id: operationId, confirmed: true, context_revision: confirmation.context.context_revision, source_version: confirmation.context.source.version, model_name: confirmation.config.llm_model }) })
      if (!active()) return
      if (result.operation_id !== operationId || !result.task_id || result.task_id === taskId || !['reserved', 'accepted'].includes(result.state)) throw new Error('提交结果尚未确认，请查询本次操作。')
      localStorage.setItem(key, JSON.stringify({ ...pending, id: result.task_id, submissionState: result.state }))
      openOperation(operationId)
    } catch (cause) {
      if (!active()) return
      if (protectedOperation) openOperation(operationId)
      else setError(cause instanceof Error ? cause.message : '无法保护操作记录，未开始处理。')
    } finally { lock.current = false; if (active()) { setBusy(false); setConfirmation(null) } }
  }

  return <div className="grid min-w-0 gap-2">
    <Button variant="outline" size="sm" disabled={disabled || busy || !owner} onClick={() => void prepare()}>{busy ? '正在核验…' : '重新生成纪要'}</Button>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Dialog open={!!confirmation} onOpenChange={open => { if (!open && !busy) setConfirmation(null) }}>
      <DialogContent><DialogHeader><DialogTitle>确认重新生成纪要</DialogTitle><DialogDescription>复用已有逐字稿及可用的说话人、视频资料，不重新转录。新纪要独立保存，原纪要和原文件保留；总结可能产生模型费用。</DialogDescription></DialogHeader>
        <p className="break-all text-sm">总结模型：{confirmation?.config.llm_model}</p>
        <p className="text-sm">来源类型：{confirmation?.context.source.type === 'video' ? '视频' : confirmation?.context.source.type === 'audio' ? '音频' : '已保留资料'}。仅使用已核验的证据，不将缺失内容当作静音。</p>
        <Button disabled={busy || disabled} onClick={() => void confirm()}>{busy ? '正在提交…' : '确认并重新生成纪要'}</Button>
        <Button variant="outline" disabled={busy} onClick={() => setConfirmation(null)}>取消</Button>
      </DialogContent>
    </Dialog>
  </div>
}
