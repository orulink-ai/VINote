import { ApiError } from './api'
import { isMeetingVersionReceipt, type ContentDepth, type MeetingVersionContext, type Presentation } from './meetingVersion'
import { resolvePageParent } from './navigation'

// accept() checks _existing first. Only these exact errors occur before any
// executor/reserve; transport errors, other 409s and 404s prove nothing.
const preflightCodes = new Set(['meeting_version_context_changed', 'meeting_version_selection_changed'])
type PreflightCode = 'meeting_version_context_changed' | 'meeting_version_selection_changed'
export type VersionRejection = { protocol: 1; status: 409; code: PreflightCode; message: string }
export type RejectedVersionReceipt = {
  operationId: string; owner: string; parentTaskId: string; summaryNoteId?: string
  sourceDetailUrl?: string; sourceParentUrl?: string
  submissionState: 'not_accepted'; preflightRejection: VersionRejection
}
export const versionNotAcceptedCopy = '本次未受理，未创建任务。请返回来源重新核验模型与资料，再明确确认新版本。'

function rejection(value: unknown): value is VersionRejection {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const item = value as VersionRejection
  return Object.keys(item).sort().join(',') === 'code,message,protocol,status'
    && item.protocol === 1 && item.status === 409 && preflightCodes.has(item.code)
    && typeof item.message === 'string' && !!item.message.trim()
}

export function versionPreflightRejection(error: unknown): VersionRejection | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.detail ||
      typeof error.detail !== 'object' || Array.isArray(error.detail)) return null
  const detail = error.detail as Record<string, unknown>
  if (Object.keys(detail).sort().join(',') !== 'code,message' ||
      typeof detail.code !== 'string' || !preflightCodes.has(detail.code) ||
      typeof detail.message !== 'string' || !detail.message.trim()) return null
  return { protocol: 1, status: 409, code: detail.code as PreflightCode, message: detail.message }
}

export function isRejectedVersionReceipt(value: unknown, owner?: string): value is RejectedVersionReceipt {
  if (!owner || !isMeetingVersionReceipt(value, owner)) return false
  const item = value as Record<string, unknown>
  return item.id === undefined && item.task_id === undefined && item.state === undefined
    && item.submissionState === 'not_accepted' && rejection(item.preflightRejection)
    && (item.summaryNoteId === undefined || typeof item.summaryNoteId === 'string' && !!item.summaryNoteId)
}

export const versionRejectionKey = (owner: string, operation: string) => `vinote:version-rejection:${owner}:${operation}`

/** An audit is separate from execution state. Never write/remove a receipt or
 * pointer in response to rejection: localStorage has no cross-window CAS. */
export function readVersionReceipt(storage: Pick<Storage, 'getItem'>, owner: string, operation: string): unknown {
  const key = `vinote:source-receipt:${owner}:${operation}`
  const raw = storage.getItem(key)
  let audit: { pending?: string; rejection?: unknown } | null = null
  try { audit = JSON.parse(storage.getItem(versionRejectionKey(owner, operation)) || 'null') } catch { /* Ignore corrupt audit. */ }
  // Read execution state last. A changed/accepted/reserved receipt always wins.
  const current = storage.getItem(key)
  const value = JSON.parse(current || 'null')
  if (raw !== current || !audit || audit.pending !== current || !rejection(audit.rejection)
      || !isMeetingVersionReceipt(value, owner) || value.operationId !== operation
      || value.submissionState !== 'unknown' || value.id !== undefined
      || value.task_id !== undefined || value.state !== undefined) return value
  const projected = { ...value, submissionState: 'not_accepted', preflightRejection: audit.rejection }
  return isRejectedVersionReceipt(projected, owner) ? projected : value
}

/** Keep only an app detail URL bound to the actual selected note/task. */
export function versionSourceLocation(note: string | undefined, task: string, candidates: unknown[], stateParent?: unknown) {
  for (const candidate of candidates) {
    if (typeof candidate !== 'string' || !candidate.startsWith('/') || candidate.startsWith('//')) continue
    try {
      const url = new URL(candidate, 'https://vinote.invalid')
      if (url.origin !== 'https://vinote.invalid') continue
      const matches = note ? url.pathname === `/note/${encodeURIComponent(note)}`
        : url.pathname === '/generate' && url.searchParams.getAll('task').length === 1
          && url.searchParams.get('task') === task && url.searchParams.get('meeting') === '1'
          && !url.searchParams.has('operation')
      if (!matches) continue
      const queryParent = url.searchParams.get('returnTo')
      const parent = resolvePageParent(queryParent, '') || resolvePageParent(stateParent, '')
      if (queryParent !== null && !resolvePageParent(queryParent, '')) url.searchParams.delete('returnTo')
      return { sourceDetailUrl: url.pathname + url.search + url.hash,
        sourceParentUrl: parent || undefined }
    } catch { /* Try the next identity-bound candidate. */ }
  }
  return {}
}

export function rejectedVersionSource(receipt: RejectedVersionReceipt): string {
  return versionSourceLocation(receipt.summaryNoteId, receipt.parentTaskId, [receipt.sourceDetailUrl]).sourceDetailUrl
    || (receipt.summaryNoteId ? `/note/${encodeURIComponent(receipt.summaryNoteId)}`
    : '/generate?' + new URLSearchParams({ meeting: '1', task: receipt.parentTaskId })
    )
}

export function rejectedVersionParent(receipt: RejectedVersionReceipt, fallback: string): string {
  return versionSourceLocation(receipt.summaryNoteId, receipt.parentTaskId, [receipt.sourceDetailUrl], receipt.sourceParentUrl).sourceParentUrl
    || resolvePageParent(receipt.sourceParentUrl, '') || fallback
}

/** Display the frozen local choice, never the current global model/settings. */
export function meetingVersionDetails(value: unknown, owner?: string) {
  if (!owner || !isMeetingVersionReceipt(value, owner)) return null
  const item = value as Record<string, unknown>
  const context = item.meetingVersionContext as MeetingVersionContext
  const text = (v: unknown, max: number) => typeof v === 'string' && !!v.trim()
    && v.length <= max && !/[\x00-\x1f\x7f]/.test(v)
  if (!text(item.modelName, 200) || typeof item.contentDepth !== 'string' ||
      !['brief', 'concise', 'detailed'].includes(item.contentDepth) || typeof item.presentation !== 'string' ||
      !['text', 'html', 'illustrated', 'comic', 'infographic'].includes(item.presentation) ||
      typeof item.createdAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(item.createdAt) ||
      !Number.isFinite(Date.parse(item.createdAt))) return null
  const title = text(context.source.title, 300) ? context.source.title!.trim() : '会议资料'
  return { title, model: item.modelName as string, depth: item.contentDepth as ContentDepth,
    presentation: item.presentation as Presentation, createdAt: item.createdAt, reuse: item.asrMode === 'reuse' }
}
