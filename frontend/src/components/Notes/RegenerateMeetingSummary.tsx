import { useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore, type ModelSourceConfig } from '@/stores/appModeStore'
import type { WorkspaceSelection } from '@/stores/teamStore'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field, FieldGroup, FieldLabel, FieldDescription } from '@/components/ui/field'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { NativeSelect } from '@/components/ui/native-select'
import { modelEligibility, type ModelEligibilityInput } from '@/lib/modelEligibility'
import { depthLabels, presentationLabels, type ContentDepth, type Presentation, type SummaryContext } from '@/lib/summaryPresentation'

type Receipt = { operation_id: string; task_id: string; state: string; source_type?: string }
type FailedOperation = { operationId: string; taskId: string; record: string }
type OperationState = { kind: 'protected' | 'saved' } | { kind: 'failed'; failed: FailedOperation }
type SummaryTask = { task_id: string; status: string; operation_id?: string; failed_stage?: string; error_code?: string; retryable?: boolean }
type SummaryModel = ModelEligibilityInput & { id: string; modelType: string; name?: string }
type Props = { noteId?: string; taskId: string; workspace: WorkspaceSelection; returnTo: string; disabled?: boolean }
const connectionId = (config: ModelSourceConfig | null) => (config as (ModelSourceConfig & { connection_id?: string }) | null)?.connection_id

export function summaryOperationKey(owner: string, origin: string | undefined, taskId: string, noteId?: string) {
  return `vinote:summary-operation:${owner}:${origin || ''}:${noteId || 'task'}:${taskId}`
}

export function RegenerateMeetingSummary(props: Props) {
  const owner = useAuthStore(s => s.user?.id)
  const config = useAppModeStore(s => s.config)
  const location = useLocation()
  // A changed route/account/Origin remounts the confirmation, including ABA changes.
  return <SummaryAction key={JSON.stringify([owner, config?.mode, config?.server_url, connectionId(config), config?.connection_revision, location.key, location.pathname, location.search, location.hash, props.noteId, props.taskId, props.returnTo, props.workspace])} {...props} owner={owner} />
}

function SummaryAction({ noteId, taskId, workspace, returnTo, disabled, owner }: Props & { owner?: string }) {
  const navigate = useNavigate()
  const [confirmation, setConfirmation] = useState<{ context: SummaryContext; config: ModelSourceConfig; models: SummaryModel[]; replaces?: FailedOperation } | null>(null)
  const [failedOperation, setFailedOperation] = useState<FailedOperation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [contentDepth, setContentDepth] = useState<ContentDepth>('concise')
  const [presentation, setPresentation] = useState<Presentation>('text')
  const [modelName, setModelName] = useState('')
  const lock = useRef(false)
  const mounted = useRef(true)
  const opener = useRef<HTMLButtonElement | null>(null)
  const origin = useAppModeStore.getState().config?.server_url
  const active = () => mounted.current && owner === useAuthStore.getState().user?.id && origin === useAppModeStore.getState().config?.server_url
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const pointerKey = summaryOperationKey(owner || '', origin, taskId, noteId)
  const openOperation = (operationId: string) => navigate('/generate?' + new URLSearchParams({ meeting: '1', operation: operationId }), { state: { returnTo } })
  function restoreOpener(event: Event) {
    // Override DialogContent's open-time focus capture: async preparation may
    // have disabled/blurred our button before the dialog was ever mounted.
    event.preventDefault()
    const target = opener.current
    opener.current = null
    if (!active() || !target?.isConnected || target.disabled ||
        document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')) return
    target.focus({ preventScroll: true })
  }

  async function inspectOperation(operation: string): Promise<OperationState> {
    try {
      const receipt = await apiJson<Receipt>(`/api/source-requests/${encodeURIComponent(operation)}`, { cache: 'no-store' })
      if (!active() || receipt.operation_id !== operation || receipt.state !== 'accepted' || !receipt.task_id) return { kind: 'protected' }
      const task = await apiJson<SummaryTask>(`/api/task/${encodeURIComponent(receipt.task_id)}`, { cache: 'no-store' })
      if (!active() || task.task_id !== receipt.task_id || task.operation_id !== undefined && task.operation_id !== operation) return { kind: 'protected' }
      if (task.status === 'failed' && task.failed_stage === 'summarizing' && task.retryable === false &&
          !['summary_result_unconfirmed', 'unknown_result', 'unknown_error', 'asr_incomplete_result'].includes(task.error_code || '')) {
        const record = localStorage.getItem(`vinote:source-receipt:${owner}:${operation}`)
        const saved = JSON.parse(record || 'null')
        // The pointer alone cannot bind an arbitrary failed task to this parent.
        if (record && saved?.operationId === operation && saved.id === receipt.task_id && receipt.task_id !== taskId &&
            saved.parentTaskId === taskId && saved.summaryNoteId === noteId && saved.summaryOnly === true &&
            saved.meeting === true && saved.submissionState === 'accepted' && saved.origin === origin &&
            saved.workspace?.scope === workspace.scope && (workspace.scope !== 'team' || saved.workspace.teamId === workspace.teamId)) {
          return { kind: 'failed', failed: { operationId: operation, taskId: receipt.task_id, record } }
        }
        return { kind: 'protected' }
      }
      if (task.status !== 'success') return { kind: 'protected' }
      const query = workspace.scope === 'team' ? `?scope=team&team_id=${encodeURIComponent(workspace.teamId)}` : '?scope=personal'
      const notes = await apiJson<{ id: string; task_id?: string }[]>(`/api/notes${query}`)
      return { kind: active() && Array.isArray(notes) && notes.some(note => !!note.id && note.task_id === receipt.task_id) ? 'saved' : 'protected' }
    } catch { return { kind: 'protected' } }  // Unread/unknown/unsaved operations remain protected.
  }

  const sameFailure = (a: FailedOperation, b: FailedOperation) => a.operationId === b.operationId && a.taskId === b.taskId && a.record === b.record

  async function prepare(replaces?: FailedOperation, trigger?: HTMLButtonElement) {
    if (!owner || disabled || lock.current) return
    if (trigger) opener.current = trigger
    lock.current = true; setBusy(true); setError('')
    try {
      const previous = localStorage.getItem(pointerKey)
      if (replaces && previous !== replaces.operationId) { openOperation(previous || replaces.operationId); return }
      if (previous) {
        const state = await inspectOperation(previous)
        if (!active()) return
        if (localStorage.getItem(pointerKey) !== previous) { openOperation(localStorage.getItem(pointerKey) || previous); return }
        if (state.kind === 'failed') {
          if (!replaces) { setFailedOperation(state.failed); return }
          if (!sameFailure(state.failed, replaces)) { openOperation(previous); return }
        } else if (state.kind === 'saved' && !replaces) {
          localStorage.removeItem(pointerKey)
          setFailedOperation(null)
        } else { openOperation(previous); return }
      }
      const [context, currentConfig, catalog] = await Promise.all([
        apiJson<SummaryContext>(`/api/task/${encodeURIComponent(taskId)}/summary-context`),
        apiJson<ModelSourceConfig>('/api/vilab/config'),
        apiJson<SummaryModel[]>('/api/vilab/models', { cache: 'no-store' }),
      ])
      if (!active()) return
      if (context.parent_task_id !== taskId || context.can_regenerate_summary !== true || !/^[0-9a-f]{64}$/.test(context.context_revision) || !/^[0-9a-f]{64}$/.test(context.source?.version)) throw new Error('当前没有可核验的纪要来源。')
      if (!currentConfig.configured || currentConfig.mode !== 'cloud' || currentConfig.server_url !== origin || connectionId(currentConfig) !== connectionId(useAppModeStore.getState().config) || currentConfig.connection_revision !== useAppModeStore.getState().config?.connection_revision) throw new Error('模型连接已变化或不可用，请重新核验。')
      if (!Array.isArray(catalog)) throw new Error('无法核验当前连接的总结模型目录，未开始生成。')
      const models = catalog.filter(model => model.modelType === 'llm' && modelEligibility(model) === 'available')
      if (!models.length) throw new Error('当前连接没有可用的总结模型，未开始生成。')
      setConfirmation({ context, config: currentConfig, models, replaces })
      setModelName(models.some(model => model.id === currentConfig.llm_model) ? currentConfig.llm_model : '')
      setContentDepth('concise'); setPresentation('text')
    } catch (cause) {
      if (active()) setError(cause instanceof ApiError && cause.status === 409 ? '当前资料不可重新生成纪要，请保留原文件与已有处理记录。' : cause instanceof Error ? cause.message : '无法核验来源，请稍后重试。')
    } finally { lock.current = false; if (active()) setBusy(false) }
  }

  async function confirm() {
    if (!confirmation || !owner || disabled || lock.current || !active()) return
    if (!confirmation.models.some(model => model.id === modelName && modelEligibility(model) === 'available')) return
    if (confirmation.context.presentation_options?.[presentation]?.available === false ||
        !confirmation.context.presentation_options && !['text', 'html'].includes(presentation)) return
    const selected = useAppModeStore.getState()
    if (selected.saving || selected.config?.mode !== 'cloud' || selected.config.llm_model !== confirmation.config.llm_model || connectionId(selected.config) !== connectionId(confirmation.config)) {
      setConfirmation(null); setError('模型选择已变化，请重新核验并确认。'); return
    }
    lock.current = true; setBusy(true); setError('')
    const operationId = crypto.randomUUID()
    const key = `vinote:source-receipt:${owner}:${operationId}`
    const pending = { operationId, createdAt: new Date().toISOString(), submissionState: 'unknown', workspace, meeting: true, mode: 'file', independentGeneration: true, summaryOnly: true, summaryNoteId: noteId, parentTaskId: taskId, sourceType: confirmation.context.source.type, sourceTitle: typeof confirmation.context.source.title === 'string' ? confirmation.context.source.title.trim() || undefined : undefined, summaryContext: confirmation.context, modelName, contentDepth, presentation, origin }
    let protectedOperation = false
    try {
      const existing = localStorage.getItem(pointerKey)
      if (confirmation.replaces) {
        const previous = confirmation.replaces
        if (existing !== previous.operationId) { openOperation(existing || previous.operationId); return }
        const state = await inspectOperation(existing)
        if (!active()) return
        if (localStorage.getItem(pointerKey) !== existing || state.kind !== 'failed' || !sameFailure(state.failed, previous)) {
          openOperation(localStorage.getItem(pointerKey) || previous.operationId); return
        }
      } else if (existing) { openOperation(existing); return }
      const serialized = JSON.stringify(pending)
      localStorage.setItem(key, serialized)
      localStorage.setItem(pointerKey, operationId)
      if (localStorage.getItem(key) !== serialized || localStorage.getItem(pointerKey) !== operationId) throw new Error('无法保存本次操作记录，未开始处理。')
      protectedOperation = true
      if (!active()) return
      const result = await apiJson<Receipt>(`/api/task/${encodeURIComponent(taskId)}/regenerate-summary`, { method: 'POST', body: JSON.stringify({ operation_id: operationId, confirmed: true, context_revision: confirmation.context.context_revision, source_version: confirmation.context.source.version, model_name: modelName, content_depth: contentDepth, presentation, ...(connectionId(confirmation.config) ? { connection_id: connectionId(confirmation.config) } : {}) }) })
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
    <Button variant="outline" size="sm" disabled={disabled || busy || !owner} onClick={event => void prepare(undefined, event.currentTarget)}>{busy ? '正在核验…' : noteId ? '重新生成纪要' : '仅重新生成纪要'}</Button>
    {failedOperation && <div className="grid gap-2">
      <p role="status" className="text-sm text-muted-foreground">上次总结已确认失败。失败记录会保留，可另选模型和形式生成新版本，不重试原操作。</p>
      <Button variant="outline" size="sm" disabled={disabled || busy || !owner} onClick={event => void prepare(failedOperation, event.currentTarget)}>保留失败记录，另建新版本</Button>
      <Button variant="ghost" size="sm" disabled={busy} onClick={() => openOperation(failedOperation.operationId)}>查看失败记录</Button>
    </div>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Dialog open={!!confirmation} onOpenChange={open => { if (!open && !busy) setConfirmation(null) }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] overflow-y-auto overscroll-contain" closeLabel="关闭" onCloseAutoFocus={restoreOpener}><DialogHeader><DialogTitle>{noteId ? '确认重新生成纪要' : '确认仅重新生成纪要'}</DialogTitle><DialogDescription>使用原始 ASR 转写、独立说话人及可用画面证据重新生成，不以上一版纪要为输入，不重新转录。新纪要独立保存，已有记录和原文件保留；总结可能产生模型费用。</DialogDescription></DialogHeader>
        <FieldGroup>
          <Field><FieldLabel htmlFor="summary-model-choice">本次总结模型</FieldLabel>
            <NativeSelect id="summary-model-choice" value={modelName} disabled={busy} aria-describedby="summary-model-help" onChange={event => setModelName(event.target.value)}>
              <option value="" disabled>请选择本次总结模型</option>
              {confirmation?.models.map(model => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
            </NativeSelect>
            <FieldDescription id="summary-model-help">仅用于本次所选形式，不修改全局模型偏好。草稿与事实复核使用同一模型。</FieldDescription>
          </Field>
          <Field><FieldLabel id="summary-depth-label">内容详略</FieldLabel>
            <ToggleGroup type="single" variant="outline" value={contentDepth} disabled={busy} aria-labelledby="summary-depth-label" onValueChange={value => { if (value) setContentDepth(value as ContentDepth) }} className="justify-start flex-wrap">
              {(Object.keys(depthLabels) as ContentDepth[]).map(value => <ToggleGroupItem key={value} value={value}>{depthLabels[value]}</ToggleGroupItem>)}
            </ToggleGroup>
          </Field>
          <Field><FieldLabel id="summary-presentation-label">呈现形式</FieldLabel>
            <ToggleGroup type="single" variant="outline" value={presentation} disabled={busy} aria-labelledby="summary-presentation-label" aria-describedby="summary-presentation-help" onValueChange={value => { if (value) setPresentation(value as Presentation) }} className="justify-start flex-wrap">
              {(Object.keys(presentationLabels) as Presentation[]).map(value => {
                const available = confirmation?.context.presentation_options?.[value]?.available ?? ['text', 'html'].includes(value)
                return <ToggleGroupItem key={value} value={value} disabled={!available} title={confirmation?.context.presentation_options?.[value]?.reason || undefined}>{presentationLabels[value]}{!available ? '（不可用）' : ''}</ToggleGroupItem>
              })}
            </ToggleGroup>
            <FieldDescription id="summary-presentation-help">图文只使用已核验的原视频截图。漫画与信息图尚未接通真实图像生成，不会自动更换模型。每次生成独立保存，同形式可保留多个版本。</FieldDescription>
          </Field>
        </FieldGroup>
        <p className="text-sm">来源类型：{['video', 'meeting_video'].includes(confirmation?.context.source.type || '') ? '视频' : ['audio', 'meeting_audio', 'meeting_recording'].includes(confirmation?.context.source.type || '') ? '音频' : '已保留资料'}。仅使用已核验的证据，不将缺失内容当作静音。</p>
        <Button disabled={busy || disabled || !modelName} onClick={() => void confirm()}>{busy ? '正在提交…' : noteId ? '确认并重新生成纪要' : '确认，仅重新总结'}</Button>
        <Button variant="outline" disabled={busy} onClick={() => setConfirmation(null)}>取消</Button>
      </DialogContent>
    </Dialog>
  </div>
}
