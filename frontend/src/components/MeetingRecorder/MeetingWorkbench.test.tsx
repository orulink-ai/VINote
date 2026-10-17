import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { LibraryNote } from '@/hooks/useLibraryNotes'

const account = vi.hoisted(() => ({ owner: 'owner-a' }))
vi.mock('@/stores/authStore', () => ({
  useAuthStore: (selector: (state: { user: { id: string } }) => unknown) => selector({ user: { id: account.owner } }),
}))
vi.mock('./LocalRecordingPreview', () => ({ LocalRecordingPreview: () => <p>原件操作</p> }))
import { MeetingWorkbench } from './MeetingWorkbench'

const savedAt = '2026-10-10T15:47:34Z'
function note(id: string, overrides: Partial<LibraryNote> = {}): LibraryNote {
  return {
    id, taskId: 'one-meeting', title: '同名纪要', content: '已确认保留原件，下一步核对纪要。',
    sourceType: 'meeting_recording', sourceDevice: 'desktop', syncLabel: '已同步',
    scope: 'personal', status: 'done', createdAt: savedAt, updatedAt: savedAt,
    ...overrides,
  }
}
function mount(notes: LibraryNote[], open = vi.fn()) {
  return render(<MeetingWorkbench key={account.owner} notes={notes} recordings={[]} loading={false} onOpenNote={open} onDeleted={vi.fn()} />)
}
async function expand(count: number) {
  await userEvent.click(screen.getByText(`关联纪要（${count}条）`))
  await waitFor(() => expect(screen.getByText(`关联纪要（${count}条）`).closest('details')).toHaveAttribute('open'))
  return screen.getByRole('region', { name: '关联纪要' })
}
beforeEach(() => { account.owner = 'owner-a'; sessionStorage.clear() })
afterEach(() => { cleanup(); sessionStorage.clear() })

it('opens the actual meeting content in edit mode from a visible action without a sync status', async () => {
  const open = vi.fn(); mount([note('exact-object')], open);
  expect(screen.queryByText('已同步')).not.toBeInTheDocument();
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
  expect(screen.getByText('关联纪要（2条）').closest('details')).toHaveAttribute('open')
  expect(screen.getByRole('textbox', { name: '搜索记录' })).toHaveValue('同名')
  returned.unmount()

  account.owner = 'owner-b'
  const otherOwner = mount(notes)
  expect(screen.getByText('关联纪要（2条）').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByRole('textbox', { name: '搜索记录' })).toHaveValue('')
  otherOwner.unmount()

  account.owner = 'owner-a'
  const otherSpace = mount(notes.map(record => ({ ...record, scope: 'team' as const, teamId: 'team-b' })))
  expect(screen.getByText('关联纪要（2条）').closest('details')).not.toHaveAttribute('open')
  otherSpace.unmount()

  const originalOwner = mount(notes)
  expect(screen.getByText('关联纪要（2条）').closest('details')).toHaveAttribute('open')
  originalOwner.unmount()
  mount([note('different-first'), note('different-second')])
  expect(screen.getByText('关联纪要（2条）').closest('details')).not.toHaveAttribute('open')
  expect(screen.queryByText('first', { exact: true })).not.toBeInTheDocument()
})
