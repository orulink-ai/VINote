/** Independent of summaryPresentation: it is being extended by another agent. */
export type ContentDepth = 'brief' | 'concise' | 'detailed'
export type Presentation = 'text' | 'illustrated' | 'html' | 'comic' | 'infographic'
export type MeetingVersionContext = {
  protocol: 1; parent_task_id: string; canonical_task_id: string; context_revision: string
  source: { version: string; type: string; title?: string; file_id?: string }
  original_llm: { model_name: string; server_url: string; connection_id?: string; verified: boolean; reason?: string }
  default_asr_mode: 'reuse'; default_llm_mode: 'inherit'
  asr_modes: { reuse: { available: boolean; reason?: string }; fresh: { available: boolean; reason?: string; context_revision?: string; presentation_options?: Partial<Record<Presentation, { available: boolean; reason?: string | null }>> } }
  presentation_options?: Partial<Record<Presentation, { available: boolean; reason?: string | null }>>
}
export type MeetingVersionModels = {
  models: { id: string; modelType: string; runtimeStatus: string; availability?: { status?: string; retryAt?: number | null }; name?: string }[]
  selection_revision: string; connection: { server_url: string; connection_id?: string }
}
export function meetingVersionOperationKey(owner: string, parent: string, note?: string) {
  return `vinote:meeting-version-operation:${owner}:${note || 'task'}:${parent}`
}
/** Read-only operation recovery is bound to its owner/local backend, not global LLM preferences. */
export function isMeetingVersionReceipt(value: unknown, owner?: string): boolean {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  const context = item.meetingVersionContext as MeetingVersionContext | undefined
  const connection = item.modelConnection as { server_url?: string } | undefined
  return item.meetingVersion === true && item.meeting === true && item.independentGeneration === true
    && typeof item.owner === 'string' && (owner === undefined || item.owner === owner)
    && typeof item.operationId === 'string' && typeof item.parentTaskId === 'string'
    && (item.asrMode === 'reuse' && item.summaryOnly === true || item.asrMode === 'fresh' && item.summaryOnly === false)
    && context?.protocol === 1 && context.parent_task_id === item.parentTaskId
    && typeof item.origin === 'string' && item.origin === connection?.server_url
    && /^[a-f0-9]{64}$/.test(context.context_revision) && /^[a-f0-9]{64}$/.test(context.source?.version)
}

export function meetingVersionSourceType(value: unknown, owner?: string): string {
  if (!isMeetingVersionReceipt(value, owner)) return 'unknown'
  const item = value as { meetingVersionContext: MeetingVersionContext }
  const kind = item.meetingVersionContext.source.type
  return ['video', 'meeting_video'].includes(kind) ? 'meeting_video'
    : ['audio', 'meeting_audio', 'meeting_recording'].includes(kind) ? 'meeting_recording' : 'unknown'
}

export function meetingVersionOriginalFile(value: unknown, owner?: string): string | undefined {
  if (!isMeetingVersionReceipt(value, owner)) return undefined
  const { meetingVersionContext: context } = value as { meetingVersionContext: MeetingVersionContext }
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(context.canonical_task_id)) return undefined
  const expected = `task:${context.canonical_task_id}`
  return context.source.file_id === expected ? expected : undefined
}
