import type { PluginRun, previewPlugin } from './contentPlugins'

export type ContentPluginRequest = Parameters<typeof previewPlugin>[0]
export type RecoverablePluginRun = PluginRun & {
  source_version_id?: string
  language?: string
  source_content?: string
  source_title?: string
  retry_safe?: boolean
}
export type ContentPluginReceipt = {
  request: ContentPluginRequest
  phase: 'submitted' | 'running' | 'ready' | 'saving' | 'saved' | 'failed' | 'interrupted'
  created_at: string
}

const phases = ['submitted', 'running', 'ready', 'saving', 'saved', 'failed', 'interrupted']
export function contentPluginRecoveryKey(owner: string) {
  if (!owner) throw new Error('请先登录，再处理内容。')
  return `vinote:${encodeURIComponent(owner)}:content-plugin-recovery:v1`
}

function checked(value: unknown): ContentPluginReceipt {
  if (!value || typeof value !== 'object') throw new Error('插件恢复记录无法读取，请保留缓存并检查存储。')
  const row = value as ContentPluginReceipt, request = row.request
  if (!request || !['translation', 'diagram', 'actions', 'glossary'].includes(request.plugin_id)
    || typeof request.operation_id !== 'string' || !/^[A-Za-z0-9_-]{1,100}$/.test(request.operation_id)
    || typeof request.note_key !== 'string' || !/^[A-Za-z0-9_.:-]{1,160}$/.test(request.note_key)
    || typeof request.version_id !== 'string' || !request.version_id || request.version_id.length > 160
    || !Number.isSafeInteger(request.base_revision) || request.base_revision < 1
    || typeof request.language !== 'string' || request.language.length > 10
    || (request.plugin_id === 'translation' && !request.language)
    || typeof request.glossary !== 'string' || request.glossary.length > 4000
    || !phases.includes(row.phase) || typeof row.created_at !== 'string' || !Number.isFinite(Date.parse(row.created_at))) {
    throw new Error('插件恢复记录无法读取，请保留缓存并检查存储。')
  }
  // Retain only the request fields. Never persist arbitrary response fields or tokens.
  return { request: {
    operation_id: request.operation_id, plugin_id: request.plugin_id, note_key: request.note_key,
    version_id: request.version_id, base_revision: request.base_revision,
    language: request.language, glossary: request.glossary,
  }, phase: row.phase, created_at: row.created_at }
}

export function readContentPluginReceipts(owner: string): ContentPluginReceipt[] {
  const raw = localStorage.getItem(contentPluginRecoveryKey(owner))
  if (!raw) return []
  let value: unknown
  try { value = JSON.parse(raw) } catch { throw new Error('插件恢复记录无法读取，请保留缓存并检查存储。') }
  if (!Array.isArray(value)) throw new Error('插件恢复记录无法读取，请保留缓存并检查存储。')
  const receipts = value.map(checked)
  if (new Set(receipts.map(row => row.request.operation_id)).size !== receipts.length) {
    throw new Error('插件恢复记录重复，请保留缓存并检查存储。')
  }
  return receipts
}

export function writeContentPluginReceipt(owner: string, receipt: ContentPluginReceipt) {
  const row = checked(receipt), receipts = readContentPluginReceipts(owner)
  const existing = receipts.find(item => item.request.operation_id === row.request.operation_id)
  if (existing && JSON.stringify(existing.request) !== JSON.stringify(row.request)) {
    throw new Error('本次操作已绑定其他来源，请先核验原处理。')
  }
  localStorage.setItem(contentPluginRecoveryKey(owner), JSON.stringify([
    row, ...receipts.filter(item => item.request.operation_id !== row.request.operation_id),
  ]))
}

/** Only confirmed saves are disposable; unknown operations must stay recoverable. */
export function clearSavedContentPluginReceipt(owner: string, operation: string) {
  const receipts = readContentPluginReceipts(owner)
  if (receipts.some(row => row.request.operation_id === operation && row.phase !== 'saved')) {
    throw new Error('处理尚未确认保存，请先核验原运行。')
  }
  localStorage.setItem(contentPluginRecoveryKey(owner), JSON.stringify(receipts.filter(row => row.request.operation_id !== operation)))
}

export function rememberContentPluginRun(owner: string, run: RecoverablePluginRun): ContentPluginReceipt {
  const previous = readContentPluginReceipts(owner).find(row => row.request.operation_id === run.id)
  if (previous && (previous.request.note_key !== run.note_key || previous.request.plugin_id !== run.plugin_id
    || previous.request.base_revision !== run.base_revision
    || (run.source_version_id && run.source_version_id !== previous.request.version_id)
    || (run.language !== undefined && run.language !== previous.request.language))) {
    throw new Error('运行来源与原请求不一致，请保留记录并核验。')
  }
  if (!previous && !run.source_version_id) throw new Error('运行尚未返回源版本，请查询原处理，不能使用当前正文代替。')
  const phase = phases.includes(run.status) ? run.status as ContentPluginReceipt['phase'] : 'submitted'
  const receipt: ContentPluginReceipt = { request: previous?.request || {
    operation_id: run.id, plugin_id: run.plugin_id, note_key: run.note_key,
    version_id: run.source_version_id!, base_revision: run.base_revision,
    language: run.language || 'en', glossary: '',
  }, phase, created_at: previous?.created_at || run.created_at }
  writeContentPluginReceipt(owner, receipt)
  return receipt
}

export function canRetryContentPluginRun(run: RecoverablePluginRun) {
  return run.retry_safe === true && ['failed', 'interrupted'].includes(run.status)
    && !['translation', 'diagram'].includes(run.plugin_id)
}
