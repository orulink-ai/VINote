import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { LibraryNote } from '@/hooks/useLibraryNotes'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import { ApiError } from '@/lib/api'
import { MeetingWorkbench } from './MeetingWorkbench'

const api = vi.hoisted(() => ({ json: vi.fn() }))
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: api.json }))
vi.mock('./LocalRecordingPreview', () => ({ LocalRecordingPreview: () => null }))
const canonical = '11111111-1111-4111-8111-111111111111'
const tasks = Array.from({ length: 6 }, (_, index) => `22222222-2222-4222-8222-${String(index).padStart(12, '0')}`)
function note(index: number, overrides = {}): LibraryNote {
  return { id: `note-${index}`, taskId: tasks[index], title: '同名纪要', content: '# HTML 图文 详细 V99', sourceType: 'meeting_video',
    generationClient: 'desktop', scope: 'personal', status: 'done', createdAt: '2026-10-20T12:00:00Z', updatedAt: '2026-10-20T12:00:00Z',
    meetingSource: { ownerId: 'owner', canonicalTaskId: canonical, recordingStartedAt: '2026-10-20T10:00:00Z' }, ...overrides }
}
function mount(notes: LibraryNote[], open = vi.fn()) {
  return render(<MeetingWorkbench notes={notes} recordings={[]} loading={false} onOpenNote={open} onDeleted={vi.fn()} />)
}
async function expand(count: number) { await userEvent.click(screen.getByText(new RegExp(`^关联纪要（${count}条）`))) }
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear()
  useAuthStore.setState({ user: { id: 'owner' } as never }); useAppModeStore.setState({ config: null })
})
afterEach(() => { cleanup(); sessionStorage.clear() })

it('reads existing metadata only on expansion, deduplicates child tasks and keeps every saved object reachable', async () => {
  api.json.mockImplementation(async (path: string) => ({ protocol: 1, task_id: path.split('/')[3], presentation: 'html', content_depth: 'brief' }))
  const notes = [note(0), note(1), note(1, { id: 'same-task-second-object' })], before = JSON.stringify(notes), open = vi.fn()
  mount(notes, open)
  expect(api.json).not.toHaveBeenCalled()
  await expand(3)
  await waitFor(() => expect(screen.getAllByText('摘要', { exact: true })).toHaveLength(3))
  expect(screen.getAllByText('HTML', { exact: true })).toHaveLength(3)
  expect(api.json.mock.calls.map(([path]) => path)).toEqual(tasks.slice(0, 2).map(task => `/api/task/${task}/summary-presentation`))
  const cards = screen.getAllByRole('button', { name: /查看纪要 · 同名纪要/ })
  expect(cards[0]).toHaveAccessibleDescription(/HTML.*摘要/)
  const labels = within(cards[0].closest('li')!).getByRole('group', { name: '生成形式与详略' })
  expect(within(labels.parentElement!).getByRole('button', { name: '编辑《同名纪要》' })).toBeVisible()
  for (const card of cards) await userEvent.click(card)
  expect(open.mock.calls).toEqual(notes.map(n => [n.id]))
  expect(JSON.stringify(notes)).toBe(before)
  expect(api.json.mock.calls.every(([, init]) => init.method === 'GET')).toBe(true)
})

it('keeps missing, transport and wrong-task metadata unknown without guessing from the body or title', async () => {
  api.json.mockImplementation(async (path: string) => {
    if (path.includes(tasks[0])) throw new ApiError('missing', 404, null)
    if (path.includes(tasks[1])) throw new Error('offline')
    return { protocol: 1, task_id: 'wrong-task', presentation: 'html', content_depth: 'detailed' }
  })
  mount([note(0), note(1), note(2)]); await expand(3)
  await waitFor(() => expect(screen.getAllByText('形式/详略暂未核验')).toHaveLength(2))
  expect(screen.getByText('形式/详略未记录')).toBeVisible()
  expect(screen.queryByText('HTML', { exact: true })).toBeNull()
  expect(screen.queryByText('详细', { exact: true })).toBeNull()
})

it.each([{ protocol: 2 }, { presentation: 'toString' }, { content_depth: 'constructor' }])('rejects malformed metadata %j', async change => {
  api.json.mockResolvedValue({ protocol: 1, task_id: tasks[0], presentation: 'text', content_depth: 'concise', ...change })
  mount([note(0)]); await expand(1)
  expect(await screen.findByText('形式/详略暂未核验')).toBeVisible()
  expect(screen.queryByText('精简', { exact: true })).toBeNull()
})

it('ignores late metadata after collapsing the dossier', async () => {
  let resolve!: (value: unknown) => void
  api.json.mockImplementation(() => new Promise(done => { resolve = done }))
  mount([note(0)]); await expand(1)
  await waitFor(() => expect(api.json).toHaveBeenCalledTimes(1))
  const signal = api.json.mock.calls[0][1].signal
  await expand(1)
  await waitFor(() => expect(signal.aborted).toBe(true))
  await act(async () => resolve({ protocol: 1, task_id: tasks[0], presentation: 'comic', content_depth: 'detailed' }))
  expect(screen.queryByText('画面分镜', { exact: true })).toBeNull()
})

it('discards an old account response and never reads a foreign-owner task', async () => {
  let resolve!: (value: unknown) => void
  api.json.mockImplementation(() => new Promise(done => { resolve = done }))
  const { rerender } = mount([note(0)]); await expand(1)
  await waitFor(() => expect(api.json).toHaveBeenCalledTimes(1))
  act(() => useAuthStore.setState({ user: { id: 'other' } as never }))
  rerender(<MeetingWorkbench notes={[note(0)]} recordings={[]} loading={false} onOpenNote={vi.fn()} onDeleted={vi.fn()} />)
  await act(async () => resolve({ protocol: 1, task_id: tasks[0], presentation: 'comic', content_depth: 'detailed' }))
  expect(screen.queryByText('画面分镜', { exact: true })).toBeNull()
  expect(api.json).toHaveBeenCalledTimes(1)
})

it('does not attach canonical parent metadata to a child without its own task', async () => {
  mount([note(0, { taskId: undefined })]); await expand(1)
  const labels = screen.getByLabelText('生成形式与详略')
  expect(within(labels).getByText('形式/详略未记录')).toBeVisible()
  expect(api.json).not.toHaveBeenCalled()
})

it('distinguishes all five forms within the same dossier using each child metadata rather than a shared canonical label', async () => {
  const forms = ['text', 'illustrated', 'html', 'comic', 'infographic']
  api.json.mockImplementation(async (path: string) => {
    const task = path.split('/')[3], index = tasks.indexOf(task)
    return { protocol: 1, task_id: task, presentation: forms[index], content_depth: index % 2 ? 'concise' : 'detailed' }
  })
  mount(forms.map((_, index) => note(index))); await expand(5)
  await waitFor(() => expect(screen.getByText('信息图', { exact: true })).toBeVisible())
  const groups = screen.getAllByRole('group', { name: '生成形式与详略' })
  for (const [index, label] of ['文字', '图文', 'HTML', '画面分镜', '信息图'].entries()) {
    expect(within(groups[index]).getByText(label, { exact: true })).toBeVisible()
    expect(within(groups[index]).getByText(index % 2 ? '精简' : '详细', { exact: true })).toBeVisible()
  }
  expect(api.json).toHaveBeenCalledTimes(5)
})
