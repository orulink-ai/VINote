import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const calls = vi.hoisted(() => ({ sync: vi.fn(), initialize: vi.fn(), reset: vi.fn() }))
vi.mock('@/stores/authStore', async () => {
  const { create } = await import('zustand')
  return { useAuthStore: create(() => ({ user: { id: 'alice' } })) }
})
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand')
  return { useWorkspaceStore: create(() => ({ sync: calls.sync, initialize: calls.initialize, reset: calls.reset, itemSyncMode: (id: string) => id.startsWith('enabled') ? 'sync' : 'local' })) }
})
vi.mock('@/stores/noteLibraryStore', async () => {
  const { create } = await import('zustand')
  return { useNoteLibraryStore: create(() => ({ notes: [] })) }
})
import type { SyncOperation } from '@/stores/workspaceStore'
import { useNoteLibraryStore } from '@/stores/noteLibraryStore'
import { useAuthStore } from '@/stores/authStore'
import { WorkspaceSync, workspaceOperationState, workspaceSyncGroups } from './WorkspaceSync'

const op = (key: string, locallyQueued?: boolean): SyncOperation => ({ key, locallyQueued, body: { operation_id: key, base_revision: 0, title: key, content: '真实本机正文', source_type: 'text', source_device: 'desktop' } })
beforeEach(() => {
  vi.clearAllMocks(); vi.useFakeTimers(); calls.initialize.mockResolvedValue(undefined)
  useAuthStore.setState({ user: { id: 'alice' } } as never)
  useNoteLibraryStore.setState({ notes: [] })
})
afterEach(() => { cleanup(); vi.useRealTimers() })

it('requires a known never-dispatched flag before showing a saved local draft or an enabled send queue', () => {
  expect(workspaceOperationState(op('local', true), 'local')).toBe('local')
  expect(workspaceOperationState(op('enabled', true), 'sync')).toBe('queued')
  for (const mode of ['local', 'sync'] as const) {
    expect(workspaceOperationState(op('unknown', false), mode)).toBe('unknown')
    expect(workspaceOperationState(op('legacy-unknown'), mode)).toBe('unknown')
  }
})
it('excludes normal paused drafts from action counts and leaves deleted drafts in trash only', () => {
  const queued = op('enabled', true), local = op('local', true), deleted = op('deleted', true), unknown = op('unknown', false)
  const conflict = { ...op('conflict', false), conflict: { revision: 3 } as SyncOperation['conflict'] }
  const groups = workspaceSyncGroups([queued, local, deleted, unknown, conflict], id => id === 'enabled' ? 'sync' : 'local', id => id === 'deleted')
  expect(groups.local).toEqual([local]); expect(groups.queued).toEqual([queued]); expect(groups.unknown).toEqual([unknown]); expect(groups.conflict).toEqual([conflict])
  expect(groups.active).toEqual([queued, unknown, conflict])
})
it('does not schedule sync when only a new local library record changes', async () => {
  await act(async () => { render(<WorkspaceSync />) })
  calls.sync.mockClear()
  act(() => useNoteLibraryStore.setState({ notes: [{ id: 'local-a' }] as never }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  expect(calls.sync).not.toHaveBeenCalled()
  act(() => useNoteLibraryStore.setState({ notes: [...useNoteLibraryStore.getState().notes, { id: 'enabled-a' }] as never }))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  expect(calls.sync).toHaveBeenCalledTimes(1)
})
it('does not schedule a new account update with the previous owner callback', async () => {
  await act(async () => { render(<WorkspaceSync />) })
  calls.sync.mockClear()
  act(() => useNoteLibraryStore.setState({ notes: [{ id: 'enabled-a' }] as never }))
  act(() => useAuthStore.setState({ user: { id: 'bob' } } as never))
  await act(async () => vi.advanceTimersByTimeAsync(1600))
  // Only Bob's initialization may pull; Alice's scheduled library callback is canceled.
  expect(calls.sync).toHaveBeenCalledTimes(1)
  expect(calls.initialize).toHaveBeenLastCalledWith('bob')
})
