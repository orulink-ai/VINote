import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ disable: vi.fn(), status: vi.fn(), catalog: vi.fn(), runs: vi.fn(), run: vi.fn(), preview: vi.fn(), retry: vi.fn(), detail: vi.fn() }))
vi.mock('@/lib/feishu', () => ({ feishuStatus: api.status, disableDeviceAutomaticDelivery: api.disable }))
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand')
  return { useAuthStore: create(() => ({ user: { id: 'a' } })) }
})
vi.mock('@/lib/contentPlugins', () => ({ pluginCatalog: api.catalog, pluginRuns: api.runs, pluginRun: api.run, previewPlugin: api.preview, retryPlugin: api.retry, pluginSetting: vi.fn(), savePlugin: vi.fn(), pluginRunLabel: (status: string) => status }))
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand')
  return { useWorkspaceStore: create(() => ({ owner: 'a', items: [], pending: [], loadDetail: api.detail })) }
})
vi.mock('@/components/Markdown/MarkdownContent', () => ({ MarkdownContent: ({ content }: { content: string }) => <div>{content}</div> }))
import { Connections } from '@/pages/Connections'
import { useAuthStore } from '@/stores/authStore'
import { ConnectorPluginStore } from './ConnectorPluginStore'
import { connectorPluginKey } from '@/lib/connectorPlugins'
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); api.disable.mockResolvedValue({ legacy: false }); api.status.mockResolvedValue({ connected: true }); useAuthStore.setState({ user: { id: 'a' } } as never) })
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function mount(owner = 'a') { return render(<MemoryRouter><ConnectorPluginStore owner={owner} returnTo="/connections?note=original" /></MemoryRouter>) }
it('installs only on successful persistence, disables, returns with durable state and searches', async () => {
  const view = mount()
  await screen.findByText('已有飞书授权，可直接管理；商店模块尚未安装。')
  fireEvent.click(screen.getByRole('button', { name: '安装', exact: true }))
  await screen.findByText('已启用')
  fireEvent.click(screen.getByRole('button', { name: '停用', exact: true }))
  await screen.findByText('已停用')
  view.unmount(); mount()
  await screen.findByText('已停用')
  fireEvent.change(screen.getByLabelText('搜索插件'), { target: { value: 'absent' } })
  await screen.findByText('没有匹配的插件')
  fireEvent.click(screen.getByRole('button', { name: '清除搜索' }))
  expect(screen.getByRole('link', { name: '管理', exact: true })).toHaveAttribute('href', '/settings/feishu')
})
it('retains uninstalled state when storage fails and retries the same installation', async () => {
  mount(); await screen.findByText('未安装')
  vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota') })
  fireEvent.click(screen.getByRole('button', { name: '安装', exact: true }))
  await screen.findByText('安装设置未能保存，原状态保留。请重试。')
  expect(screen.getByText('未安装')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重试', exact: true }))
  await screen.findByText('已启用')
})
it('stops device automatic delivery before persisting disabled plugin state', async () => {
  localStorage.setItem(connectorPluginKey('a'), JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }))
  let finish!: (value: { legacy: boolean }) => void
  api.disable.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  mount(); await screen.findByText('已启用'); fireEvent.click(screen.getByRole('button', { name: '停用', exact: true }))
  expect(api.disable).toHaveBeenCalledExactlyOnceWith('a')
  expect(JSON.parse(localStorage.getItem(connectorPluginKey('a'))!).feishu.enabled).toBe(true)
  await act(async () => finish({ legacy: false })); await screen.findByText('已停用')
  expect(JSON.parse(localStorage.getItem(connectorPluginKey('a'))!).feishu.enabled).toBe(false)
})
it('device-stop failure keeps plugin enabled and retries without claiming it stopped', async () => {
  localStorage.setItem(connectorPluginKey('a'), JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }))
  api.disable.mockRejectedValueOnce(new Error('设备关闭接口暂不可用')).mockResolvedValueOnce({ legacy: false })
  mount(); await screen.findByText('已启用'); fireEvent.click(screen.getByRole('button', { name: '停用', exact: true }))
  await screen.findByText(/设备关闭接口暂不可用/)
  expect(JSON.parse(localStorage.getItem(connectorPluginKey('a'))!).feishu.enabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重试', exact: true })); await screen.findByText('已停用')
})
it('old-owner device stop acknowledgement cannot persist state after an account switch', async () => {
  localStorage.setItem(connectorPluginKey('a'), JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }))
  let finish!: (value: { legacy: boolean }) => void
  api.disable.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  const view = mount(); await screen.findByText('已启用'); fireEvent.click(screen.getByRole('button', { name: '停用', exact: true }))
  act(() => useAuthStore.setState({ user: { id: 'b' } } as never))
  view.rerender(<MemoryRouter><ConnectorPluginStore owner="b" returnTo="/connections" /></MemoryRouter>)
  await act(async () => finish({ legacy: false })); await screen.findByText('未安装')
  expect(localStorage.getItem(connectorPluginKey('b'))).toBeNull()
  expect(JSON.parse(localStorage.getItem(connectorPluginKey('a'))!).feishu.enabled).toBe(true)
})
it('uninstall also stops device delivery and keeps authorization and documents untouched', async () => {
  localStorage.setItem(connectorPluginKey('a'), JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }))
  mount(); await screen.findByText('已启用'); fireEvent.click(screen.getByRole('button', { name: '卸载', exact: true })); await screen.findByText('未安装')
  expect(api.disable).toHaveBeenCalledExactlyOnceWith('a'); expect(JSON.parse(localStorage.getItem(connectorPluginKey('a'))!).feishu).toEqual({ installed: false, enabled: false })
  expect(screen.getByText(/服务已受理的原任务继续保留/)).toBeVisible()
})
it('ordinary plugin installation does not enable automatic delivery', async () => {
  mount(); await screen.findByText('未安装'); fireEvent.click(screen.getByRole('button', { name: '安装', exact: true })); await screen.findByText('已启用')
  expect(api.disable).not.toHaveBeenCalled(); expect(JSON.parse(localStorage.getItem(connectorPluginKey('a'))!).feishu).toEqual({ installed: true, enabled: true })
})
it('legacy fallback can disable the plugin but does not claim device stop was confirmed', async () => {
  localStorage.setItem(connectorPluginKey('a'), JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }))
  api.disable.mockResolvedValueOnce({ legacy: true }); mount(); await screen.findByText('已启用')
  fireEvent.click(screen.getByRole('button', { name: '停用', exact: true })); await screen.findByText('已停用')
  expect(screen.getByText(/当前服务未提供自动交付协议，未确认设备关闭接口/)).toBeVisible()
  expect(screen.queryByText(/新的设备自动交付已停止/)).toBeNull()
})
it('a late ABA stop response cannot overwrite the current visit installation state', async () => {
  localStorage.setItem(connectorPluginKey('a'), JSON.stringify({ version: 1, feishu: { installed: true, enabled: true } }))
  let finish!: (value: { legacy: boolean }) => void
  api.disable.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  mount(); await screen.findByText('已启用'); fireEvent.click(screen.getByRole('button', { name: '停用', exact: true }))
  act(() => { useAuthStore.setState({ user: { id: 'b' } } as never); useAuthStore.setState({ user: { id: 'a' } } as never) })
  await act(async () => finish({ legacy: false })); await screen.findByText('已启用')
  expect(JSON.parse(localStorage.getItem(connectorPluginKey('a'))!).feishu.enabled).toBe(true)
})
it('does not treat unreadable installation data as an empty installed list', async () => {
  localStorage.setItem(connectorPluginKey('a'), '{invalid')
  mount(); await screen.findByText('安装状态无法读取，请重试；不会覆盖已有设置。')
  expect(screen.queryByRole('button', { name: '安装', exact: true })).not.toBeInTheDocument()
  localStorage.removeItem(connectorPluginKey('a'))
  fireEvent.click(screen.getByRole('button', { name: '重试', exact: true }))
  await screen.findByText('未安装')
})
it('ignores late authorization response after switching accounts', async () => {
  let resolve!: (value: { connected: boolean }) => void
  api.status.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const view = mount(); await screen.findByText('未安装')
  act(() => useAuthStore.setState({ user: { id: 'b' } } as never))
  api.status.mockResolvedValue({ connected: false })
  view.rerender(<MemoryRouter><ConnectorPluginStore key="b" owner="b" returnTo="/connections" /></MemoryRouter>)
  await act(async () => { resolve({ connected: true }) })
  expect(screen.queryByText('已有飞书授权，可直接管理；商店模块尚未安装。')).not.toBeInTheDocument()
})

it('discards an old response after switching away and back and keeps current controls usable', async () => {
  let resolve!: (value: { connected: boolean }) => void
  api.status.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  mount(); await screen.findByText('未安装')
  api.status.mockResolvedValue({ connected: false })
  act(() => {
    useAuthStore.setState({ user: { id: 'b' } } as never)
    useAuthStore.setState({ user: { id: 'a' } } as never)
  })
  await act(async () => resolve({ connected: true }))
  expect(screen.queryByText('已有飞书授权，可直接管理；商店模块尚未安装。')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '安装', exact: true }))
  await screen.findByText('已启用')
})

it('hides diagram generation but keeps the original historical run and frozen result reachable', async () => {
  api.catalog.mockResolvedValue([{ id: 'diagram', name: '流程图整理', description: '历史', installed: true, enabled: true, option: 'none' }])
  const historical = { id: 'original-diagram', plugin_id: 'diagram', note_key: 'note', status: 'ready', source_title: '原纪要', source_content: '固定原文', source_version_id: 'original', output: '历史图表结果', language: 'zh', base_revision: 1, retry_safe: true, model: 'original-model', error: '', created_at: '2026-10-12T00:00:00Z' }
  api.runs.mockResolvedValue([historical]); api.run.mockResolvedValue(historical)
  api.detail.mockResolvedValue({ key: 'note', title: '原纪要', revision: 2, metadata: {}, versions: [] })
  render(<MemoryRouter><Connections /></MemoryRouter>)
  const history = await screen.findByRole('button', { name: /流程图整理 · 已保存内容/ })
  expect(screen.queryByRole('button', { name: '选择内容' })).not.toBeInTheDocument()
  fireEvent.click(history)
  await screen.findByText('历史图表结果')
  expect(screen.getByText('固定原文')).toBeInTheDocument()
  expect(api.run).toHaveBeenCalledWith('original-diagram')
  expect(screen.queryByRole('button', { name: '生成预览' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '重试生成预览' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '另选内容' })).not.toBeInTheDocument()
  expect(api.preview).not.toHaveBeenCalled(); expect(api.retry).not.toHaveBeenCalled()
})
