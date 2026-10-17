import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
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
function Destination() {
  const location = useLocation();
  return <output aria-label="存储目标">{location.pathname + location.search}</output>
}
async function mount(parent = '/files?note=real-note') {
  await act(async () => { render(<MemoryRouter initialEntries={['/tasks?' + new URLSearchParams({ tab: 'sync', returnTo: parent })]}><Routes>
    <Route path="/tasks" element={<Tasks />} />
    <Route path="/settings/storage" element={<Destination />} />
  </Routes></MemoryRouter>) })
}
function noDispatch() {
  expect(api.json).not.toHaveBeenCalled(); expect(api.sync).not.toHaveBeenCalled()
}
it('redirects the historical sync URL to storage without dispatching or rewriting retained operations', async () => {
  const pending = [op('local', true), op('enabled', true), op('unknown', false), op('legacy-unknown')]
  useWorkspaceStore.setState({ pending }); await mount()
  const target = new URL(screen.getByLabelText('存储目标').textContent!, 'https://vinote.invalid')
  expect(target.pathname).toBe('/settings/storage')
  expect(target.searchParams.get('returnTo')).toBe('/files?note=real-note')
  expect(useWorkspaceStore.getState().pending).toBe(pending)
  expect(screen.queryByText(/待发送|待核验|同步失败/)).not.toBeInTheDocument(); noDispatch()
})
it('does not gate legacy navigation on cache readiness or fabricate empty sync counts', async () => {
  const pending = [op('local', true)]
  useWorkspaceStore.setState({ ready: false, pending, items: [{ key: 'local', deleted: true } as never] }); await mount('/notes?project=kept&archived=1')
  expect(new URL(screen.getByLabelText('存储目标').textContent!, 'https://vinote.invalid').searchParams.get('returnTo')).toBe('/notes?project=kept&archived=1')
  expect(screen.queryByText(/正在读取同步|待发送 0|没有待处理同步/)).not.toBeInTheDocument()
  expect(useWorkspaceStore.getState().pending).toBe(pending); noDispatch()
})
it('rejects an external return target on the historical link', async () => {
  await mount('https://untrusted.invalid/notes')
  expect(new URL(screen.getByLabelText('存储目标').textContent!, 'https://vinote.invalid').searchParams.get('returnTo')).toBe('/notes'); noDispatch()
})
