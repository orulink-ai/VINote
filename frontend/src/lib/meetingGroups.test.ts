import { expect, it, vi } from 'vitest'
import type { LibraryNote } from '@/hooks/useLibraryNotes'
import type { PendingMeeting } from './audioStorage'
import { buildMeetingRows } from './meetingGroups'
const api = vi.hoisted(() => ({ json: vi.fn() }))
vi.mock('./api', () => ({ apiJson: api.json }))
import { useNoteLibraryStore } from '@/stores/noteLibraryStore'

const source = (task = 'original', owner = 'owner-a') => ({ ownerId: owner, canonicalTaskId: task })
function note(id: string, extra: Partial<LibraryNote> & { meetingSource?: ReturnType<typeof source> } = {}): LibraryNote {
  return { id, title: '相同标题', content: '可读正文', scope: 'personal', status: 'done',
    createdAt: '2026-10-19T01:00:00Z', updatedAt: '2026-10-19T01:00:00Z', ...extra }
}
const recording = (ownerId = 'owner-a'): PendingMeeting => ({
  id: 'rec-a', taskId: 'original', ownerId, workspace: { scope: 'personal' }, options: { title: '原会议' },
  startedAt: '2026-10-18T01:00:00Z', elapsedSeconds: 50, recordingStatus: 'saved', processingStatus: 'completed',
} as PendingMeeting)

it('reproduces separate child tasks and groups summary-only/new generation with their canonical original', () => {
  const input = [note('first', { taskId: 'original', meetingSource: source() }),
    note('summary-only', { taskId: 'child-summary', meetingSource: source() }),
    note('new-generation', { taskId: 'child-asr', meetingSource: source() })]
  const before = JSON.stringify(input)
  const rows = buildMeetingRows([recording()], input)
  expect(rows).toHaveLength(1)
  expect(rows[0].notes.map(n => n.id).sort()).toEqual(['first', 'new-generation', 'summary-only'])
  expect(rows[0].recordings.map(r => r.id)).toEqual(['rec-a'])
  expect(JSON.stringify(input)).toBe(before)
})

it('defaults to the latest saved readable object, preserving older edits, unread and failed records', () => {
  const input = [note('old-edited', { taskId: 'same', updatedAt: '2026-10-20T10:00:00Z' }),
    note('latest-readable', { taskId: 'same', createdAt: '2026-10-20T01:00:00Z' }),
    note('pending', { taskId: 'same', status: 'pending', createdAt: '2026-10-20T03:00:00Z' }),
    note('unread', { taskId: 'same', content: '', createdAt: '2026-10-20T04:00:00Z' })]
  const rows = buildMeetingRows([], input)
  expect(rows[0].note?.id).toBe('latest-readable')
  expect(rows[0].notes).toHaveLength(4)
})

it('keeps same-title/time, unknown provenance, another owner and another workspace separate', () => {
  const rows = buildMeetingRows([], [note('a', { taskId: 'child-a', meetingSource: source() }),
    note('b', { taskId: 'child-b', meetingSource: source('other') }),
    note('unknown', { taskId: 'child-unknown' }),
    note('other-owner', { taskId: 'child-a', meetingSource: source('original', 'owner-b') }),
    note('other-team', { taskId: 'child-a', scope: 'team', teamId: 'team-b', meetingSource: source() })])
  expect(rows).toHaveLength(5)
})

it('does not attach a canonical relationship to a different owners recording', () => {
  expect(buildMeetingRows([recording('owner-b')], [note('a', { taskId: 'child', meetingSource: source() })])).toHaveLength(2)
})

const canonicalA = '11111111-1111-4111-8111-111111111111'
const canonicalB = '22222222-2222-4222-8222-222222222222'
const permutations = <T,>(items: T[]): T[][] => items.length ? items.flatMap((item, index) =>
  permutations(items.filter((_, other) => other !== index)).map(rest => [item, ...rest])) : [[]]
const memberships = (rows: ReturnType<typeof buildMeetingRows>) => rows.map(row =>
  [...row.notes.map(note => note.id), ...row.recordings.map(recording => recording.id)].sort()).sort((a, b) => a.join('|').localeCompare(b.join('|')))

it('never lets documented app aliases override two different verified canonical originals', () => {
  const input = [note('app-recording-one', { meetingSource: source(canonicalA) }),
    note('app-recording-one-v2', { meetingSource: source(canonicalB) })]
  for (const order of permutations(input)) {
    expect(memberships(buildMeetingRows([], order))).toEqual([['app-recording-one'], ['app-recording-one-v2']])
  }
})

it('keeps an ambiguous unverified transitive bridge separate regardless of input order and retains its recording', () => {
  const input = [note('known-a', { taskId: 'task-a', meetingSource: source(canonicalA) }),
    note('known-b', { taskId: 'task-b', meetingSource: source(canonicalB) }),
    note('legacy-left', { taskId: 'task-a', sourceIds: ['shared-legacy'] }),
    note('legacy-right', { taskId: 'task-b', sourceIds: ['shared-legacy'] })]
  const original = { ...recording(), id: 'retained-bridge', taskId: undefined, noteId: 'legacy-left' }
  const before = JSON.stringify({ input, original })
  for (const order of permutations(input)) {
    const rows = buildMeetingRows([original], order)
    expect(memberships(rows)).toEqual([['known-a'], ['known-b'], ['legacy-left', 'legacy-right', 'retained-bridge']])
    expect(memberships(buildMeetingRows([], order, {}, 'owner-a'))).toEqual([['known-a'], ['known-b'], ['legacy-left', 'legacy-right']])
    for (const row of rows) expect(new Set(row.notes.flatMap(note => note.meetingSource ? [note.meetingSource.canonicalTaskId] : [])).size).toBeLessThanOrEqual(1)
  }
  expect(JSON.stringify({ input, original })).toBe(before)
})

it('preserves legacy-only aliases and unambiguous bridges into the same verified canonical', () => {
  const legacy = [note('app-recording-one'), note('app-recording-one-v2')]
  expect(buildMeetingRows([], legacy)).toHaveLength(1)
  const input = [
    note('a', { taskId: 'task-a', meetingSource: source(canonicalA) }),
    note('b', { taskId: 'task-b', meetingSource: source(canonicalA) }),
    note('legacy', { taskId: 'task-a', meetingIdentity: ['task:task-b'] }),
  ]
  for (const order of permutations(input)) {
    expect(memberships(buildMeetingRows([], order, {}, 'owner-a'))).toEqual([['a', 'b', 'legacy']])
  }
  expect(buildMeetingRows([], legacy.map(note => ({ ...note, meetingSource: source(canonicalA) })))).toHaveLength(1)
})

it('carries the API canonical projection through the real note store into grouping without title matching', async () => {
  const saved = '2026-10-19T01:00:00Z'
  api.json.mockResolvedValueOnce(['parent', 'summary-child', 'asr-child'].map(task => ({
    id: 'note-' + task, title: task, content: '保留正文', task_id: task, scope: 'personal', status: 'done',
    created_at: saved, updated_at: saved,
    meeting_source: { owner_id: 'owner-a', canonical_task_id: 'parent' },
  })))
  useNoteLibraryStore.getState().reset()
  await useNoteLibraryStore.getState().loadNotes()
  const notes = useNoteLibraryStore.getState().notes
  expect(notes.every(note => note.meetingSource?.canonicalTaskId === 'parent')).toBe(true)
  expect(buildMeetingRows([], notes)).toHaveLength(1)
  useNoteLibraryStore.getState().reset()
})
