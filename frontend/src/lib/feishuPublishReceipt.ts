import { useAuthStore } from '@/stores/authStore'
import { readRuntimeConfig } from './runtimeConfig'
import { deliveryById, deliveryByOperation, type Delivery, type FeishuDestination, type FeishuContact } from './feishu'

export type PublishDraft = {
  owner: string; noteKey: string; origin: string; operationId: string
  snapshot: { title: string; content: string; versionId?: string; revisionId?: string }
  options: { destination_config: FeishuDestination; permission_policy: 'private' | 'inherit'; notify_self: boolean; groups: string[]; contacts?: FeishuContact[]; recipient_access_policy?: 'grant_view_and_notify' }
  state: 'draft' | 'unknown' | 'acknowledged'; jobId?: string
}
const origin = () => readRuntimeConfig('VITE_API_BASE_URL') || window.location.origin
const key = (owner: string, note: string) => `vinote:${owner}:feishu-publish:${encodeURIComponent(note)}`
let epoch = 0
let currentOwner = useAuthStore.getState().user?.id
if (typeof useAuthStore.subscribe === 'function') useAuthStore.subscribe(state => {
  if (state.user?.id !== currentOwner) { epoch++; currentOwner = state.user?.id }
})
export function publishScope(owner: string) {
  guardPublishOwner(owner)
  const started = epoch
  const startedOrigin = origin()
  return () => { guardPublishOwner(owner); if (epoch !== started) throw new Error('账号会话已变化，原发布草稿保留'); if (origin() !== startedOrigin) throw new Error('原发布服务已变化，原发布草稿保留') }
}
// In-memory evidence belongs to one live invocation, never a historical JSON receipt.
export type PublishAttempt = { readonly operationId: string }
const attempts = new WeakMap<PublishAttempt, { draft: PublishDraft; guard: () => void; phase: 'preflight' | 'not_dispatched' | 'unknown' }>()
const latestAttempts = new Map<string, PublishAttempt>()
export function beginPublishAttempt(draft: PublishDraft, current: () => void = () => {}) : PublishAttempt {
  const saved = readPublishDraft(draft.owner, draft.noteKey)
  if (!saved || saved.state !== 'draft' || saved.operationId !== draft.operationId || saved.jobId || JSON.stringify(saved.snapshot) !== JSON.stringify(draft.snapshot)) throw new Error('只有当前未提交草稿可开始发布')
  const attempt = { operationId: draft.operationId }
  const scope = publishScope(draft.owner)
  attempts.set(attempt, { draft, guard: () => { scope(); current() }, phase: 'preflight' })
  latestAttempts.set(key(draft.owner, draft.noteKey), attempt)
  return attempt
}
export function markPublishAttempt(attempt: PublishAttempt, phase: 'not_dispatched' | 'unknown') {
  const evidence = attempts.get(attempt)
  if (!evidence || evidence.phase === 'unknown') throw new Error('发布派发状态不可回退')
  evidence.guard()
  if (latestAttempts.get(key(evidence.draft.owner, evidence.draft.noteKey)) !== attempt) throw new Error('发布调用已变化')
  evidence.phase = phase
}
export function restoreUndispatchedDraft(attempt: PublishAttempt): PublishDraft | null {
  const evidence = attempts.get(attempt)
  if (!evidence || evidence.phase !== 'not_dispatched') return null
  evidence.guard()
  const { draft } = evidence
  if (latestAttempts.get(key(draft.owner, draft.noteKey)) !== attempt) return null
  const saved = readPublishDraft(draft.owner, draft.noteKey)
  if (!saved || saved.state !== 'unknown' || saved.jobId || saved.operationId !== attempt.operationId || JSON.stringify(saved.snapshot) !== JSON.stringify(draft.snapshot) || JSON.stringify(saved.options) !== JSON.stringify(draft.options)) return null
  const restored = { ...saved, state: 'draft' as const }
  localStorage.setItem(key(draft.owner, draft.noteKey), JSON.stringify(restored))
  localStorage.removeItem(`${key(draft.owner, draft.noteKey)}:${attempt.operationId}`)
  attempts.delete(attempt)
  latestAttempts.delete(key(draft.owner, draft.noteKey))
  return restored
}
export function guardPublishOwner(owner: string) { if (!owner || useAuthStore.getState().user?.id !== owner) throw new Error('账号已切换，原发布草稿保留') }
export function readPublishDraft(owner: string, note: string): PublishDraft | null {
  guardPublishOwner(owner)
  const raw = localStorage.getItem(key(owner, note))
  if (!raw) return null
  const draft = JSON.parse(raw) as PublishDraft
  if (draft.owner !== owner || draft.noteKey !== note || !draft.operationId || !draft.snapshot || !draft.options || !['draft', 'unknown', 'acknowledged'].includes(draft.state)) throw new Error('发布草稿记录异常，请保留原记录')
  if (draft.origin !== origin()) throw new Error('原发布属于其他服务，请返回原服务核验')
  return draft
}
export function newPublishDraft(owner: string, noteKey: string, snapshot: PublishDraft['snapshot'], options: PublishDraft['options']): PublishDraft {
  guardPublishOwner(owner)
  return { owner, noteKey, origin: origin(), operationId: crypto.randomUUID(), snapshot: { ...snapshot }, options: JSON.parse(JSON.stringify(options)), state: 'draft' }
}
export function persistPublishDraft(draft: PublishDraft) {
  guardPublishOwner(draft.owner)
  const previous = readPublishDraft(draft.owner, draft.noteKey)
  if (previous && previous.operationId !== draft.operationId && draft.state !== 'draft') throw new Error('当前发布操作已变化，旧回执不能覆盖新草稿')
  if (previous?.state === 'acknowledged' && previous.operationId === draft.operationId && (draft.state === 'draft' || JSON.stringify(previous.snapshot) !== JSON.stringify(draft.snapshot) || JSON.stringify(previous.options) !== JSON.stringify(draft.options))) throw new Error('已提交发布输入不可改变')
  if (previous?.state === 'unknown' && (draft.state === 'draft' || previous.operationId !== draft.operationId || JSON.stringify(previous.snapshot) !== JSON.stringify(draft.snapshot) || JSON.stringify(previous.options) !== JSON.stringify(draft.options))) throw new Error('原发布结果未确认，不能改变输入或创建新提交')
  if (draft.origin !== origin()) throw new Error('原发布服务已变化')
  if (draft.state !== 'draft') localStorage.setItem(`${key(draft.owner, draft.noteKey)}:${draft.operationId}`, JSON.stringify(draft))
  localStorage.setItem(key(draft.owner, draft.noteKey), JSON.stringify(draft))
}
export async function queryPublishReceipt(draft: PublishDraft): Promise<{ draft: PublishDraft; job: Delivery }> {
  const guard = publishScope(draft.owner)
  if (draft.origin !== origin() || draft.state === 'draft') throw new Error('尚未提交或服务已变化')
  const job = draft.jobId ? await deliveryById(draft.jobId) : await deliveryByOperation(draft.operationId)
  guard()
  if ((draft.jobId && job.id !== draft.jobId) || (!draft.jobId && job.operation_id !== draft.operationId) || !job.id) throw new Error('返回回执不属于原发布操作')
  const confirmed = { ...draft, state: 'acknowledged' as const, jobId: job.id }
  persistPublishDraft(confirmed)
  return { draft: confirmed, job }
}
