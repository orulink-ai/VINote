import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({
  local: [{ id: 'original', title: 'Same title', content: 'local', createdAt: '2026-10-10', updatedAt: '2026-10-10', taskId: 'task-original', status: 'pending' }],
  workspace: { items: [
    { key: 'desktop-original', title: 'Same title', created_at: '2026-10-10', updated_at: '2026-10-10' },
    { key: 'separate-note', title: 'Same title', created_at: '2026-10-10', updated_at: '2026-10-10' },
  ], details: {}, mappings: {}, pending: [] },
}))
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: (selector: Function) => selector({ notes: state.local }) }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: (selector: Function) => selector({ currentWorkspace: { scope: 'personal' } }) }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: () => state.workspace }))
import { useLibraryNotes } from './useLibraryNotes'
describe('library source identity', () => {
  it('merges the same source without a cached mapping and preserves unrelated same-title notes', () => {
    const { result } = renderHook(() => useLibraryNotes())
    expect(result.current).toHaveLength(2)
    expect(result.current.find(note => note.workspaceKey === 'desktop-original')).toMatchObject({ localId: 'original', taskId: 'task-original', status: 'pending' })
    expect(result.current.some(note => note.workspaceKey === 'separate-note')).toBe(true)
  })
})
