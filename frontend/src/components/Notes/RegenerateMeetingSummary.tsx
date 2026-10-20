import { useLayoutEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { apiJson, ApiError } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import type { WorkspaceSelection } from '@/stores/teamStore'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field, FieldGroup, FieldLabel, FieldDescription } from '@/components/ui/field'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { NativeSelect } from '@/components/ui/native-select'
import { Checkbox } from '@/components/ui/checkbox'
import { modelEligibility, type ModelEligibilityInput } from '@/lib/modelEligibility'
import { depthLabels, presentationLabels } from '@/lib/summaryPresentation'
import { meetingVersionOperationKey, isMeetingVersionReceipt, type MeetingVersionContext, type MeetingVersionModels, type ContentDepth, type Presentation } from '@/lib/meetingVersion'

type Receipt = { operation_id: string; task_id: string; state: string; source_type?: string }
type FailedOperation = { operationId: string; taskId: string; record: string }
type OperationState = { kind: 'protected' | 'saved' } | { kind: 'failed'; failed: FailedOperation }
type SummaryTask = { task_id: string; status: string; operation_id?: string; failed_stage?: string; error_code?: string; retryable?: boolean }
type SummaryModel = ModelEligibilityInput & { id: string; modelType: string; name?: string }
type Props = { noteId?: string; taskId: string; workspace: WorkspaceSelection; returnTo: string; disabled?: boolean }

export function summaryOperationKey(owner: string, origin: string | undefined, taskId: string, noteId?: string) {
  return `vinote:summary-operation:${owner}:${origin || ''}:${noteId || 'task'}:${taskId}`
}

export function RegenerateMeetingSummary(props: Props) {
  const owner = useAuthStore(s => s.user?.id)
  const location = useLocation()
  return <SummaryAction key={JSON.stringify([owner, location.key, location.pathname, location.search, location.hash, props.noteId, props.taskId, props.returnTo, props.workspace])} {...props} owner={owner} />
}

function SummaryAction({ noteId, taskId, workspace, returnTo, disabled, owner }: Props & { owner?: string }) {
  const navigate = useNavigate()
  const [confirmation, setConfirmation] = useState<{ context: MeetingVersionContext; replaces?: FailedOperation } | null>(null)
  const [catalog, setCatalog] = useState<MeetingVersionModels | null>(null)
  const [loadingModels, setLoadingModels] = useState(false)
  const [llmMode, setLlmMode] = useState<'inherit' | 'select'>('inherit')
  const [asrMode, setAsrMode] = useState<'reuse' | 'fresh'>('reuse')
  const [asrModel, setAsrModel] = useState('')
  const [asrConsent, setAsrConsent] = useState(false)
  const [failedOperation, setFailedOperation] = useState<FailedOperation | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [contentDepth, setContentDepth] = useState<ContentDepth>('concise')
  const [presentation, setPresentation] = useState<Presentation>('text')
  const [modelName, setModelName] = useState('')
  const lock = useRef(false)
  const mounted = useRef(true)
  const opener = useRef<HTMLButtonElement | null>(null)
  const legacyOrigin = useAppModeStore.getState().config?.server_url
  const active = () => mounted.current && owner === useAuthStore.getState().user?.id
  useLayoutEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const pointerKey = meetingVersionOperationKey(owner || '', taskId, noteId)
  const legacyPointerKey = summaryOperationKey(owner || '', legacyOrigin, taskId, noteId)
  const pointerReadKey = useRef(pointerKey)
  const catalogSequence = useRef(0)
  const models: SummaryModel[] = catalog?.models.filter(model => model.modelType === 'llm' && modelEligibility(model) === 'available') || []
  const presentationOptions = asrMode === 'fresh' ? confirmation?.context.asr_modes.fresh.presentation_options : confirmation?.context.presentation_options
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
            saved.meeting === true && saved.submissionState === 'accepted' && (isMeetingVersionReceipt(saved, owner) || saved.origin === legacyOrigin) &&
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
      const readKey = localStorage.getItem(pointerKey) ? pointerKey : localStorage.getItem(legacyPointerKey) ? legacyPointerKey : pointerKey
      pointerReadKey.current = readKey
      const previous = localStorage.getItem(readKey)
      if (replaces && previous !== replaces.operationId) { openOperation(previous || replaces.operationId); return }
      if (previous) {
        const state = await inspectOperation(previous)
        if (!active()) return
        if (localStorage.getItem(readKey) !== previous) { openOperation(localStorage.getItem(readKey) || previous); return }
        if (state.kind === 'failed') {
          if (!replaces) { setFailedOperation(state.failed); return }
          if (!sameFailure(state.failed, replaces)) { openOperation(previous); return }
        } else if (state.kind === 'saved' && !replaces) {
          localStorage.removeItem(readKey)
          setFailedOperation(null)
        } else { openOperation(previous); return }
      }
      const context = await apiJson<MeetingVersionContext>(`/api/task/${encodeURIComponent(taskId)}/meeting-version-context`, { cache: 'no-store' })
      if (!active()) return
      if (context.protocol !== 1 || context.parent_task_id !== taskId || !context.original_llm?.model_name || !context.original_llm.server_url || !/^[0-9a-f]{64}$/.test(context.context_revision) || !/^[0-9a-f]{64}$/.test(context.source?.version)) throw new Error('当前没有可核验的纪要来源。')
      setConfirmation({ context, replaces })
      ++catalogSequence.current; setCatalog(null); setLoadingModels(false)
      setLlmMode('inherit'); setAsrMode('reuse'); setAsrModel(''); setAsrConsent(false)
      setModelName(context.original_llm.model_name)
      setContentDepth('concise'); setPresentation('text')
    } catch (cause) {
      if (active()) setError(cause instanceof ApiError && cause.status === 409 ? '当前资料不可重新生成纪要，请保留原文件与已有处理记录。' : cause instanceof Error ? cause.message : '无法核验来源，请稍后重试。')
    } finally { lock.current = false; if (active()) setBusy(false) }
  }

  async function chooseModels(mode: 'inherit' | 'select', asr = asrMode) {
    if (!confirmation || busy) return
    setLlmMode(mode); setError(''); setAsrConsent(false)
    const sequence = ++catalogSequence.current
    if (mode === 'inherit' && asr === 'reuse') { setLoadingModels(false); setCatalog(null); setModelName(confirmation.context.original_llm.model_name); return }
    setModelName(''); setAsrModel(''); setCatalog(null); setLoadingModels(true)
    try {
      const result = await apiJson<MeetingVersionModels>(`/api/task/${encodeURIComponent(taskId)}/meeting-version-models?context_revision=${confirmation.context.context_revision}`, { cache: 'no-store' })
      if (!active() || sequence !== catalogSequence.current) return
      if (!Array.isArray(result.models) || !/^[a-f0-9]{64}$/.test(result.selection_revision) || !result.connection?.server_url) throw new Error('无法核验当前连接的总结模型目录，未开始生成。')
      setCatalog(result)
    } catch (cause) { if (active() && sequence === catalogSequence.current) setError(cause instanceof Error ? cause.message : '目录不可用，请重新选择。') }
    finally { if (active() && sequence === catalogSequence.current) setLoadingModels(false) }
  }

  async function confirm() {
    if (!confirmation || !owner || disabled || lock.current || !active()) return
    if (loadingModels || !modelName || llmMode === 'select' && (!catalog || !models.some(model => model.id === modelName))) return
    if (llmMode === 'inherit' && confirmation.context.original_llm.verified === false) return
    if (asrMode === 'reuse' && !confirmation.context.asr_modes.reuse.available) return
    if (asrMode === 'fresh' && (!confirmation.context.asr_modes.fresh.available || !asrConsent || llmMode !== 'select' || !catalog?.models.some(model => model.id === asrModel && model.modelType === 'asr' && modelEligibility(model) === 'available'))) return
    if (presentationOptions?.[presentation]?.available === false ||
        !presentationOptions && !['text', 'html'].includes(presentation)) return
    lock.current = true; setBusy(true); setError('')
    const operationId = crypto.randomUUID()
    const key = `vinote:source-receipt:${owner}:${operationId}`
    const modelConnection = llmMode === 'inherit' ? confirmation.context.original_llm : catalog!.connection
    const pending = { operationId, owner, createdAt: new Date().toISOString(), submissionState: 'unknown', workspace, meeting: true, meetingVersion: true, mode: 'file', independentGeneration: true, summaryOnly: asrMode === 'reuse', summaryNoteId: noteId, parentTaskId: taskId, sourceType: confirmation.context.source.type, sourceTitle: typeof confirmation.context.source.title === 'string' ? confirmation.context.source.title.trim() || undefined : undefined, meetingVersionContext: confirmation.context, modelConnection, asrMode, modelName, contentDepth, presentation, origin: modelConnection.server_url }
    let protectedOperation = false
    try {
      const readKey = pointerReadKey.current
      const existing = localStorage.getItem(pointerKey) || localStorage.getItem(readKey)
      if (confirmation.replaces) {
        const previous = confirmation.replaces
        if (existing !== previous.operationId) { openOperation(existing || previous.operationId); return }
        const state = await inspectOperation(existing)
        if (!active()) return
        if ((localStorage.getItem(pointerKey) || localStorage.getItem(readKey)) !== existing || state.kind !== 'failed' || !sameFailure(state.failed, previous)) {
          openOperation(localStorage.getItem(pointerKey) || localStorage.getItem(readKey) || previous.operationId); return
        }
      } else if (existing) { openOperation(existing); return }
      const serialized = JSON.stringify(pending)
      localStorage.setItem(key, serialized)
      localStorage.setItem(pointerKey, operationId)
      if (readKey !== pointerKey) localStorage.setItem(readKey, operationId)
      if (localStorage.getItem(key) !== serialized || localStorage.getItem(pointerKey) !== operationId) throw new Error('无法保存本次操作记录，未开始处理。')
      protectedOperation = true
      if (!active()) return
      const result = await apiJson<Receipt>(`/api/task/${encodeURIComponent(taskId)}/meeting-versions`, { method: 'POST', body: JSON.stringify({ operation_id: operationId, confirmed: true, context_revision: confirmation.context.context_revision, source_version: confirmation.context.source.version, asr_mode: asrMode, llm_mode: llmMode, content_depth: contentDepth, presentation,
        ...(llmMode === 'select' ? { model_name: modelName, selection_revision: catalog!.selection_revision, ...(catalog!.connection.connection_id ? { connection_id: catalog!.connection.connection_id } : {}) } : {}),
        ...(asrMode === 'fresh' ? { asr_model: asrModel, fresh_context_revision: confirmation.context.asr_modes.fresh.context_revision, extra_asr_consent: true } : {}) }) })
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
    <Button variant="outline" size="sm" disabled={disabled || busy || !owner} onClick={event => void prepare(undefined, event.currentTarget)}>{busy ? '正在核验…' : '生成新版本'}</Button>
    {failedOperation && <div className="grid gap-2">
      <p role="status" className="text-sm text-muted-foreground">上次总结已确认失败。失败记录会保留，可另选模型和形式生成新版本，不重试原操作。</p>
      <Button variant="outline" size="sm" disabled={disabled || busy || !owner} onClick={event => void prepare(failedOperation, event.currentTarget)}>保留失败记录，另建新版本</Button>
      <Button variant="ghost" size="sm" disabled={busy} onClick={() => openOperation(failedOperation.operationId)}>查看失败记录</Button>
    </div>}
    {error && !confirmation && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Dialog open={!!confirmation} onOpenChange={open => { if (!open && !busy) setConfirmation(null) }}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] overflow-y-auto overscroll-contain" closeLabel="关闭" onCloseAutoFocus={restoreOpener}><DialogHeader><DialogTitle>确认生成新版本</DialogTitle><DialogDescription>{asrMode === 'reuse' ? '复用原始 ASR 转写、独立说话人及可用画面证据，不以上一版纪要为输入，不重新转录。' : '明确重新识别原录制并生成纪要，将额外使用 ASR 与 LLM 额度。'}新纪要独立保存，已有记录和原文件保留；总结可能产生模型费用。</DialogDescription></DialogHeader>
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <FieldGroup>
          <Field><FieldLabel id="summary-asr-mode">语音识别</FieldLabel>
            <ToggleGroup type="single" variant="outline" value={asrMode} disabled={busy} aria-labelledby="summary-asr-mode" className="justify-start flex-wrap" onValueChange={value => {
              if (value !== 'reuse' && value !== 'fresh') return
              setAsrMode(value); setAsrConsent(false); setPresentation('text')
              void chooseModels(value === 'fresh' ? 'select' : 'inherit', value)
            }}>
              <ToggleGroupItem value="reuse" disabled={!confirmation?.context.asr_modes.reuse.available}>复用已有转写（默认）</ToggleGroupItem>
              <ToggleGroupItem value="fresh" disabled={!confirmation?.context.asr_modes.fresh.available}>重新识别 ASR{!confirmation?.context.asr_modes.fresh.available ? '（不可用）' : ''}</ToggleGroupItem>
            </ToggleGroup>
            {confirmation?.context.asr_modes.reuse.available === false && <p role="status" className="text-sm text-destructive">{confirmation.context.asr_modes.reuse.reason || '已有转写暂不能核验，未开始生成。'}不会自动重新识别。</p>}
            <FieldDescription>{confirmation?.context.asr_modes.fresh.reason || '重新识别需明确选择 ASR 和 LLM，并确认额外额度。'}</FieldDescription>
          </Field>
          <Field><FieldLabel id="summary-llm-mode">总结模型来源</FieldLabel>
            <ToggleGroup type="single" variant="outline" value={llmMode} disabled={busy || asrMode === 'fresh'} aria-labelledby="summary-llm-mode" className="justify-start flex-wrap" onValueChange={value => { if (value === 'inherit' || value === 'select') void chooseModels(value) }}>
              <ToggleGroupItem value="inherit" disabled={confirmation?.context.original_llm.verified === false}>沿用所选纪要模型{confirmation?.context.original_llm.verified === false ? '（不可用）' : '（默认）'}</ToggleGroupItem>
              <ToggleGroupItem value="select">更换总结模型</ToggleGroupItem>
            </ToggleGroup>
          </Field>
          {confirmation?.context.original_llm.reason && <p role="status" className="text-sm text-muted-foreground">{confirmation.context.original_llm.reason}</p>}
          <Field><FieldLabel htmlFor="summary-model-choice">本次总结模型</FieldLabel>
            <NativeSelect id="summary-model-choice" value={modelName} disabled={busy || llmMode === 'inherit' || loadingModels} aria-describedby="summary-model-help" onChange={event => { setModelName(event.target.value); setAsrConsent(false) }}>
              {llmMode === 'inherit' && <option value={confirmation?.context.original_llm.model_name}>{confirmation?.context.original_llm.model_name}{confirmation?.context.original_llm.verified === false ? '（历史记录，连接待核验）' : '（原版本）'}</option>}
              <option value="" disabled>请选择本次总结模型</option>
              {llmMode === 'select' && models.map(model => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
            </NativeSelect>
            <FieldDescription id="summary-model-help">默认沿用所选纪要的原模型与原连接，不修改全局模型偏好。只有明确更换时读取当前连接目录；草稿与事实复核使用同一模型。</FieldDescription>
          </Field>
          {loadingModels && <p role="status">正在核验当前连接目录…</p>}
          {asrMode === 'fresh' && <>
            <Field><FieldLabel htmlFor="summary-asr-choice">本次 ASR 模型</FieldLabel>
              <NativeSelect id="summary-asr-choice" value={asrModel} disabled={busy || loadingModels} onChange={event => { setAsrModel(event.target.value); setAsrConsent(false) }}>
                <option value="" disabled>请选择本次 ASR 模型</option>
                {catalog?.models.filter(model => model.modelType === 'asr' && modelEligibility(model) === 'available').map(model => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
              </NativeSelect>
            </Field>
            <Field orientation="horizontal"><Checkbox id="summary-extra-asr" checked={asrConsent} disabled={busy} onCheckedChange={value => setAsrConsent(value === true)} /><FieldLabel htmlFor="summary-extra-asr">我确认重新识别会额外使用 ASR 与 LLM 额度</FieldLabel></Field>
          </>}
          <Field><FieldLabel id="summary-depth-label">内容详略</FieldLabel>
            <ToggleGroup type="single" variant="outline" value={contentDepth} disabled={busy} aria-labelledby="summary-depth-label" onValueChange={value => { if (value) setContentDepth(value as ContentDepth) }} className="justify-start flex-wrap">
              {(Object.keys(depthLabels) as ContentDepth[]).map(value => <ToggleGroupItem key={value} value={value}>{depthLabels[value]}</ToggleGroupItem>)}
            </ToggleGroup>
          </Field>
          <Field><FieldLabel id="summary-presentation-label">呈现形式</FieldLabel>
            <ToggleGroup type="single" variant="outline" value={presentation} disabled={busy} aria-labelledby="summary-presentation-label" aria-describedby="summary-presentation-help" onValueChange={value => { if (value) setPresentation(value as Presentation) }} className="justify-start flex-wrap">
              {(Object.keys(presentationLabels) as Presentation[]).map(value => {
                const available = presentationOptions?.[value]?.available ?? ['text', 'html'].includes(value)
                return <ToggleGroupItem key={value} value={value} disabled={!available} title={presentationOptions?.[value]?.reason || undefined}>{presentationLabels[value]}{!available ? '（不可用）' : ''}</ToggleGroupItem>
              })}
            </ToggleGroup>
            <FieldDescription id="summary-presentation-help">图文只使用已核验的原视频截图，其他形式以当前可用能力为准，不会自动更换模型。每次生成独立保存，同形式可保留多个版本。</FieldDescription>
          </Field>
        </FieldGroup>
        <p className="text-sm">来源类型：{['video', 'meeting_video'].includes(confirmation?.context.source.type || '') ? '视频' : ['audio', 'meeting_audio', 'meeting_recording'].includes(confirmation?.context.source.type || '') ? '音频' : '已保留资料'}。仅使用已核验的证据，不将缺失内容当作静音。</p>
        <Button disabled={busy || loadingModels || disabled || !modelName || llmMode === 'inherit' && confirmation?.context.original_llm.verified === false || asrMode === 'fresh' && (!asrModel || !asrConsent) || asrMode === 'reuse' && !confirmation?.context.asr_modes.reuse.available} onClick={() => void confirm()}>{busy ? '正在提交…' : '确认生成新版本'}</Button>
        <Button variant="outline" disabled={busy} onClick={() => setConfirmation(null)}>取消</Button>
      </DialogContent>
    </Dialog>
  </div>
}
