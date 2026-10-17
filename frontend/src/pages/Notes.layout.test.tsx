import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

const data = vi.hoisted(() => ({
  loadNotes: vi.fn(), load: vi.fn(), remove: vi.fn(),
  libraryError: '', loading: false,
  rows: [
    { id: 'ack', title: '已确认的笔记', syncLabel: '已同步', workspaceKey: 'ack' },
    { id: 'pending', title: '待处理笔记', syncLabel: '已保存 · 等待同步', workspaceKey: 'pending' },
    { id: 'conflict', title: '冲突笔记', syncLabel: '需要处理冲突', workspaceKey: 'conflict' },
    { id: 'unknown', title: '待核验笔记', syncLabel: '保存结果待核验', workspaceKey: 'unknown' },
    { id: 'local', title: '本机笔记', syncLabel: '仅本机保存', workspaceKey: '' },
  ].map(row => ({ ...row, project: '项目A', status: 'done', sourceType: 'file', content: '可阅读的原正文', createdAt: '2026-10-12', sourceDevice: 'desktop' })),
}))
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand')
  return { useWorkspaceStore: create(() => ({ owner: 'owner-layout', ready: true, busy: false, error: '', pending: [], mappings: {}, details: {}, items: [], itemPolicies: {}, itemSyncMode: (reference: string) => reference === 'local' ? 'local' : 'sync', loadDetail: data.load, changeDeleted: data.remove })) }
})
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand')
  return { useAuthStore: create(() => ({ user: { id: 'owner-layout' } })) }
})
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => ({ loading: data.loading, error: data.libraryError, loadNotes: data.loadNotes }) }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: () => ({ currentWorkspace: { scope: 'personal' } }) }))
vi.mock('@/hooks/useViewState', async () => { const { useState } = await import('react'); return { useViewState: (_name: string, initial: unknown) => useState(initial) } })
vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh', formatDate: () => '今天' }) }))
vi.mock('@/hooks/useLibraryNotes', () => ({ useLibraryNotes: () => data.rows, libraryNoteUrl: (note: { id: string }) => `/workspace/${note.id}` }))
import { Notes } from './Notes'
import { useWorkspaceStore } from '@/stores/workspaceStore'
const originalRows = data.rows.map(row => ({ ...row }))
beforeEach(() => { vi.clearAllMocks(); data.rows = originalRows.map(row => ({ ...row })); data.libraryError = ''; data.loading = false; useWorkspaceStore.setState({ error: '', pending: [
  { key: 'pending', locallyQueued: true, body: {} },
  { key: 'conflict', conflict: { revision: 2 }, body: {} },
  { key: 'unknown', body: {} },
] as never, busy: false }) })
afterEach(cleanup)
function Where() { const location = useLocation(); return <output aria-label="导航位置">{JSON.stringify({ path: location.pathname + location.search + location.hash, state: location.state })}</output> }
function mount(path = '/notes?project=项目A#results') { render(<MemoryRouter initialEntries={[path]}><Notes /><Where /></MemoryRouter>) }
const current = () => JSON.parse(screen.getByLabelText('导航位置').textContent || '{}')

it('retains both complete source entries, writing, readable rows and source navigation context', () => {
  mount()
  expect(screen.getByRole('link', { name: '写笔记' })).toBeInTheDocument()
  const sources = screen.getByRole('region', { name: '生成总结笔记' })
  expect(within(sources).getByText('B 站等公开视频、普通网页或公开文档 → 总结笔记')).toBeInTheDocument()
  expect(within(sources).getByText('PDF、Word、音视频或文字文件 → 总结笔记')).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: '文档与文字' })).toHaveAttribute('title', '文档与文字：网页文章、PDF、Word、文字与字幕笔记')
  expect(screen.getAllByRole('button', { name: /^编辑《/ })).toHaveLength(5)
  expect(screen.getAllByRole('button', { name: /^删除《/ })).toHaveLength(5)
  expect(document.querySelector('button button')).toBeNull()
  fireEvent.click(within(sources).getByRole('link', { name: /粘贴链接/ }))
  expect(current().path).toBe('/generate?mode=url')
  expect(decodeURIComponent(current().state.returnTo)).toBe('/notes?project=项目A#results')
  expect(data.remove).not.toHaveBeenCalled()
})
it('keeps every saved row readable without surfacing historical synchronization labels or gates', () => {
  mount()
  for (const row of data.rows) expect(screen.getByRole('button', { name: `${row.title} · 已保存` })).toBeEnabled()
  for (const row of data.rows) expect(screen.queryByText(row.syncLabel, { exact: true })).not.toBeInTheDocument()
  expect(screen.queryByRole('switch')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '检查同步' })).not.toBeInTheDocument()
  expect(data.load).not.toHaveBeenCalled(); expect(data.remove).not.toHaveBeenCalled()
})
it('explicitly reloads a cached read failure while preserving the current filters and rows', () => {
  data.libraryError = '列表读取中断，已有资料保留'; mount()
  fireEvent.click(screen.getByRole('button', { name: '查看原因' }))
  expect(screen.getByText(data.libraryError, { exact: false })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
  expect(data.loadNotes).toHaveBeenLastCalledWith({ scope: 'personal' })
  expect(decodeURIComponent(current().path)).toBe('/notes?project=项目A#results')
  expect(screen.getAllByRole('button', { name: /^删除《/ })).toHaveLength(5)
  expect(data.load).not.toHaveBeenCalled(); expect(data.remove).not.toHaveBeenCalled()
})
it('canceling local trash preserves the same parent and filters without requiring sync', async () => {
  mount()
  fireEvent.click(screen.getByRole('button', { name: '删除《本机笔记》' }))
  expect(screen.getByRole('alertdialog')).toHaveTextContent('原文件与已发布飞书文档保留')
  fireEvent.click(screen.getByRole('button', { name: '保留笔记' }))
  expect(decodeURIComponent(current().path)).toBe('/notes?project=项目A#results')
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(data.remove).not.toHaveBeenCalled()
})
it('archive keeps browsing and restore responsibilities without duplicating generation entries', () => {
  mount('/notes?archived=1')
  expect(screen.queryByRole('region', { name: '生成总结笔记' })).not.toBeInTheDocument()
  expect(screen.getByRole('tab', { name: '未归档' })).toBeInTheDocument()
  expect(screen.getByText('没有归档内容')).toBeInTheDocument()
  expect(screen.getByText('归档的内容会显示在这里；切换到未归档可继续浏览当前笔记。')).toBeInTheDocument()
})

it('keeps cached update feedback in the same browsing slot and reveals the complete cause only on request', () => {
  mount()
  const slot = screen.getByLabelText('列表数量与读取状态')
  const first = screen.getByRole('button', { name: '已确认的笔记 · 已保存' })
  act(() => useWorkspaceStore.setState({ error: '原同步请求的完整核验原因，保留读取上下文' }))
  expect(screen.getByLabelText('列表数量与读取状态')).toBe(slot)
  expect(screen.getByRole('button', { name: '已确认的笔记 · 已保存' })).toBe(first)
  expect(within(slot).getByRole('status')).toHaveTextContent('列表读取未完成')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText('原同步请求的完整核验原因，保留读取上下文')).not.toBeInTheDocument()
  fireEvent.click(within(slot).getByRole('button', { name: '查看原因' }))
  expect(screen.getByText('原同步请求的完整核验原因，保留读取上下文', { exact: false })).toBeInTheDocument()
  fireEvent.click(within(slot).getByRole('button', { name: '收起原因' }))
  expect(screen.queryByText('原同步请求的完整核验原因，保留读取上下文', { exact: false })).not.toBeInTheDocument()
  expect(data.remove).not.toHaveBeenCalled()
})

it('keeps a failed first read explicit rather than reporting an empty library', () => {
  data.rows = []; data.libraryError = '首读未完成，重新读取原列表'
  mount('/notes')
  expect(screen.getByRole('alert')).toHaveTextContent(data.libraryError)
  expect(screen.getByText('数量待核验')).toBeInTheDocument()
  expect(screen.queryByText('还没有保存的笔记')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
  expect(data.loadNotes).toHaveBeenCalledTimes(2)
})

it('distinguishes same-title records by reliable source saving times without dropping records', () => {
  data.rows[0] = { ...data.rows[0], title: '同名.docx', createdAt: '2026-10-12T01:02:03Z' }
  data.rows[1] = { ...data.rows[1], title: '同名.docx', createdAt: '2026-10-12T02:04:05Z' }
  mount()
  const formatter = new Intl.DateTimeFormat('zh', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
  const [first, second] = screen.getAllByRole('button', { name: '同名.docx · 已保存' })
  expect(first).toHaveTextContent(formatter.format(new Date(data.rows[0].createdAt)))
  expect(second).toHaveTextContent(formatter.format(new Date(data.rows[1].createdAt)))
  expect(screen.getAllByRole('button', { name: '删除《同名.docx》' })).toHaveLength(2)
})
