import { beforeEach, describe, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ json: vi.fn() }))
vi.mock('../lib/api', () => ({ apiJson: api.json }))
import { useNoteLibraryStore } from './noteLibraryStore'
const row = { id: 'a-note', title: 'A private note', content: 'Private', status: 'done', scope: 'personal', team_id: null, team_name: null, video_url: null, task_id: null, source_type: 'text', created_at: '2026-10-11', updated_at: '2026-10-11' }
describe('library response ownership', () => {
  beforeEach(() => { vi.clearAllMocks(); useNoteLibraryStore.getState().reset() })
  it('keeps video-link provenance separate from its retained audio playback kind', async () => {
    api.json.mockResolvedValueOnce({ ...row, source_type: 'video', media_kind: 'audio', task_id: 'task-a' })
    const note = await useNoteLibraryStore.getState().loadNoteById(row.id)
    expect(note).toMatchObject({ sourceType: 'video', mediaKind: 'audio', taskId: 'task-a' })
  })
  it('refreshes media detail omitted by the list before reopening a cached video-link note', async () => {
    const cached = { id: row.id, title: row.title, content: row.content, status: 'done', scope: 'personal' as const,
      createdAt: row.created_at, updatedAt: row.updated_at, sourceType: 'video', taskId: 'task-a' }
    useNoteLibraryStore.setState({ notes: [cached] })
    api.json.mockResolvedValueOnce({ ...row, source_type: 'video', media_kind: 'audio', task_id: 'task-a' })
    const note = await useNoteLibraryStore.getState().loadNoteById(row.id)
    expect(api.json).toHaveBeenCalledWith(`/api/notes/${row.id}`)
    expect(note?.mediaKind).toBe('audio')
    expect(useNoteLibraryStore.getState().notes).toHaveLength(1)
    expect(useNoteLibraryStore.getState().notes[0].mediaKind).toBe('audio')
  })
  it.each([0, 401, 403, 404])('retains cached text only for a transport outage, not an access rejection (%s)', async status => {
    const cached = { id: row.id, title: row.title, content: row.content, status: 'done', scope: 'personal' as const,
      createdAt: row.created_at, updatedAt: row.updated_at, sourceType: 'video', taskId: 'task-a' }
    useNoteLibraryStore.setState({ notes: [cached] })
    api.json.mockRejectedValueOnce(Object.assign(new Error('read failed'), status ? { status } : {}))
    const note = await useNoteLibraryStore.getState().loadNoteById(row.id)
    expect(note).toEqual(status ? null : cached)
    expect(useNoteLibraryStore.getState().error).toBe('read failed')
  })
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
