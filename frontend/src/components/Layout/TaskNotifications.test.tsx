import { act, render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TaskNotifications } from './TaskNotifications'
import { useAuthStore } from '@/stores/authStore'
import { trackGenerationNotification } from '@/lib/taskNotifications'
const mock = vi.hoisted(() => ({ api: vi.fn(), native: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiJson: mock.api }))
vi.mock('@/lib/nativeTaskNotification', () => ({ deliverNativeNotification: mock.native, listenNativeNotification: async () => () => undefined, focusNotificationWindow: vi.fn() }))
beforeEach(() => {
  localStorage.clear(); vi.useFakeTimers(); mock.api.mockReset(); mock.native.mockReset()
  useAuthStore.setState({ user: { id: 'a' } as never })
  vi.spyOn(document, 'hasFocus').mockReturnValue(true)
})
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })
const mount = () => render(<MemoryRouter><TaskNotifications /></MemoryRouter>)
const accepted = () => localStorage.setItem('vinote:source-receipt:a:op', JSON.stringify({ id: 'task', operationId: 'op', meeting: false, submissionState: 'accepted', workspace: { scope: 'personal' }, sourceType: 'webpage', sourceUrl: 'https://example.com/article' }))
it('saves a tracked completed task before notifying even after leaving the generator', async () => {
  accepted(); trackGenerationNotification('a', { taskId: 'task', operationId: 'op', meeting: false })
  const saved = { id: 'saved', task_id: 'task', scope: 'personal', team_id: null, title: '学习笔记', content: '完整正文', created_at: new Date().toISOString() }
  let posted = false
  mock.api.mockImplementation(async (url: string, options?: { method?: string }) => {
    if (url.includes('/api/task/')) return { task_id: 'task', status: 'success', result: { task_id: 'task', title: '学习笔记', markdown: '完整正文' } }
    if (options?.method === 'POST') { posted = true; return saved }
    return posted ? [saved] : []
  })
  await act(async () => { mount() })
  expect(mock.api.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
  expect(screen.getByText('笔记整理已完成 · 学习笔记')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '打开笔记' })).toBeInTheDocument()
  await act(async () => { vi.advanceTimersByTime(9000) })
  expect(mock.api.mock.calls.filter(([, options]) => options?.method === 'POST')).toHaveLength(1)
})
it('never backfills historical terminal receipts when mounting notifications', async () => {
  accepted()
  mock.api.mockImplementation(async (url: string) => url.includes('/api/task/') ? { task_id: 'task', status: 'success', result: { task_id: 'task', title: '历史', markdown: '历史正文' } } : [])
  await act(async () => { mount() })
  expect(mock.api.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false)
  expect(screen.queryByRole('status')).toBeNull()
})
it('tracks across pages and emits one foreground completion with saved-note lookup', async () => {
  trackGenerationNotification('a', { taskId: 'task', meeting: false })
  mock.api.mockImplementation(async (url: string) => url.includes('/api/task/') ? { task_id: 'task', status: 'success' } : [{ id: 'saved', task_id: 'task' }])
  await act(async () => { mount() })
  expect(screen.getByText('笔记整理已完成')).toBeInTheDocument()
  expect(mock.native).not.toHaveBeenCalled()
  await act(async () => { vi.advanceTimersByTime(9000) })
  expect(mock.api).toHaveBeenCalledTimes(2)
})
it('falls back to application results when background native delivery fails', async () => {
  vi.mocked(document.hasFocus).mockReturnValue(false)
  trackGenerationNotification('a', { taskId: 'task', meeting: true })
  mock.api.mockResolvedValue({ task_id: 'task', status: 'failed' }); mock.native.mockRejectedValue(new Error('denied'))
  await act(async () => { mount() })
  expect(screen.getByText('会议纪要未完成')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '查看原因' })).toBeInTheDocument()
  expect(mock.native).toHaveBeenCalledTimes(1)
})
it('does not replay historical terminal receipts on mount', async () => {
  localStorage.setItem('vinote:source-receipt:a:op', JSON.stringify({ id: 'task', operationId: 'op', meeting: true }))
  mock.api.mockResolvedValue({ task_id: 'task', status: 'success' })
  await act(async () => { mount() })
  expect(screen.queryByRole('status')).toBeNull()
})
it('discards an old account response after account switch', async () => {
  trackGenerationNotification('a', { taskId: 'task', meeting: true })
  let resolve!: (value: unknown) => void
  mock.api.mockImplementation(() => new Promise(done => { resolve = done }))
  await act(async () => { mount() })
  await act(async () => { useAuthStore.setState({ user: { id: 'b' } as never }); resolve({ task_id: 'task', status: 'failed' }) })
  expect(screen.queryByRole('status')).toBeNull(); expect(mock.native).not.toHaveBeenCalled()
})
it('rejects the old response even when account switches A to B to A in one render batch', async () => {
  trackGenerationNotification('a', { taskId: 'task', meeting: true })
  let resolve!: (value: unknown) => void
  mock.api.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  mock.api.mockResolvedValue({ task_id: 'task', status: 'processing' })
  await act(async () => { mount() })
  await act(async () => {
    useAuthStore.setState({ user: { id: 'b' } as never })
    useAuthStore.setState({ user: { id: 'a' } as never })
    resolve({ task_id: 'task', status: 'failed' })
  })
  expect(screen.queryByRole('status')).toBeNull()
  expect(mock.native).not.toHaveBeenCalled()
})
