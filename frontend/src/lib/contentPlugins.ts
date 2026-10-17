import { apiJson } from './api'
import type { WorkspaceNote } from './workspace'
export type ContentPlugin = { id: string; name: string; description: string; option: 'language' | 'glossary' | 'none'; installed: boolean; enabled: boolean }
export type PluginRun = { id: string; plugin_id: string; note_key: string; status: string; output: string; error: string; model: string; base_revision: number; created_at: string }
export const pluginRunLabel = (status: string) => ({ running: '正在生成', interrupted: '处理中断', failed: '生成失败', ready: '待核对', saved: '已保存新版本' }[status] || '结果待核对')
export const pluginCatalog = () => apiJson<ContentPlugin[]>('/api/plugins')
export const pluginSetting = (id: string, installed: boolean, enabled = true) => apiJson<ContentPlugin[]>('/api/plugins/' + id, { method: 'PUT', body: JSON.stringify({ installed, enabled }) })
export const pluginRuns = () => apiJson<PluginRun[]>('/api/plugins/runs')
export const pluginRun = (id: string) => apiJson<PluginRun>('/api/plugins/runs/' + id)
export const previewPlugin = (body: { plugin_id: string; note_key: string; version_id: string; base_revision: number; operation_id: string; language: string; glossary: string }) => apiJson<PluginRun>('/api/plugins/runs', { method: 'POST', body: JSON.stringify(body) })
export const retryPlugin = (id: string) => apiJson<PluginRun>(`/api/plugins/runs/${id}/retry`, { method: 'POST' })
export const savePlugin = (id: string) => apiJson<WorkspaceNote>(`/api/plugins/runs/${id}/save`, { method: 'POST' })
