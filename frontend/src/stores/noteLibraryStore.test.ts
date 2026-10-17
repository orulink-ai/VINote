import { beforeEach, describe, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ json: vi.fn() }))
vi.mock('../lib/api', () => ({ apiJson: api.json }))
import { useNoteLibraryStore } from './noteLibraryStore'
const row = { id: 'a-note', title: 'A private note', content: 'Private', status: 'done', scope: 'personal', team_id: null, team_name: null, video_url: null, task_id: null, source_type: 'text', created_at: '2026-10-11', updated_at: '2026-10-11' }
describe('library response ownership', () => {
  beforeEach(() => { vi.clearAllMocks(); useNoteLibraryStore.getState().reset() })
  it('discards the old account list after reset', async () => {
    let resolve!: (value: unknown) => void
    api.json.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const request = useNoteLibraryStore.getState().loadNotes()
    useNoteLibraryStore.getState().reset()
    resolve([row]); await request
    expect(useNoteLibraryStore.getState().notes).toEqual([])
  })
  it('never returns a previous account detail to a new consumer', async () => {
    let resolve!: (value: unknown) => void
    api.json.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const request = useNoteLibraryStore.getState().loadNoteById(row.id)
    useNoteLibraryStore.getState().reset()
    resolve(row)
    expect(await request).toBeNull()
    expect(useNoteLibraryStore.getState().notes).toEqual([])
  })
  it('retains the most recently selected workspace when responses arrive out of order', async () => {
    let resolve!: (value: unknown) => void
    api.json.mockImplementationOnce(() => new Promise(done => { resolve = done })).mockResolvedValueOnce([])
    const personal = useNoteLibraryStore.getState().loadNotes()
    await useNoteLibraryStore.getState().loadNotes({ scope: 'team', teamId: 'team-b' })
    resolve([row]); await personal
    expect(useNoteLibraryStore.getState().notes).toEqual([])
  })
})
