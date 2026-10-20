import { cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { NoteRecord } from '@/stores/noteLibraryStore'
import type { WorkspaceNote, WorkspaceSummary } from '@/lib/workspace'
import type { PendingMeeting } from '@/lib/audioStorage'
const state = vi.hoisted(() => ({ local: [] as NoteRecord[], personal: true, workspace: { items: [] as WorkspaceSummary[], details: {} as Record<string, WorkspaceNote>, mappings: {} as Record<string, { key: string }>, pending: [] } }))
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: (selector: (s: unknown) => unknown) => selector({ notes: state.local }) }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: (selector: (s: unknown) => unknown) => selector({ currentWorkspace: { scope: state.personal ? 'personal' : 'team' } }) }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: () => state.workspace }))
vi.mock('@/hooks/useViewState', async () => { const { useState } = await import('react'); return { useViewState: (_key: string, value: unknown) => useState(value) } })
vi.mock('@/components/MeetingRecorder/LocalRecordingPreview', () => ({ LocalRecordingPreview: ({ recording }: { recording: PendingMeeting }) => <p>原件 {recording.id}</p> }))
import { useLibraryNotes, type LibraryNote } from './useLibraryNotes'
import { buildMeetingRows, MeetingWorkbench } from '@/components/MeetingRecorder/MeetingWorkbench'
const note = (id: string, taskId?: string): LibraryNote => ({ id, taskId, title: '旧会议', content: '相同正文', createdAt: '2026-10-10T00:00:00Z', updatedAt: '2026-10-10T00:00:00Z', sourceType: 'meeting_recording', scope: 'personal', status: 'done' })
const shared = (key: string, versions: WorkspaceNote['versions'] = [], metadata = {}): WorkspaceNote => ({ key, title: '旧会议', content: '相同正文', created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z', source_type: 'meeting_recording', source_device: 'mobile', revision: 1, deleted: false, archived: false, version_count: versions.length, metadata, versions, transcript: null, next_versions_offset: null })
const recording = (id: string, taskId?: string): PendingMeeting => ({ id, taskId, ownerId: 'owner', workspace: { scope: 'personal' }, options: { title: '旧会议' }, startedAt: '2026-10-10T00:00:00Z', elapsedSeconds: 20, recordingStatus: 'saved', processingStatus: 'completed' } as PendingMeeting)
beforeEach(() => { state.local = []; state.personal = true; state.workspace = { items: [], details: {}, mappings: {}, pending: [] } })
afterEach(cleanup)
it('recognizes a mobile mirror of the same stable source without cached mappings', () => {
  state.local = [note('app-original-task')]
  const remote = shared('mobile-app-original-task')
  state.workspace.items = [remote]; state.workspace.details[remote.key] = remote
  const { result } = renderHook(() => useLibraryNotes())
  expect(result.current).toHaveLength(1)
  expect(result.current[0]).toMatchObject({ workspaceKey: remote.key, localId: 'app-original-task' })
})
it('recovers stable migration source IDs from retained versions when media_id is missing', () => {
  state.local = [note('app-recording-one-v2', 'recording-one')]
  const versions = [{ id: 'app-recording-one-v2-generated-a123', title: 'V2', content: '第二版', created_at: '2026-10-10' }, { id: 'history-unrelated-id', title: 'V1', content: '原文', created_at: '2026-10-09' }]
  const remote = shared('migration-opaque-key', versions)
  state.workspace.items = [remote]; state.workspace.details[remote.key] = remote
  const snapshot = JSON.stringify(state)
  const { result } = renderHook(() => useLibraryNotes())
  expect(result.current).toHaveLength(1)
  expect(result.current[0].taskId).toBe('recording-one')
  const rows = buildMeetingRows([recording('local-copy', 'recording-one')], result.current)
  expect(rows).toHaveLength(1)
  expect(rows[0].notes.map(note => note.id)).toContain('app-recording-one-v2')
  expect(rows[0].notes.map(note => note.id)).toContain('migration-opaque-key')
  expect(JSON.stringify(state)).toBe(snapshot)
  expect(remote.versions).toHaveLength(2)
})
it('keeps migrated objects without verified sources in the pending view with every object reachable', () => {
  const first = shared('desktop-app-source-task'), second = shared('mobile-app-source-task-v2')
  state.workspace.items = [first, second]; state.workspace.details = { [first.key]: first, [second.key]: second }
  const { result } = renderHook(() => useLibraryNotes())
  const rows = buildMeetingRows([], result.current)
  expect(rows).toHaveLength(1)
  expect(rows[0].notes.map(row => row.workspaceKey)).toEqual([first.key, second.key])
  const open = vi.fn()
  render(<MeetingWorkbench notes={result.current} recordings={[]} loading={false} onOpenNote={open} onDeleted={vi.fn()} />)
  expect(screen.queryByRole('button', { name: '旧会议 · 已完成' })).not.toBeInTheDocument()
  fireEvent.mouseDown(screen.getByRole('tab', { name: '待归档' }), { button: 0, ctrlKey: false })
  expect(screen.getByRole('region', { name: '待归档内容' })).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: '关联原录制' })).not.toBeInTheDocument()
  const history = screen.getAllByRole('button', { name: /查看纪要 · 旧会议/ })
  fireEvent.click(history[0]); fireEvent.click(history[1])
  expect(open.mock.calls).toEqual([[first.key], [second.key]])
})
it('separates related minutes from the retained recording without inventing generated version counts', () => {
  const original = recording('retained', 'same-task')
  const first = note('first', 'same-task'), second = note('second', 'same-task')
  render(<MeetingWorkbench notes={[first, second]} recordings={[original]} loading={false} onOpenNote={vi.fn()} onDeleted={vi.fn()} />)
  const disclosure = screen.getByText('关联纪要（2条）与原录制')
  expect(disclosure.closest('details')).not.toHaveAttribute('open')
  fireEvent.click(disclosure)
  expect(screen.getByRole('region', { name: '关联纪要' })).toBeInTheDocument()
  expect(screen.getByRole('region', { name: '关联原录制' })).toBeInTheDocument()
  expect(screen.queryByText(/2.*生成版本|3 份内容记录/)).not.toBeInTheDocument()
})
it('retains known date-only metadata without fabricating a midnight time', () => {
  render(<MeetingWorkbench notes={[{ ...note('date-only'), createdAt: '2026-10-10' }]} recordings={[]} loading={false} onOpenNote={vi.fn()} onDeleted={vi.fn()} />)
  fireEvent.mouseDown(screen.getByRole('tab', { name: '待归档' }), { button: 0, ctrlKey: false })
  expect(screen.getByText('2026-10-10（时间未记录）')).toBeInTheDocument()
  expect(screen.getByText('2026-10-10（时间未记录）').parentElement).not.toHaveTextContent('00:00')
})
it('keeps unrelated same-title same-content same-date meetings separate', () => {
  expect(buildMeetingRows([], [note('first', 'task-first'), note('second', 'task-second')])).toHaveLength(2)
  expect(buildMeetingRows([recording('original')], [note('unrelated')])).toHaveLength(2)
})
it('matches recordings by task even when legacy noteId and draftNoteId were not restored', () => {
  const original = recording('original', 'accepted-task')
  const notes = [note('local-v1', 'accepted-task'), { ...note('shared-v2', 'accepted-task'), workspaceKey: 'shared-v2', updatedAt: '2026-10-11T00:00:00Z' }]
  const rows = buildMeetingRows([original], notes)
  expect(rows).toHaveLength(1)
  expect(rows[0].note?.id).toBe('shared-v2')
  expect(rows[0].notes).toHaveLength(2)
  expect(rows[0].recordings).toEqual([original])
})
it('retains a newer local edit and its distinct shared content instead of hiding a draft', () => {
  state.local = [{ ...note('original', 'same-task'), content: '未同步草稿', updatedAt: '2026-10-11T00:00:00Z' }]
  const remote = shared('desktop-original')
  state.workspace.items = [remote]; state.workspace.details[remote.key] = remote
  const { result } = renderHook(() => useLibraryNotes())
  expect(result.current).toHaveLength(2)
  expect(buildMeetingRows([], result.current)[0].notes).toHaveLength(2)
  expect(buildMeetingRows([], result.current)[0].note?.content).toBe('未同步草稿')
})
it('does not resurrect a deleted mapped source and does not mix team identities', () => {
  state.local = [note('original', 'same-task')]
  state.workspace.items = [{ ...shared('mobile-original'), deleted: true }]
  const { result } = renderHook(() => useLibraryNotes())
  expect(result.current).toHaveLength(0)
  expect(buildMeetingRows([], [note('personal', 'same-task'), { ...note('team', 'same-task'), scope: 'team', teamId: 'team-one' }])).toHaveLength(2)
})
it('preserves failed processing and every original while grouping the known task', () => {
  const first = { ...recording('original-a', 'same-task'), processingStatus: 'failed' as const, processingError: '失败原件保留' }, second = recording('original-b', 'same-task')
  const input = [first, second]; const before = JSON.stringify(input)
  const rows = buildMeetingRows(input, [note('saved-v1', 'same-task')])
  expect(rows).toHaveLength(1)
  expect(rows[0].state).toBe('需处理')
  expect(rows[0].recordings).toHaveLength(2)
  expect(JSON.stringify(input)).toBe(before)
})

it('loads archived project snapshots without using their archive flag as meeting association', () => {
  state.local = [{ ...note('confirmed-source', 'canonical'), meetingSource: { ownerId: 'owner', canonicalTaskId: 'canonical' } }]
  const linked = { ...shared('desktop-confirmed-source', [], { project: 'Review' }), archived: true }
  const pending = { ...shared('unlinked-project-content', [], { project: 'Review' }), archived: true }
  state.workspace.items = [linked, pending]
  state.workspace.details = { [linked.key]: linked, [pending.key]: pending }
  const { result } = renderHook(() => useLibraryNotes())
  expect(result.current).toHaveLength(2)
  expect(result.current.every(note => note.archived && note.project === 'Review')).toBe(true)
  const rows = buildMeetingRows([], result.current, {}, 'owner')
  expect(rows.filter(row => row.kind === 'meeting')).toHaveLength(1)
  expect(rows.filter(row => row.kind === 'unlinked').flatMap(row => row.notes.map(note => note.id)))
    .toEqual(['unlinked-project-content'])
  expect(state.workspace.details[linked.key].archived).toBe(true)
  expect(state.workspace.details[pending.key].archived).toBe(true)
})
