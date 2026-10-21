import { expect, it, vi } from 'vitest'
import type { LibraryNote } from '@/hooks/useLibraryNotes'
import type { PendingMeeting } from './audioStorage'
import { buildMeetingRows, meetingRecordingTitle } from './meetingGroups'
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
    meeting_source: { owner_id: 'owner-a', canonical_task_id: 'parent', recording_started_at: '2026-10-19T07:41:05.355Z' },
  })))
  useNoteLibraryStore.getState().reset()
  await useNoteLibraryStore.getState().loadNotes()
  const notes = useNoteLibraryStore.getState().notes
  expect(notes.every(note => note.meetingSource?.canonicalTaskId === 'parent')).toBe(true)
  expect(buildMeetingRows([], notes)).toHaveLength(1)
  expect(notes.every(note => note.meetingSource?.recordingStartedAt === '2026-10-19T07:41:05.355Z')).toBe(true)
  expect(buildMeetingRows([], notes)[0].date).toBe('2026-10-19T07:41:05.355Z')
  useNoteLibraryStore.getState().reset()
})

it('identifies two proven meetings while keeping unlinked historical and synthetic objects outside the meeting list', () => {
  const rows = buildMeetingRows([], [
    note('first-original', { taskId: 'first', title: '原始会议一', meetingSource: source('first') }),
    note('first-html', { taskId: 'html-child', title: '最新 HTML 稿', meetingSource: source('first') }),
    note('second-original', { taskId: 'second', meetingSource: source('second') }),
    note('old-manual', { title: '原始会议一' }),
    note('synthetic-acceptance', { taskId: 'unproven-task', title: '原始会议一' }),
  ], {}, 'owner-a')
  expect(rows.filter(row => row.kind === 'meeting')).toHaveLength(2)
  expect(rows.filter(row => row.kind === 'unlinked').flatMap(row => row.notes.map(note => note.id)).sort())
    .toEqual(['old-manual', 'synthetic-acceptance'])
})

it('uses the canonical recording clock and stable identity instead of promoting a summary title', () => {
  const original = note('original-note', { taskId: 'original', title: '待生成纪要', meetingSource: { ...source(), recordingStartedAt: '2026-10-19T07:41:05.355Z' } })
  const latest = note('latest-summary', { taskId: 'new-child', title: '最新摘要的新标题',
    meetingSource: source(), createdAt: '2026-10-20T08:00:00Z' })
  const row = buildMeetingRows([], [latest, original], {}, 'owner-a')[0]
  expect(row.title).toBe(meetingRecordingTitle('2026-10-19T07:41:05.355Z'))
  expect(row.note?.id).toBe('latest-summary') // readability/status projection only
  expect(row.key).toBe(buildMeetingRows([], [original], {}, 'owner-a')[0].key)
})

it('recognizes an exact retained recording task without requiring a canonical projection or guessing the title', () => {
  const rows = buildMeetingRows([recording()], [note('legacy', { taskId: 'original', title: '完全不同的保存标题' })], {}, 'owner-a')
  expect(rows).toHaveLength(1)
  expect(rows[0].kind).toBe('meeting')
  expect(rows[0].notes[0].id).toBe('legacy')
})

it('does not retain foreign-owner sources nested in a historical workspace projection', () => {
  const projected = note('workspace-projection', { localSources: [
    note('owned', { meetingSource: source('same-source') }),
    note('foreign', { meetingSource: source('same-source', 'owner-b') }),
  ] })
  const rows = buildMeetingRows([recording('owner-b')], [projected], {}, 'owner-a')
  expect(rows.flatMap(row => row.notes.map(note => note.id)).sort()).toEqual(['owned', 'workspace-projection'])
  expect(rows.flatMap(row => row.recordings)).toEqual([])
})

it('prefers canonical capture time over device history and ignores note, filename and save clocks', () => {
  const input = note('saved', { taskId: 'original', title: '2099-01-01 23:59｜待生成纪要',
    recordingStartedAt: '2099-01-01T23:59:00Z',
    meetingSource: { ...source(), recordingStartedAt: '2026-10-19T07:41:05.355Z' } })
  const row = buildMeetingRows([recording()], [input])[0]
  expect(row.date).toBe('2026-10-19T07:41:05.355Z')
  expect(row.title).toBe(meetingRecordingTitle(row.date))
  const unknown = buildMeetingRows([], [{ ...input, meetingSource: source() }])[0]
  expect(unknown.title).toBe('录制时间未记录')
  expect(unknown.date).toBe('')
  expect(unknown.dateKind).toBe('unknown')
})

it('keeps conflicting canonical clocks unknown without falling back to a device or choosing by input order', () => {
  const inputs = ['2026-10-19T07:41:05Z', '2026-10-19T10:02:18Z'].map((recordingStartedAt, index) =>
    note(String(index), { taskId: 'original', meetingSource: { ...source(), recordingStartedAt } }))
  for (const order of permutations(inputs)) {
    const rows = buildMeetingRows([recording()], order)
    expect(rows).toHaveLength(1)
    expect(rows[0].title).toBe('录制时间未记录')
  }
})

it.each(['2026-10-19', '2026-10-19T07:41:05', 'invalid'])('does not turn an incomplete capture clock %s into an exact recording time', recordingStartedAt => {
  expect(buildMeetingRows([], [note('saved', { meetingSource: { ...source(), recordingStartedAt } })])[0].title).toBe('录制时间未记录')
})

it('does not merge different canonical recordings even when their verified start times match', () => {
  const rows = buildMeetingRows([], ['a', 'b'].map(task => note(task, {
    meetingSource: { ...source(task), recordingStartedAt: '2026-10-19T07:41:05Z' } })))
  expect(rows).toHaveLength(2)
  expect(rows[0].title).toBe(rows[1].title)
})

it('distinguishes canonical recordings starting in the same minute by their actual seconds in the user timezone', () => {
  const rows = buildMeetingRows([], ['05', '48'].map(second => note(second, {
    meetingSource: { ...source(second), recordingStartedAt: `2026-10-19T07:41:${second}.355Z` },
  })))
  const date = new Date('2026-10-19T07:41:05.355Z')
  const pad = (part: number) => String(part).padStart(2, '0')
  const localPrefix = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:`
  expect(rows.map(row => row.title)).toEqual([localPrefix + '48', localPrefix + '05'])
  expect(rows[0].key).not.toBe(rows[1].key)
})

it('does not label a dossier with saved minutes as ungenerated because capture history is stale', () => {
  const original = { ...recording(), processingStatus: 'idle' as const, noteId: undefined }
  const saved = note('saved-child', { taskId: 'child', meetingSource: source() })
  expect(buildMeetingRows([original], [saved])[0].state).toBe('已完成')
  expect(buildMeetingRows([original], [saved], { original: 'complete' })[0].state).toBe('已完成')
  expect(buildMeetingRows([original], [saved], { original: 'processing' })[0].state).toBe('处理中')
  expect(buildMeetingRows([original], [saved], { original: 'failed' })[0].state).toBe('需处理')
})

it('does not claim saved minutes for a completed recording when no saved content is present', () => {
  expect(buildMeetingRows([recording()], [])[0].state).toBe('纪要待保存')
  expect(buildMeetingRows([{ ...recording(), processingStatus: 'idle' }], [])[0].state).toBe('未生成')
})
