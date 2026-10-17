import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
const api = vi.hoisted(() => ({ json: vi.fn(), sync: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiJson: api.json }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 'owner' } }) }))
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand')
  return { useWorkspaceStore: create(() => ({ ready: true, busy: false, details: {}, items: [], pending: [], sync: api.sync, itemSyncMode: (key: string) => key === 'enabled' ? 'sync' : 'local' })) }
})
vi.mock('@/hooks/useLibraryNotes', () => ({ useLibraryNotes: () => [], libraryNoteUrl: () => '/notes' }))
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }))
vi.mock('@/lib/feishu', () => ({ deliveryStatus: vi.fn() }))
vi.mock('@/lib/mcpConnections', () => ({ listMCPRuns: vi.fn(), mcpRunLabel: {} }))
import { useWorkspaceStore, type SyncOperation } from '@/stores/workspaceStore'
import { Tasks } from './Tasks'

const op = (key: string, locallyQueued?: boolean): SyncOperation => ({ key, locallyQueued, body: { operation_id: key, title: key, content: '保留本机稿', base_revision: 0, source_type: 'text', source_device: 'desktop' } })
beforeEach(() => { vi.clearAllMocks(); useWorkspaceStore.setState({ ready: true, busy: false, pending: [], details: {}, items: [] }) })
afterEach(cleanup)
async function mount() { await act(async () => { render(<MemoryRouter initialEntries={['/tasks?tab=sync&returnTo=%2Ffiles%3Fnote%3Dreal-note']}><Tasks /></MemoryRouter>) }) }

it('separates local saved content, enabled never-sent content and unknown legacy results without replay language', async () => {
  useWorkspaceStore.setState({ pending: [op('local', true), op('enabled', true), op('unknown', false), op('legacy-unknown')] })
  await mount()
  expect(screen.getByText(/待发送 1 · 待核验 2 · 需核对 0/)).toBeInTheDocument()
  expect(screen.getByText('仅本机保存 · 1')).toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: '核验原结果' })).toHaveLength(2)
  const unknown = new URL(screen.getAllByRole('link', { name: '核验原结果' })[0].getAttribute('href')!, 'https://vinote.invalid')
  expect(unknown.searchParams.get('operation')).toBe('unknown')
  expect(unknown.searchParams.get('returnTo')).toBe('/tasks?tab=sync&returnTo=%2Ffiles%3Fnote%3Dreal-note')
  expect(screen.queryByText(/重试原请求|同步失败/)).not.toBeInTheDocument()
  expect(api.json).not.toHaveBeenCalled(); expect(api.sync).not.toHaveBeenCalled()
})
it('reports a purely local save as normal and sends no request until a user explicitly refreshes shared state', async () => {
  useWorkspaceStore.setState({ pending: [op('local', true)] }); await mount()
  expect(screen.getByText(/没有待处理同步/)).toBeInTheDocument()
  expect(screen.queryByText(/等待同步|等待发送|待写入/)).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: '核验原结果' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  expect(api.sync).toHaveBeenCalledTimes(1); expect(api.json).not.toHaveBeenCalled()
  expect(useWorkspaceStore.getState().pending[0].locallyQueued).toBe(true)
})
it('does not display false zero counts while records are not ready, and hides deleted local drafts from normal content', async () => {
  useWorkspaceStore.setState({ ready: false, pending: [op('local', true)], items: [{ key: 'local', deleted: true } as never] }); await mount()
  expect(screen.getByText(/正在读取同步记录/)).toBeInTheDocument()
  expect(screen.queryByText(/待发送 0|没有待处理同步|仅本机保存 · 1/)).not.toBeInTheDocument()
  act(() => useWorkspaceStore.setState({ ready: true }))
  expect(screen.queryByText('仅本机保存 · 1')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /返回文件库/ })).toHaveAttribute('href', '/files?note=real-note')
})
