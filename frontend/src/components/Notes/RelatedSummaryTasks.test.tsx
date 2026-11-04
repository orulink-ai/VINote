import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({ api: vi.fn(), save: vi.fn(), owner: 'owner' }))
vi.mock('@/lib/api', () => ({ apiJson: mocks.api }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: mocks.owner } }) } }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: Object.assign((selector: (s: unknown) => unknown) => selector({ currentWorkspace: { scope: 'personal' }, teams: [] }), { getState: () => ({ currentWorkspace: { scope: 'personal' } }) }), getWorkspaceLabel: () => '个人空间' }))
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: { getState: () => ({ saveNote: mocks.save }) } }))
import { RelatedSummaryTasks } from './RelatedSummaryTasks'
const canonical = '546bfcb5-4cf1-47f2-b4a7-34a1b3612970'
const child = '4e8efb3a-98cc-4774-a5b0-d99794feec35'
const operation = '6ef7260e-3815-4b07-a281-84bdf3e50929'
const links = { canonical_task_id: canonical, items: [{ task_id: child, operation_id: operation }] }
const task = { task_id: child, status: 'success', result: { task_id: child, title: '会议', markdown: '正文' } }
beforeEach(() => { mocks.api.mockReset(); mocks.save.mockReset(); mocks.owner = 'owner' })
afterEach(cleanup)
function mount() { render(<MemoryRouter><Routes><Route path="/" element={<RelatedSummaryTasks canonical={canonical} owner="owner" returnTo="/files" />} /><Route path="/note/:id" element={<p>已保存</p>} /></Routes></MemoryRouter>) }
async function expand() { await userEvent.click(await screen.findByText(/处理记录 · 1次/)) }
it('verifies the child and explicitly saves once to the selected workspace', async () => {
  mocks.api.mockImplementation((url: string) => Promise.resolve(url.endsWith('summary-children') ? links : url.startsWith('/api/notes') ? [] : task))
  mocks.save.mockResolvedValue({ id: 'saved' })
  mount(); await expand(); await userEvent.click(await screen.findByRole('button', { name: '恢复保存' }))
  expect(mocks.save).not.toHaveBeenCalled()
  await userEvent.click(screen.getByRole('button', { name: '确认保存到此空间' }))
  await screen.findByText('已保存')
  expect(mocks.save).toHaveBeenCalledOnce()
  expect(mocks.save).toHaveBeenCalledWith('会议', '正文', undefined, child, { scope: 'personal' }, 'meeting_recording')
  expect(mocks.api.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
})
it('shows failure without offering save', async () => {
  mocks.api.mockImplementation((url: string) => Promise.resolve(url.endsWith('summary-children') ? links : { task_id: child, status: 'failed' }))
  mount(); await expand(); await screen.findByText(/处理失败/); expect(screen.queryByRole('button', { name: '恢复保存' })).not.toBeInTheDocument()
})
it('opens an existing note without creating another', async () => {
  mocks.api.mockImplementation((url: string) => Promise.resolve(url.endsWith('summary-children') ? links : url.startsWith('/api/notes') ? [{ id: 'saved', task_id: child }] : task))
  mount(); await expand(); await userEvent.click(await screen.findByRole('button', { name: '恢复保存' })); await userEvent.click(screen.getByRole('button', { name: '确认保存到此空间' })); await screen.findByText('已保存'); expect(mocks.save).not.toHaveBeenCalled()
})
it('does not save when the association changes', async () => {
  let reads = 0
  mocks.api.mockImplementation((url: string) => { if (url.endsWith('summary-children')) return Promise.resolve(++reads === 1 ? links : { ...links, items: [] }); return Promise.resolve(task) })
  mount(); await expand(); await userEvent.click(await screen.findByRole('button', { name: '恢复保存' })); await userEvent.click(screen.getByRole('button', { name: '确认保存到此空间' })); await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('关联无法确认')); expect(mocks.save).not.toHaveBeenCalled()
})
it('does not save if the workspace cannot be checked', async () => {
  mocks.api.mockImplementation((url: string) => url.startsWith('/api/notes') ? Promise.reject(new Error('空间读取失败')) : Promise.resolve(url.endsWith('summary-children') ? links : task))
  mount(); await expand(); await userEvent.click(await screen.findByRole('button', { name: '恢复保存' })); await userEvent.click(screen.getByRole('button', { name: '确认保存到此空间' })); await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('空间读取失败')); expect(mocks.save).not.toHaveBeenCalled()
})
it('does not offer save for a mismatched task response', async () => {
  mocks.api.mockImplementation((url: string) => Promise.resolve(url.endsWith('summary-children') ? links : { ...task, task_id: canonical }))
  mount(); await expand(); await screen.findByText(/状态无法读取/); expect(screen.queryByRole('button', { name: '恢复保存' })).not.toBeInTheDocument()
})
it('keeps records collapsed and orders verified updates newest first', async () => {
  const second = '5e8efb3a-98cc-4774-a5b0-d99794feec35'
  mocks.api.mockImplementation((url: string) => Promise.resolve(url.endsWith('summary-children') ? { ...links, items: [{ ...links.items[0], content_depth: 'detailed', presentation: 'text' }, { task_id: second, operation_id: operation, content_depth: 'concise', presentation: 'html' }] } : url.endsWith(second) ? { task_id: second, status: 'success', updated_at: '2026-11-03T00:00:00Z' } : { task_id: child, status: 'failed', updated_at: '2026-11-02T00:00:00Z' }))
  mount()
  const summary = await screen.findByText(/处理记录 · 2次/)
  expect(summary).toHaveTextContent('最近状态 · 已完成')
  expect(summary.parentElement).not.toHaveAttribute('open')
  await userEvent.click(summary)
  const section = screen.getByLabelText('关联纪要生成记录')
  const rows = within(section).getAllByText(/状态更新于/)
  expect(rows[0]).toHaveTextContent('精简 · HTML · 已完成')
  expect(rows[1]).toHaveTextContent('详细 · 文字 · 处理失败')
  expect(screen.getByText(`任务编号：${child}`).closest('details')).not.toHaveAttribute('open')
})
