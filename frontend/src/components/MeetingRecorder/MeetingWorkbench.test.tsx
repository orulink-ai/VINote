import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { LibraryNote } from '@/hooks/useLibraryNotes'
import type { PendingMeeting } from '@/lib/audioStorage'

const account = vi.hoisted(() => ({ owner: 'owner-a' }))
vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (state: { user: { id: string } }) => unknown) => selector({ user: { id: account.owner } }),
}))
vi.mock('./LocalRecordingPreview', () => ({ LocalRecordingPreview: () => <p>原件操作</p> }))
import { MeetingWorkbench } from './MeetingWorkbench'
import { meetingRecordingTitle } from '@/lib/meetingGroups'
const captureTime = (task: string) => new Date(Date.UTC(2026, 9, 10, 7, [...task].reduce((sum, c) => sum + c.charCodeAt(0), 0) % 60)).toISOString()
const heading = (task: string, state = '已完成') => `${meetingRecordingTitle(captureTime(task))} · ${state}`

const savedAt = '2026-10-10T15:47:34Z'
function note(id: string, overrides: Partial<LibraryNote> = {}): LibraryNote {
  return {
    id, taskId: 'one-meeting', title: '同名纪要', content: '已确认保留原件，下一步核对纪要。',
    meetingSource: 'taskId' in overrides && !overrides.taskId ? undefined : { ownerId: account.owner, canonicalTaskId: overrides.taskId || 'one-meeting', recordingStartedAt: captureTime(overrides.taskId || 'one-meeting') },
    sourceType: 'meeting_recording', sourceDevice: 'desktop', syncLabel: '已同步',
    scope: 'personal', status: 'done', createdAt: savedAt, updatedAt: savedAt,
    ...overrides,
  }
}
function mount(notes: LibraryNote[], open = vi.fn()) {
  return render(<MeetingWorkbench key={account.owner} notes={notes} recordings={[]} loading={false} onOpenNote={open} onDeleted={vi.fn()} />)
}
async function expand(count: number) {
  const label = new RegExp(`^关联纪要（${count}条）`)
  await userEvent.click(screen.getByText(label))
  await waitFor(() => expect(screen.getByText(label).closest('details')).toHaveAttribute('open'))
  return screen.getByRole('region', { name: '关联纪要' })
}
beforeEach(() => { account.owner = 'owner-a'; sessionStorage.clear() })
afterEach(() => { cleanup(); sessionStorage.clear() })

it('opens the actual meeting content in edit mode from a visible action without a sync status', async () => {
  const open = vi.fn(); mount([note('exact-object')], open);
  expect(screen.queryByText('已同步')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: heading('one-meeting') }));
  await userEvent.click(screen.getByRole('button', { name: '编辑《同名纪要》' }));
  expect(open).toHaveBeenCalledExactlyOnceWith('exact-object', true);
});

it('distinguishes same-title same-save-time objects using actual updates and text while opening each original ID', async () => {
  const notes = [
    note('first-object', { updatedAt: '2026-10-12T03:02:01Z', content: '决定采用方案甲，保留核验依据。' }),
    note('second-object', { updatedAt: '2026-10-12T02:02:01Z', content: '决定采用方案乙，保留核验依据。' }),
    note('third-object', { updatedAt: '2026-10-12T01:02:01Z', sourceType: 'meeting_video' }),
  ]
  const before = JSON.stringify(notes), open = vi.fn()
  mount(notes, open)
  const region = await expand(3)
  const buttons = within(region).getAllByRole('button', { name: /查看纪要 · 同名纪要/ })
  expect(buttons).toHaveLength(3)
  expect(new Set(buttons.map(button => button.textContent)).size).toBe(3)
  expect(within(buttons[0]).getByText(/记录更新于/).textContent).not.toBe(within(buttons[1]).getByText(/记录更新于/).textContent)
  expect(within(buttons[0]).getByText('决定采用方案甲，保留核验依据。')).toBeInTheDocument()
  expect(within(buttons[1]).getByText('决定采用方案乙，保留核验依据。')).toBeInTheDocument()
  expect(buttons[2]).toHaveTextContent('录屏纪要')
  expect(screen.queryByText('记录详情')).not.toBeInTheDocument()
  for (const button of buttons) await userEvent.click(button)
  expect(open.mock.calls).toEqual(notes.map(record => [record.id]))
  expect(JSON.stringify(notes)).toBe(before)
})

it('does not fabricate an update or a read body from the saved timestamp, device or workspace key', async () => {
  const notes = [
    note('not-read', { updatedAt: '', content: '', sourceType: undefined, sourceDevice: undefined, workspaceKey: 'not-read', syncLabel: undefined }),
    note('known-read', { content: '实际读取的摘要。' }),
  ]
  mount(notes)
  const region = await expand(2)
  const unread = within(region).getByRole('button', { name: /正文未读取/ })
  expect(unread).toHaveTextContent('记录更新于 时间未记录')
  expect(unread).not.toHaveTextContent('共享')
  expect(unread).not.toHaveTextContent('桌面端')
  expect(unread).not.toHaveTextContent('手机')
  expect(within(unread).getByText(/记录更新于/)).not.toHaveTextContent('2026')
  expect(within(region).getAllByRole('button', { name: /查看纪要/ })).toHaveLength(2)
})

it('retains identical visible records and exposes their actual identifiers only on demand without V numbering', async () => {
  const notes = [note('opaque-first-object'), note('opaque-second-object')], open = vi.fn()
  mount(notes, open)
  const region = await expand(2)
  const buttons = within(region).getAllByRole('button', { name: /查看纪要/ })
  expect(buttons).toHaveLength(2)
  expect(buttons[0].textContent).toBe(buttons[1].textContent)
  const identifiers = within(region).getAllByText('记录详情')
  expect(identifiers).toHaveLength(2)
  for (let index = 0; index < buttons.length; index++) {
    const details = identifiers[index].closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(within(details).getByText(notes[index].id)).not.toBeVisible()
    await userEvent.click(identifiers[index])
    expect(within(details).getByText(notes[index].id)).toBeVisible()
    await userEvent.click(buttons[index])
  }
  expect(open.mock.calls).toEqual([['opaque-first-object'], ['opaque-second-object']])
  expect(region).not.toHaveTextContent(/V[12]|版本保存于|共享内容/)
})

it('keeps previews bounded, treats unread records honestly and never collapses them into one object', async () => {
  mount([note('long', { content: '界'.repeat(5000) }), note('unread-a', { content: '' }), note('unread-b', { content: '' })])
  const region = await expand(3)
  const preview = within(region).getByText(/^界+…$/)
  expect(preview.textContent!.length).toBeLessThanOrEqual(181)
  expect(within(region).getAllByText('正文未读取')).toHaveLength(2)
  expect(within(region).getAllByRole('button', { name: /查看纪要/ })).toHaveLength(3)
  expect(within(region).getAllByText('记录详情')).toHaveLength(2)
})

it('restores warm-return expansion and search for the same owner without carrying bodies to another owner or workspace', async () => {
  const notes = [note('first'), note('second')]
  const initial = mount(notes)
  await userEvent.type(screen.getByRole('textbox', { name: '搜索记录' }), '同名')
  await expand(2)
  await waitFor(() => expect(JSON.parse(sessionStorage.getItem('vinote:view:owner-a:recordings-expanded') || '[]')).toHaveLength(2))
  const expanded = sessionStorage.getItem('vinote:view:owner-a:recordings-expanded')!
  expect(expanded).toContain('first')
  expect(expanded).not.toContain('已确认保留原件')
  initial.unmount()

  // A newer record can become the representative; the real members are unchanged.
  const returned = mount(notes.map(record => record.id === 'second' ? { ...record, updatedAt: '2026-10-12T00:00:00Z' } : record))
  expect(screen.getByText(/^关联纪要（2条）/).closest('details')).toHaveAttribute('open')
  expect(screen.getByRole('textbox', { name: '搜索记录' })).toHaveValue('同名')
  returned.unmount()

  account.owner = 'owner-b'
  const otherOwner = mount(notes)
  expect(screen.queryByText(/^关联纪要（2条）/)).not.toBeInTheDocument()
  expect(screen.queryByText('查看纪要 · 同名纪要')).not.toBeInTheDocument()
  expect(screen.getByRole('textbox', { name: '搜索记录' })).toHaveValue('')
  otherOwner.unmount()

  account.owner = 'owner-a'
  const otherSpace = mount(notes.map(record => ({ ...record, scope: 'team' as const, teamId: 'team-b' })))
  expect(screen.getByText(/^关联纪要（2条）/).closest('details')).not.toHaveAttribute('open')
  otherSpace.unmount()

  const originalOwner = mount(notes)
  expect(screen.getByText(/^关联纪要（2条）/).closest('details')).toHaveAttribute('open')
  originalOwner.unmount()
  mount([note('different-first'), note('different-second')])
  expect(screen.getByText(/^关联纪要（2条）/).closest('details')).not.toHaveAttribute('open')
  expect(screen.queryByText('first', { exact: true })).not.toBeInTheDocument()
})


it('renders a retained-media placeholder with default done as needing attention when its exact task failed', () => {
  const row = note('placeholder', { title: 'Synthetic retained capture', content: '原始媒体已保存，正在进行会后处理。', status: 'done', taskId: 'failed-task' })
  render(<MeetingWorkbench notes={[row]} recordings={[]} taskStates={{ 'failed-task': 'failed' }} loading={false} onOpenNote={vi.fn()} onDeleted={vi.fn()} />)
  expect(screen.getByRole('button', { name: heading('failed-task', '需处理') })).toBeInTheDocument()
  expect(screen.queryByText('· 纪要已完成')).toBeNull()
})
it('keeps provenance-free records in history and does not infer state from their titles', async () => {
  const rows = [note('pending', { title: 'A normal subject', taskId: undefined, status: 'pending' }), note('failed', { title: 'Another subject', taskId: undefined, status: 'failed' }), note('done', { title: '待生成纪要', taskId: undefined, status: 'done' })]
  mount(rows)
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(0)
  await userEvent.click(screen.getByRole('tab', { name: '待归档' }))
  expect(screen.getByRole('button', { name: /查看纪要 · A normal subject.*状态未核验/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /查看纪要 · Another subject.*需处理/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /查看纪要 · 待生成纪要.*已完成/ })).toBeInTheDocument()
})
it('keeps unverified and unsaved successful task results distinct from completed saved minutes', () => {
  render(<MeetingWorkbench notes={[note('unknown', { taskId: 'unknown' }), note('pending', { taskId: 'success', status: 'pending' })]} recordings={[]} taskStates={{ unknown: 'unverified', success: 'complete' }} loading={false} onOpenNote={vi.fn()} onDeleted={vi.fn()} />)
  expect(screen.getByRole('button', { name: heading('unknown', '状态未核验') })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: heading('success', '纪要待保存') })).toBeInTheDocument()
  expect(screen.queryByText('· 纪要已完成')).toBeNull()
})

it('opens the meeting contents instead of automatically opening its newest summary, retaining every child and original', async () => {
  const source = { ownerId: 'owner-a', canonicalTaskId: 'original' }
  const notes = [note('old', { title: '旧稿标题', taskId: 'original', meetingSource: source, content: '旧稿独有检索词', updatedAt: '2026-10-20T10:00:00Z' }),
    note('latest', { title: '最新可读稿', taskId: 'summary-child', meetingSource: source, createdAt: '2026-10-20T01:00:00Z' }),
    note('failed', { taskId: 'asr-child', meetingSource: source, status: 'failed', createdAt: '2026-10-20T02:00:00Z' })]
  const recording = { id: 'rec', ownerId: 'owner-a', taskId: 'original', workspace: { scope: 'personal' },
    options: { title: '真实会议' }, startedAt: savedAt, elapsedSeconds: 20, recordingStatus: 'saved', processingStatus: 'completed' } as PendingMeeting
  const open = vi.fn()
  const view = render(<MeetingWorkbench recordings={[recording]} notes={notes} loading={false} onOpenNote={open} onDeleted={vi.fn()} />)
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(1)
  expect(screen.getByText('3 份纪要')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: `${meetingRecordingTitle(savedAt)} · 已完成` }))
  expect(open).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: `${meetingRecordingTitle(savedAt)} · 已完成` })).toHaveAttribute('aria-expanded', 'true')
  await userEvent.type(screen.getByRole('textbox', { name: '搜索记录' }), '旧稿独有检索词')
  const history = screen.getByRole('region', { name: '关联纪要' })
  expect(within(history).getAllByRole('button', { name: /查看纪要/ })).toHaveLength(3)
  await userEvent.click(within(history).getByRole('button', { name: /查看纪要 · 旧稿标题/ }))
  expect(open).toHaveBeenLastCalledWith('old')
  await userEvent.click(screen.getByRole('button', { name: /查看原录制 · 真实会议/ }))
  expect(screen.getByRole('dialog', { name: '录制详情' })).toBeInTheDocument()
  expect(screen.getByText('原件操作')).toBeInTheDocument()
  view.unmount()
  render(<MeetingWorkbench recordings={[recording]} notes={notes} loading={false} onOpenNote={open} onDeleted={vi.fn()} />)
  expect(screen.getByRole('textbox', { name: '搜索记录' })).toHaveValue('旧稿独有检索词')
  expect(screen.getByText('关联纪要（3条）与原录制').closest('details')).toHaveAttribute('open')
})

it('lists two meeting dossiers and keeps unlinked synthetic or manual notes in the pending view without deleting anything', async () => {
  const notes = [
    note('original-a', { title: '会议一', taskId: 'task-a' }),
    note('summary-a', { title: '详细文字稿', taskId: 'child-a', meetingSource: { ownerId: account.owner, canonicalTaskId: 'task-a' } }),
    note('original-b', { title: '会议二', taskId: 'task-b' }),
    note('manual', { title: '会议一', taskId: undefined, meetingSource: undefined }),
    note('synthetic', { title: '虚构验收笔记', taskId: 'unverified', meetingSource: undefined }),
  ]
  const before = JSON.stringify(notes), open = vi.fn()
  mount(notes, open)
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(2)
  expect(screen.getByText('2 场会议')).toBeInTheDocument()
  expect(screen.queryByText('查看纪要 · 虚构验收笔记')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: heading('task-a') }))
  expect(open).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: /查看纪要 · 详细文字稿/ })).toBeVisible()
  await userEvent.click(screen.getByRole('tab', { name: '待归档' }))
  const history = screen.getByRole('region', { name: '待归档内容' })
  expect(screen.queryByRole('button', { name: heading('task-a') })).not.toBeInTheDocument()
  await userEvent.click(within(history).getByRole('button', { name: /查看纪要 · 虚构验收笔记/ }))
  expect(open).toHaveBeenLastCalledWith('synthetic')
  expect(JSON.stringify(notes)).toBe(before)
})

it('keeps a canonical recording entry after the IndexedDB history is absent, without claiming availability', async () => {
  const source = { ownerId: 'owner-a', canonicalTaskId: 'original' }, open = vi.fn()
  mount([note('original-note', { taskId: 'original', meetingSource: source }), note('child', { taskId: 'summary-child', meetingSource: source })], open)
  await userEvent.click(screen.getByText('关联纪要（2条）与原录制'))
  await userEvent.click(within(screen.getByRole('region', { name: '关联原录制' })).getByRole('button', { name: /查看原录制/ }))
  expect(open).toHaveBeenLastCalledWith('original-note')
  expect(screen.getByText(/原录制是否可用以详情核验为准/)).toBeInTheDocument()
})

it('supports keyboard expansion of the meeting without navigating to a summary', async () => {
  const open = vi.fn()
  mount([note('one'), note('two')], open)
  const parent = screen.getByRole('button', { name: heading('one-meeting') })
  const user = userEvent.setup()
  parent.focus()
  await user.keyboard('{Enter}')
  expect(parent).toHaveAttribute('aria-expanded', 'true')
  expect(document.getElementById(parent.getAttribute('aria-controls')!)?.open).toBe(true)
  expect(screen.getByRole('region', { name: '关联纪要' })).toBeVisible()
  expect(open).not.toHaveBeenCalled()
  await user.keyboard(' ')
  expect(parent).toHaveAttribute('aria-expanded', 'false')
  expect(open).not.toHaveBeenCalled()
})

it('opens an unnamed recording as a meeting with its original and no invented summary', async () => {
  const original = { id: 'rec-only', ownerId: account.owner, workspace: { scope: 'personal' },
    options: { title: '' }, startedAt: savedAt, elapsedSeconds: 20, recordingStatus: 'saved', processingStatus: 'idle' } as PendingMeeting
  const open = vi.fn()
  render(<MeetingWorkbench recordings={[original]} notes={[]} loading={false} onOpenNote={open} onDeleted={vi.fn()} />)
  await userEvent.click(screen.getByRole('button', { name: `${meetingRecordingTitle(savedAt)} · 未生成` }))
  expect(screen.queryByRole('button', { name: /查看纪要/ })).not.toBeInTheDocument()
  expect(open).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: /查看原录制 · 未命名录制/ }))
  expect(screen.getByRole('dialog', { name: '录制详情' })).toBeInTheDocument()
})

it.each([false, true])('classifies dossiers by proven sources regardless of the historical archived flag %s', async archived => {
  const notes = [
    note('source-a', { title: '第一场会议', taskId: 'source-a', archived }),
    note('source-b', { title: '第二场会议', taskId: 'source-b', archived: !archived }),
    note('unlinked-active', { title: '待归档旧稿一', taskId: undefined, meetingSource: undefined, archived: false }),
    note('unlinked-archived', { title: '待归档旧稿二', taskId: undefined, meetingSource: undefined, archived: true }),
  ]
  const before = JSON.stringify(notes), open = vi.fn()
  const props = { recordings: [], notes, loading: false, onOpenNote: open, onDeleted: vi.fn() }
  const view = render(<MeetingWorkbench {...props} view="meetings" />)
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(2)
  expect(screen.getByRole('button', { name: heading('source-a') })).toBeVisible()
  expect(screen.getByRole('button', { name: heading('source-b') })).toBeVisible()
  expect(screen.queryByText('查看纪要 · 待归档旧稿一')).not.toBeInTheDocument()
  view.rerender(<MeetingWorkbench {...props} view="pending" />)
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(0)
  const pending = screen.getByRole('region', { name: '待归档内容' })
  expect(within(pending).getAllByRole('button', { name: /查看纪要/ })).toHaveLength(2)
  await userEvent.click(within(pending).getByRole('button', { name: /查看纪要 · 待归档旧稿二/ }))
  expect(open).toHaveBeenLastCalledWith('unlinked-archived')
  expect(JSON.stringify(notes)).toBe(before)
})

it('keeps a new version in the same meeting dossier even when its old archive flag differs', () => {
  const original = note('canonical', { title: '原会议档案', taskId: 'canonical', archived: true })
  const props = { recordings: [], loading: false, onOpenNote: vi.fn(), onDeleted: vi.fn() }
  const view = render(<MeetingWorkbench {...props} notes={[original]} view="meetings" />)
  const row = screen.getByRole('button', { name: heading('canonical') })
  const identity = row.parentElement!.getAttribute('data-meeting-row-ids')
  const child = note('new-format', { taskId: 'summary-child', title: '图文新版本', archived: false,
    meetingSource: original.meetingSource, createdAt: '2026-10-20T00:00:00Z' })
  view.rerender(<MeetingWorkbench {...props} notes={[original, child]} view="meetings" />)
  expect(document.querySelectorAll('[data-meeting-row-ids]')).toHaveLength(1)
  expect(screen.getByRole('button', { name: heading('canonical') })).toBeVisible()
  expect(screen.getByText('2 份纪要')).toBeInTheDocument()
  expect(identity).toContain('canonical')
  view.rerender(<MeetingWorkbench {...props} notes={[original, child]} view="pending" />)
  expect(screen.queryByRole('button', { name: /查看纪要/ })).not.toBeInTheDocument()
})

it('never promotes a note placeholder, saved time or workspace recording hint to the meeting heading', async () => {
  const record = note('clock-unknown', { title: '2026-10-19 15:41｜待生成纪要',
    recordingStartedAt: '2099-01-01T12:00:00Z', meetingSource: { ownerId: account.owner, canonicalTaskId: 'source' } })
  mount([record])
  const header = screen.getByRole('button', { name: '录制时间未记录 · 已完成' })
  expect(header).not.toHaveTextContent('待生成纪要')
  expect(header).not.toHaveTextContent('2026')
  expect(header).not.toHaveTextContent('2099')
  expect(header).not.toHaveTextContent('保存于')
  await userEvent.click(header)
  expect(screen.getByRole('button', { name: /查看纪要 · 2026-10-19 15:41｜待生成纪要/ })).toBeVisible()
})
