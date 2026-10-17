import { apiJson } from './api'
import { cloudTranslationProvider, cloudTranslationSchema, mcpBase, type MCPRun, type MCPTool } from './mcpConnections'
import type { WorkspaceNote, WorkspaceWrite } from './workspace'

export type TranslationSource = { note_key: string; source_version_id: string; base_revision: number; content: string }
export type TranslationMapping = { text_parameter: string; language_parameter: string; target_language: 'en' | 'zh'; model_parameter?: 'model'; model?: string }
export type TranslationModels = { providerId: string; modelParameter: 'model'; models: { id: string; modelType: 'llm'; runtimeStatus: 'available' }[]; defaultModel: string | null }
export async function getTranslationModels(): Promise<TranslationModels> {
  const catalog = await apiJson<TranslationModels>(`${mcpBase}/first-party/translation/models`)
  if (catalog.providerId !== cloudTranslationProvider || catalog.modelParameter !== 'model' || !Array.isArray(catalog.models)
    || catalog.models.some(model => !model || typeof model.id !== 'string' || !model.id.trim() || model.modelType !== 'llm' || model.runtimeStatus !== 'available')
    || new Set(catalog.models.map(model => model.id)).size !== catalog.models.length
    || (catalog.defaultModel !== null && !catalog.models.some(model => model.id === catalog.defaultModel))) throw new Error('云翻译模型列表或默认模型无法核验，请重新读取；不会选择其他模型。')
  return catalog
}
export function validatedTranslationModel(catalog: TranslationModels | null, model: string): string {
  if (!catalog) throw new Error('请先读取当前账号可用的翻译模型。')
  if (!model) throw new Error('服务没有默认模型，请明确选择翻译模型。')
  if (!catalog.models.some(item => item.id === model)) throw new Error('所选翻译模型不可用，请明确重选；不会自动替换。')
  return model
}
export type TranslationRun = MCPRun
export type MCPReceipt = {
  connectionId: string; requestId: string; toolName: string; arguments: Record<string, unknown>;
  source?: TranslationSource; mapping?: TranslationMapping; runId?: string; saving?: boolean; saved?: boolean; saveBody?: WorkspaceWrite; status?: MCPRun['status'];
}
const complex = ['$ref', 'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else', 'dependentRequired', 'dependentSchemas', 'patternProperties']
const unsafe = new Set(['__proto__', 'prototype', 'constructor'])
export function translationFields(tool: MCPTool): string[] {
  const schema = tool.inputSchema
  if (schema.type !== 'object' || complex.some(key => key in schema) || !schema.properties || typeof schema.properties !== 'object' || Array.isArray(schema.properties)) return []
  const props = schema.properties as Record<string, unknown>
  return Object.keys(props).filter(key => {
    const value = props[key]
    return !unsafe.has(key) && !!value && typeof value === 'object' && !Array.isArray(value)
      && (value as Record<string, unknown>).type === 'string' && !complex.some(k => k in value)
  })
}
export function translationArguments(tool: MCPTool, source: TranslationSource, mapping: TranslationMapping) {
  const fields = translationFields(tool), { text_parameter: text, language_parameter: language, target_language: target } = mapping
  if (!fields.includes(text) || !fields.includes(language) || text === language || !['en', 'zh'].includes(target)) throw new Error('请明确选择两个不同的真实字符串参数及中文或英文目标语言。')
  const required = tool.inputSchema.required
  if (required !== undefined && (!Array.isArray(required) || required.some(key => typeof key !== 'string' || ![text, language].includes(key)))) throw new Error('此工具还需要其他参数，当前全文翻译流程不兼容。请选择只需要正文和目标语言的工具。')
  if (!source.content.trim()) throw new Error('源版本没有正文，请选择完整已保存版本。')
  if (source.content.length > 60000) throw new Error('完整源版本超过 60000 字符，不会截断处理。')
  const entries = [[text, source.content], [language, target]]
  if (mapping.model_parameter || mapping.model !== undefined) {
    if (!cloudTranslationSchema(tool) || text !== 'text' || language !== 'target_language' || mapping.model_parameter !== 'model' || !mapping.model?.trim()) throw new Error('官方模型参数无法核验，请重新发现工具并明确选择模型。')
    entries.push(['model', mapping.model])
  }
  const args = Object.fromEntries(entries)
  const properties = tool.inputSchema.properties as Record<string, Record<string, unknown>>
  for (const key of Object.keys(args)) {
    const schema = properties[key], value = args[key]
    if (Array.isArray(schema.enum) && !schema.enum.includes(value)) throw new Error('实际参数枚举不接受本次正文或目标语言，请选择兼容工具。')
    if ('const' in schema && schema.const !== value) throw new Error('实际参数固定值与本次正文或目标语言不符。')
    if (typeof schema.maxLength === 'number' && [...value].length > schema.maxLength) throw new Error('完整正文超过工具参数长度限制，不会截断。')
    if (typeof schema.minLength === 'number' && [...value].length < schema.minLength) throw new Error('正文或目标语言不满足工具参数长度限制。')
    if (key === mapping.model_parameter && schema.pattern === '^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$') {
      if (!/^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$/.test(value)) throw new Error('翻译模型 ID 不符合官方参数格式。')
    } else if ('pattern' in schema) throw new Error('参数需要额外格式校验，当前全文翻译流程不兼容。')
    if ('format' in schema) throw new Error('参数需要额外格式校验，当前全文翻译流程不兼容。')
  }
  // Match the server compact UTF-8 JSON serialization; never slice the source.
  const canonical = JSON.stringify(args)
  if (new TextEncoder().encode(canonical).length > 65536) throw new Error('完整正文与参数超过 64 KiB，不会截断或暗中分段。原文保留。')
  return args
}
export function translationText(run: TranslationRun) {
  if (run.status !== 'succeeded' || !run.result || typeof run.result !== 'object') return null
  const result = run.result as { content?: unknown; isError?: boolean; truncated?: boolean }
  if (result.isError || result.truncated || !Array.isArray(result.content) || !result.content.length) return null
  if (result.content.some(item => !item || item.type !== 'text' || typeof item.text !== 'string')) return null
  const text = result.content.map(item => item.text).join('\n\n')
  return text.trim() ? text : null
}
export const mcpRecoveryKey = (owner: string) => {
  if (!owner) throw new Error('请先登录。')
  return `vinote:${encodeURIComponent(owner)}:mcp-invocations:v1`
}
function checked(value: unknown): MCPReceipt {
  const row = value as MCPReceipt
  if (!row || typeof row.connectionId !== 'string' || !row.connectionId || typeof row.requestId !== 'string' || !/^[A-Za-z0-9_.:-]{1,128}$/.test(row.requestId) || typeof row.toolName !== 'string' || !row.toolName || !row.arguments || typeof row.arguments !== 'object' || Array.isArray(row.arguments)) throw new Error('MCP 恢复记录无法读取，请保留缓存并核验原请求。')
  const withModel = !!row.mapping?.model_parameter || row.mapping?.model !== undefined
  if (row.source && (!row.mapping || typeof row.source.content !== 'string' || !row.source.note_key || !row.source.source_version_id || !Number.isSafeInteger(row.source.base_revision) || row.source.base_revision < 1 || !['zh', 'en'].includes(row.mapping.target_language) || row.mapping.text_parameter === row.mapping.language_parameter || Object.keys(row.arguments).length !== (withModel ? 3 : 2) || row.arguments[row.mapping.text_parameter] !== row.source.content || row.arguments[row.mapping.language_parameter] !== row.mapping.target_language
    || (withModel && (row.toolName !== 'vinote_translate_text' || row.mapping.text_parameter !== 'text' || row.mapping.language_parameter !== 'target_language' || row.mapping.model_parameter !== 'model' || !row.mapping.model?.trim() || row.arguments.model !== row.mapping.model)))) throw new Error('MCP 恢复来源与参数不一致，请核验原请求。')
  if (row.status && !['awaiting_confirmation', 'running', 'succeeded', 'failed', 'unknown', 'cancelled'].includes(row.status)) throw new Error('MCP 恢复状态无法读取，请核验原请求。')
  if (row.saveBody && (!row.source || !row.saveBody.operation_id || row.saveBody.base_revision !== row.source.base_revision || row.saveBody.versions?.length !== 1 || row.saveBody.versions[0].content !== row.saveBody.content || row.saveBody.versions[0].parent_id !== row.source.source_version_id || row.saveBody.metadata?.default_version_id !== row.saveBody.versions[0].id)) throw new Error('保存恢复记录与原来源不一致，请保留译文并检查版本。')
  return { connectionId: row.connectionId, requestId: row.requestId, toolName: row.toolName, arguments: row.arguments, ...(row.source ? { source: row.source, mapping: row.mapping } : {}), ...(row.runId ? { runId: row.runId } : {}), saving: !!row.saving, saved: !!row.saved, ...(row.status ? { status: row.status } : {}), ...(row.saveBody ? { saveBody: row.saveBody } : {}) }
}
export function readMCPReceipts(owner: string): MCPReceipt[] {
  const raw = localStorage.getItem(mcpRecoveryKey(owner))
  if (!raw) return []
  let rows: unknown
  try { rows = JSON.parse(raw) } catch { throw new Error('MCP 恢复记录无法读取，请保留缓存并核验原请求。') }
  if (!Array.isArray(rows)) throw new Error('MCP 恢复记录无法读取，请保留缓存并核验原请求。')
  const receipts = rows.map(checked)
  if (new Set(receipts.map(row => row.requestId)).size !== receipts.length) throw new Error('MCP 恢复记录重复，请保留缓存。')
  return receipts
}
export function writeMCPReceipt(owner: string, value: MCPReceipt) {
  const row = checked(value), rows = readMCPReceipts(owner), previous = rows.find(item => item.requestId === row.requestId)
  if (previous && JSON.stringify([previous.connectionId, previous.toolName, previous.arguments, previous.source, previous.mapping]) !== JSON.stringify([row.connectionId, row.toolName, row.arguments, row.source, row.mapping])) throw new Error('原请求已固定，不能更换来源或参数。')
  if (previous?.saveBody && JSON.stringify(previous.saveBody) !== JSON.stringify(row.saveBody)) throw new Error('原保存操作已固定，请核验原版本。')
  localStorage.setItem(mcpRecoveryKey(owner), JSON.stringify([row, ...rows.filter(item => item.requestId !== row.requestId)]))
}
export function verifyMCPRun(receipt: MCPReceipt, run: TranslationRun) {
  if (run.requestId !== receipt.requestId || run.connectionId !== receipt.connectionId || run.toolName !== receipt.toolName || JSON.stringify(Object.entries(run.arguments).sort()) !== JSON.stringify(Object.entries(receipt.arguments).sort())) throw new Error('运行回执与原请求不一致，请保留并核验。')
  return { ...receipt, runId: run.id, status: run.status }
}
export const queryMCPRequest = (requestId: string) => apiJson<TranslationRun>(`${mcpBase}/runs/by-request/${encodeURIComponent(requestId)}`)
export function translationSaveBody(note: WorkspaceNote, receipt: MCPReceipt, run: TranslationRun): WorkspaceWrite {
  verifyMCPRun(receipt, run)
  const content = translationText(run), source = receipt.source
  if (!source || !receipt.mapping || !content || note.key !== source.note_key || note.deleted || note.revision !== source.base_revision || !note.versions.some(version => version.id === source.source_version_id && version.content === source.content)) throw new Error('源内容已变化或结果不完整，请保留译文并检查原文版本。')
  const version = { id: crypto.randomUUID(), title: note.title, content, created_at: new Date().toISOString(), kind: 'edit' as const, parent_id: source.source_version_id }
  return { operation_id: crypto.randomUUID(), base_revision: source.base_revision, title: note.title, content, source_type: note.source_type, source_device: note.source_device, metadata: { ...note.metadata, default_version_id: version.id }, versions: [version] }
}
