import { apiJson } from './api'

export type VersionHistory = {
  label: string
  detail: string
  action: string
  title?: string
  taskId?: string
  noteId?: string
  saveable?: boolean
  failed?: boolean
}

const stages: Record<string, string> = {
  queued: '排队中', preparing: '准备会议资料', preparing_media: '准备会议资料',
  transcribing: '语音转写', parallel_analysis: '转写与说话人分析', diarizing: '说话人分析',
  aligning: '核对转写', transcript_ready: '转写已就绪', analyzing_video: '整理共享画面与发言资料',
  summarizing: '生成与事实复核', generating: '生成与事实复核', screenshots: '整理画面引用',
  saving: '保存结果', saving_result: '保存结果',
}
const unknownCodes = new Set(['summary_result_unconfirmed', 'unknown_result', 'unknown_error', 'asr_incomplete_result'])
const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const identifier = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(value)
const text = (value: unknown): value is string => typeof value === 'string' && !!value.trim()

export const unverifiedVersionHistory = (): VersionHistory => ({
  label: '状态待核验', detail: '尚未确认原任务状态。原提交记录已保留，请查询原结果。', action: '核验原提交',
})

/** Display only: a frozen capture placeholder is not a generated subject. */
export function versionHistoryTitle(title: string) {
  return title.replace(/\s*[｜|]\s*待生成纪要\s*$/, ' 录制')
}

/** Read only. Never persist readback, clear a pointer, retry, or submit work.
 * current() also guards concurrent receipt replacement/removal in another view. */
export async function readMeetingVersionHistory(
  receipt: { operationId?: string; id?: string },
  signal: AbortSignal,
  current: () => boolean,
): Promise<VersionHistory | null> {
  const value = receipt as Record<string, unknown>
  const pending = unverifiedVersionHistory()
  let taskId: string | undefined
  const get = async (path: string) => {
    if (!current()) throw new Error('obsolete')
    const result = await apiJson<unknown>(path, { method: 'GET', signal, cache: 'no-store' })
    if (!current()) throw new Error('obsolete')
    return result
  }
  try {
    if (!identifier(receipt.operationId)) return pending
    const op = object(await get(`/api/source-requests/${encodeURIComponent(receipt.operationId)}`))
    if (op.operation_id !== receipt.operationId || !identifier(op.task_id)
        || op.task_id === value.parentTaskId || receipt.id !== undefined && receipt.id !== op.task_id) return pending
    if (op.state === 'reserved') return { ...pending, label: '提交待确认', detail: '原提交仍为预留状态，请核验原结果，不重复提交。' }
    if (op.state !== 'accepted') return pending
    taskId = op.task_id
    const task = object(await get(`/api/task/${encodeURIComponent(taskId)}`))
    const result = object(task.result)
    if (task.task_id !== taskId || task.operation_id !== undefined && task.operation_id !== receipt.operationId
        || result.task_id !== undefined && result.task_id !== taskId) return pending
    const query = { ...pending, taskId, action: '查看原任务与处理记录' }
    if (unknownCodes.has(String(task.error_code)) || ['unknown', 'unknown_result', 'summary_result_unconfirmed'].includes(String(task.status))) {
      return { ...query, label: '结果待确认', detail: '原任务结果尚未确认，请查询原记录，不重复生成。' }
    }
    if (['failed', 'error'].includes(String(task.status))) {
      const stage = stages[String(task.failed_stage)]
      return { label: stage ? `未完成 · ${stage}` : '未完成', taskId, failed: true,
        detail: '原任务未完成，原资料与提交记录已保留。', action: '查看失败处理记录' }
    }
    if (task.status !== 'success') {
      const stage = stages[String(task.stage)] || stages[String(task.status)]
      return stage ? { ...query, label: stage, detail: '以上为原任务最近一次读取的阶段，可刷新核验。' } : query
    }
    if (!text(result.title) || !text(result.markdown)) return { ...query, label: '结果待核验', detail: '原任务报告已完成，但完整结果尚未核验。' }
    const workspace = object(value.workspace)
    // Use the frozen destination, never the current workspace selection.
    let scope = '?scope=personal'
    if (workspace.scope === 'team' && identifier(workspace.teamId)) scope = `?scope=team&team_id=${encodeURIComponent(workspace.teamId)}`
    else if (workspace.scope !== 'personal') return query
    const notes = await get(`/api/notes${scope}`)
    if (!Array.isArray(notes)) return query
    const saved = notes.map(object).find(note => note.task_id === taskId && identifier(note.id))
    if (saved) return { label: '已保存', detail: '原任务结果已保存为纪要。', action: '查看已保存纪要', taskId,
      noteId: saved.id as string, title: text(saved.title) ? saved.title : result.title }
    return { label: '已生成，待保存', detail: '原任务已有完整结果，可从原提交恢复保存。',
      action: '查看原结果并恢复保存', taskId, title: result.title, saveable: true }
  } catch {
    return current() ? { ...pending, taskId } : null
  }
}
