import { act, cleanup, fireEvent, render, screen, waitFor, } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { contentPluginRecoveryKey, readContentPluginReceipts, writeContentPluginReceipt, type ContentPluginReceipt } from '@/lib/contentPluginRecovery'

const api = vi.hoisted(() => ({ catalog: vi.fn(), runs: vi.fn(), get: vi.fn(), preview: vi.fn(), retry: vi.fn(), save: vi.fn(), setting: vi.fn(), detail: vi.fn() }))
vi.mock('@/lib/contentPlugins', () => ({
  pluginCatalog: api.catalog, pluginRuns: api.runs, pluginRun: api.get,
  previewPlugin: api.preview, retryPlugin: api.retry, savePlugin: api.save, pluginSetting: api.setting,
  pluginRunLabel: (status: string) => ({ ready: '待核对', saved: '已保存新版本', failed: '生成失败', running: '正在生成', interrupted: '处理中断' }[status] || '待核验'),
}))
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand')
  return { useAuthStore: create(() => ({ user: { id: 'owner-a' } })) }
})
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand')
  return { useWorkspaceStore: create(() => ({ owner: 'owner-a', items: [{ key: 'note-a', title: '原始笔记', deleted: false }], pending: [], loadDetail: api.detail })) }
})
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <div>{content}</div> }))

import { useAuthStore } from '@/stores/authStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { Connections } from './Connections'

const catalog = [{ id: 'actions', name: '行动项整理', option: 'none', description: '翻译完整版本', installed: true, enabled: true }]
const receipt: ContentPluginReceipt = { request: { operation_id: 'original-operation', plugin_id: 'actions', note_key: 'note-a', version_id: 'original-version', base_revision: 3, language: 'zh', glossary: '' }, phase: 'submitted', created_at: '2026-10-12T00:00:00Z' }
const note = { key: 'note-a', title: '原始笔记', revision: 3, deleted: false, metadata: { default_version_id: 'original-version' }, versions: [{ id: 'original-version', title: '已保存原文', content: '原文内容', created_at: '2026-10-12T00:00:00Z' }] }
const ready = { id: 'original-operation', plugin_id: 'actions', note_key: 'note-a', status: 'ready', output: '图表结果', source_content: '固定原文内容', source_version_id: 'original-version', source_title: '原始笔记', language: 'zh', base_revision: 3, model: 'model', error: '', retry_safe: false, created_at: receipt.created_at }

beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear()
  useAuthStore.setState({ user: { id: 'owner-a' } } as never)
  useWorkspaceStore.setState({ owner: 'owner-a', pending: [], items: [{ key: 'note-a', title: '原始笔记', deleted: false }] } as never)
  api.catalog.mockResolvedValue(catalog); api.runs.mockResolvedValue([]); api.detail.mockResolvedValue(note); api.get.mockResolvedValue(ready)
  api.preview.mockImplementation(async body => ({ ...ready, id: body.operation_id, language: body.language }))
  api.save.mockResolvedValue({ ...note, revision: 4, content: '图表结果' })
})
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })
function mount() { return render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Connections /></MemoryRouter>) }
async function choose() {
  fireEvent.click(await screen.findByRole('button', { name: '选择内容' }))
  fireEvent.change(screen.getByLabelText('处理哪份内容'), { target: { value: 'note-a' } })
  await waitFor(() => expect(screen.getByRole('button', { name: '生成预览' })).toBeEnabled())
}

it('persists the exact diagram owner/source request before POST without an internal translation form', async () => {
  api.preview.mockImplementation(async body => {
    expect(readContentPluginReceipts('owner-a')[0].request).toEqual(body)
    return { ...ready, id: body.operation_id, language: body.language }
  })
  mount(); await choose()
  expect(screen.queryByLabelText('目标语言')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
  await screen.findByText('图表结果')
  expect(api.preview).toHaveBeenCalledTimes(1)
  expect(api.preview.mock.calls[0][0]).toMatchObject({ version_id: 'original-version', base_revision: 3, language: 'en' })
  expect(screen.getByText(/保存后作为当前版本/)).toHaveTextContent('不会发布到飞书或发送通知')
})

it('re-enters by GET of the original operation and compares the frozen source, never current body', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  api.detail.mockResolvedValue({ ...note, content: '后来改写的正文', metadata: { default_version_id: 'latest' }, versions: [{ id: 'latest', title: '最新版', content: '后来改写的正文', created_at: receipt.created_at }] })
  mount()
  await screen.findByText('图表结果')
  fireEvent.click(screen.getByRole('button', { name: '原文' }))
  expect(screen.getByText('固定原文内容')).toBeVisible()
  expect(screen.queryByText('后来改写的正文')).not.toBeInTheDocument()
  expect(api.get).toHaveBeenCalledWith('original-operation')
  expect(api.preview).not.toHaveBeenCalled()
  expect(readContentPluginReceipts('owner-a')[0].request.version_id).toBe('original-version')
})

it('does not POST when durable storage fails', async () => {
  mount(); await choose()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('本地存储已满') })
  fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
  await screen.findByText('本地存储已满')
  expect(api.preview).not.toHaveBeenCalled()
})

it('keeps an unknown submission across unmount and a GET 404 without inventing a new POST', async () => {
  api.preview.mockRejectedValue(new Error('结果未知'))
  const view = mount(); await choose()
  fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
  await screen.findByText('结果未知')
  const saved = readContentPluginReceipts('owner-a')[0]
  expect(saved.phase).toBe('submitted')
  view.unmount(); api.get.mockRejectedValue(new Error('尚未查到原运行'))
  mount(); await screen.findByText('尚未查到原运行')
  expect(api.get).toHaveBeenLastCalledWith(saved.request.operation_id)
  expect(api.preview).toHaveBeenCalledTimes(1)
  expect(readContentPluginReceipts('owner-a')[0].request).toEqual(saved.request)
  expect(screen.getByRole('button', { name: '原处理待核验' })).toBeDisabled()
})

it('closing a ready preview neither saves nor loses the original recovery operation', async () => {
  writeContentPluginReceipt('owner-a', receipt); mount()
  await screen.findByText('图表结果')
  fireEvent.click(screen.getByRole('button', { name: '关闭预览' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(api.save).not.toHaveBeenCalled()
  expect(readContentPluginReceipts('owner-a')[0].request.operation_id).toBe('original-operation')
  fireEvent.click(screen.getByRole('button', { name: '选择内容' }))
  await screen.findByText('图表结果')
  expect(api.get).toHaveBeenCalledTimes(2)
  expect(api.preview).not.toHaveBeenCalled()
})

it('requires the server retry safety flag even for a failed run', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  api.get.mockResolvedValue({ ...ready, status: 'failed', output: '', retry_safe: false })
  mount()
  expect(await screen.findByRole('button', { name: '重试生成预览' })).toBeDisabled()
  expect(screen.getByText(/当前尚不能安全重试/)).toBeInTheDocument()
  expect(api.retry).not.toHaveBeenCalled()
})

it('explicitly retries only the same safe run, retaining its immutable request', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  api.get.mockResolvedValue({ ...ready, status: 'failed', output: '', retry_safe: true })
  api.retry.mockResolvedValue(ready)
  mount(); fireEvent.click(await screen.findByRole('button', { name: '重试生成预览' }))
  await screen.findByText('图表结果')
  expect(api.retry).toHaveBeenCalledWith('original-operation')
  expect(api.preview).not.toHaveBeenCalled()
  expect(readContentPluginReceipts('owner-a')[0].request).toEqual(receipt.request)
})

it('retains an uncertain save, disables resubmission until GET, and marks saved only on confirmation', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  api.save.mockRejectedValue(new Error('保存结果未知'))
  mount(); await screen.findByText('图表结果')
  fireEvent.click(screen.getByRole('button', { name: '核对无误，保存为新版本' }))
  await screen.findByText('保存结果未知')
  expect(readContentPluginReceipts('owner-a')[0].phase).toBe('saving')
  expect(screen.getByRole('button', { name: '核对无误，保存为新版本' })).toBeDisabled()
  api.get.mockResolvedValue({ ...ready, status: 'saved' })
  fireEvent.click(screen.getByRole('button', { name: '查询本次处理结果' }))
  await screen.findByText('新版本已保存，原文版本保留。')
  expect(api.save).toHaveBeenCalledTimes(1)
  expect(api.preview).not.toHaveBeenCalled()
})

it('drops the old account result even when switching away and back before it completes', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  let finish!: (value: typeof ready) => void
  api.get.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  mount(); await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1))
  await act(async () => useAuthStore.setState({ user: { id: 'owner-b' } } as never))
  api.get.mockRejectedValue(new Error('继续核验中'))
  await act(async () => useAuthStore.setState({ user: { id: 'owner-a' } } as never))
  await screen.findByText('继续核验中')
  await act(async () => finish(ready))
  expect(screen.queryByText('图表结果')).not.toBeInTheDocument()
  expect(readContentPluginReceipts('owner-b')).toEqual([])
})

it('does not replace corrupt recovery storage with a new generation', async () => {
  localStorage.setItem(contentPluginRecoveryKey('owner-a'), '{bad')
  mount(); await screen.findByText(/插件恢复记录无法读取/)
  fireEvent.click(await screen.findByRole('button', { name: '选择内容' }))
  expect(api.preview).not.toHaveBeenCalled()
  expect(localStorage.getItem(contentPluginRecoveryKey('owner-a'))).toBe('{bad')
})

it('prevents double submission and does not reopen a closed preview when the late result arrives', async () => {
  let finish!: (value: typeof ready) => void
  api.preview.mockReturnValue(new Promise(resolve => { finish = resolve }))
  mount(); await choose()
  const button = screen.getByRole('button', { name: '生成预览' })
  fireEvent.click(button); fireEvent.click(button)
  expect(api.preview).toHaveBeenCalledTimes(1)
  const body = api.preview.mock.calls[0][0]
  fireEvent.click(screen.getByRole('button', { name: '关闭预览' }))
  await act(async () => finish({ ...ready, id: body.operation_id, language: body.language }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(readContentPluginReceipts('owner-a')[0].phase).toBe('ready')
})

it('does not save a preview whose immutable server source is still unavailable', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  api.get.mockResolvedValue({ ...ready, source_content: undefined, source_version_id: undefined })
  mount(); await screen.findByText('图表结果')
  expect(screen.getByRole('button', { name: '核对无误，保存为新版本' })).toBeDisabled()
  expect(api.save).not.toHaveBeenCalled()
})

it('does not expose source choices from a workspace cache belonging to the previous owner', async () => {
  mount(); await screen.findByRole('button', { name: '选择内容' })
  await act(async () => useAuthStore.setState({ user: { id: 'owner-b' } } as never))
  fireEvent.click(await screen.findByRole('button', { name: '选择内容' }))
  expect(screen.queryByRole('option', { name: '原始笔记' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '生成预览' })).toBeDisabled()
  expect(api.preview).not.toHaveBeenCalled()
})

it('requires a real save receipt before claiming the new version is saved', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  api.save.mockResolvedValue(undefined)
  mount(); await screen.findByText('图表结果')
  fireEvent.click(screen.getByRole('button', { name: '核对无误，保存为新版本' }))
  await screen.findByText('保存回执尚未核验，请查询原运行。')
  expect(screen.queryByText('新版本已保存，原文版本保留。')).not.toBeInTheDocument()
  expect(readContentPluginReceipts('owner-a')[0].phase).toBe('saving')
})

it('does not reuse an obsolete failed receipt to retry again after a retry timeout', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  api.get.mockResolvedValue({ ...ready, status: 'failed', output: '', retry_safe: true })
  api.retry.mockRejectedValue(new Error('重试结果未知'))
  mount(); fireEvent.click(await screen.findByRole('button', { name: '重试生成预览' }))
  await screen.findByText('重试结果未知')
  expect(screen.getByRole('button', { name: '重试生成预览' })).toBeDisabled()
  expect(readContentPluginReceipts('owner-a')[0].phase).toBe('submitted')
  expect(api.retry).toHaveBeenCalledTimes(1)
  api.get.mockResolvedValue({ ...ready, status: 'running', output: '', retry_safe: false })
  fireEvent.click(screen.getByRole('button', { name: '查询本次处理结果' }))
  await waitFor(() => expect(readContentPluginReceipts('owner-a')[0].phase).toBe('running'))
  expect(api.retry).toHaveBeenCalledTimes(1)
})

it('a confirmed save retains the original and lets the next explicit operation select the new version', async () => {
  writeContentPluginReceipt('owner-a', receipt)
  const savedNote = { ...note, revision: 4, metadata: { default_version_id: 'translated-version' }, versions: [{ id: 'translated-version', title: '已保存译文', content: '图表结果', created_at: receipt.created_at }, ...note.versions] }
  api.save.mockResolvedValue(savedNote)
  api.preview.mockImplementation(async body => ({ ...ready, id: body.operation_id, source_version_id: body.version_id, base_revision: body.base_revision, language: body.language }))
  mount(); await screen.findByText('图表结果')
  fireEvent.click(screen.getByRole('button', { name: '核对无误，保存为新版本' }))
  await screen.findByText('新版本已保存，原文版本保留。')
  expect(readContentPluginReceipts('owner-a')[0].phase).toBe('saved')
  fireEvent.click(screen.getByRole('button', { name: '另选内容' }))
  expect(screen.getByLabelText('源版本')).toHaveValue('translated-version')
  fireEvent.click(screen.getByRole('button', { name: '生成预览' }))
  await waitFor(() => expect(api.preview).toHaveBeenCalledTimes(1))
  expect(api.preview.mock.calls[0][0]).toMatchObject({ version_id: 'translated-version', base_revision: 4 })
})

it('does not offer an internal translation even if an older catalog still contains it', async () => {
  api.catalog.mockResolvedValue([{ ...catalog[0], id: 'translation', name: '全文翻译', option: 'language' }]); mount(); await screen.findByText(/探索内置插件/); await waitFor(() => expect(api.catalog).toHaveBeenCalled()); expect(screen.queryByRole('button', { name: '选择内容' })).not.toBeInTheDocument(); expect(screen.getByRole('link', { name: /MCP 工具/ })).toHaveAttribute('href', '/settings/mcp'); expect(api.preview).not.toHaveBeenCalled();
})
