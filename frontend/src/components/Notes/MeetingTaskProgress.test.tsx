import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { MeetingTaskProgress } from './MeetingTaskProgress'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import type { NoteRecord } from '@/stores/noteLibraryStore'
const library = vi.hoisted(() => ({ loadNoteById: vi.fn() }))
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => library }))
const api = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ apiJson: api }))
const note = { id: 'n1', taskId: 't1', status: 'pending' } as NoteRecord
beforeEach(() => { vi.resetAllMocks(); useAuthStore.setState({ user: { id: 'owner' } as never }); useAppModeStore.setState({ config: { server_url: 'https://example.invalid' } as never }) })
const show = () => render(<MemoryRouter><MeetingTaskProgress note={note} returnTo='/note/n1?returnTo=%2Fmeetings' zh /></MemoryRouter>)
it('shows actual stage and unknown progress without replaying a task', async () => {
  api.mockResolvedValue({ task_id: 't1', status: 'transcribing', message: '正在转写完整录音', progress: null })
  show()
  expect(await screen.findByText('正在转写完整录音')).toBeVisible()
  expect(screen.getByText('服务暂未提供识别百分比')).toBeVisible()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: '查看原任务' })).toHaveAttribute('href', '/generate?meeting=1&task=t1&returnTo=%2Fnote%2Fn1%3FreturnTo%3D%252Fmeetings')
  expect(api.mock.calls.every(([path, options]) => path === '/api/task/t1' && !options.method)).toBe(true)
})
it('rejects a mismatched task response and never labels it complete', async () => {
  api.mockResolvedValue({ task_id: 'other', status: 'success' }); show()
  expect(await screen.findByText('暂时无法读取任务进度')).toBeVisible()
})
it('does not show a late response after the account changes', async () => {
  let resolve!: (data: unknown) => void
  api.mockImplementation(() => new Promise(done => { resolve = done })); show()
  await waitFor(() => expect(api).toHaveBeenCalled())
  act(() => useAuthStore.setState({ user: null }))
  await act(async () => resolve({ task_id: 't1', status: 'transcribing', message: '旧账号内容' }))
  expect(screen.queryByText('旧账号内容')).not.toBeInTheDocument()
})
it('polls the same task and renders only measured transcription progress', async () => {
  vi.useFakeTimers()
  try {
    api.mockResolvedValueOnce({ task_id: 't1', status: 'transcribing', progress: 99 })
      .mockResolvedValueOnce({ task_id: 't1', status: 'transcribing', progress: 99, processed_seconds: 30, total_seconds: 120 })
    const view = show()
    await act(async () => {})
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '25')
    expect(screen.getByText('0:30 / 2:00 · 25%')).toBeVisible()
    view.unmount()
    await act(async () => { await vi.advanceTimersByTimeAsync(10000) })
    expect(api).toHaveBeenCalledTimes(2)
  } finally { vi.useRealTimers() }
})
it.each(['pending', 'queued', 'downloading'])('accepts legitimate %s task status', async status => {
  api.mockResolvedValue({ task_id: 't1', status }); show()
  await waitFor(() => expect(api).toHaveBeenCalled())
  expect(screen.queryByText('暂时无法读取任务进度')).not.toBeInTheDocument()
  expect(screen.queryByText('正在读取原任务…')).not.toBeInTheDocument()
})
it.each([{ status: 'success' }, { status: 'success', result: { task_id: 'other', title: '标题', markdown: '正文' } }])('rejects incomplete or mismatched success results', async data => {
  api.mockResolvedValue({ task_id: 't1', ...data }); show()
  expect(await screen.findByText('暂时无法读取任务进度')).toBeVisible()
})
it('does not fabricate full completion from inconsistent duration measurements', async () => {
  api.mockResolvedValue({ task_id: 't1', status: 'transcribing', processed_seconds: 150, total_seconds: 120 }); show()
  expect(await screen.findByText('服务暂未提供识别百分比')).toBeVisible()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})
it('bounds a stalled read and allows a manual read again', async () => {
  vi.useFakeTimers()
  try {
    api.mockImplementation((_path, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('Aborted')))))
    const view = show()
    await act(async () => { await vi.advanceTimersByTimeAsync(15000) })
    expect(screen.getByText('暂时无法读取任务进度')).toBeVisible()
    expect(screen.getByRole('button', { name: '重新读取' })).toBeVisible()
    view.unmount()
  } finally { vi.useRealTimers() }
})
it('shows a terminal failure instead of its stale active stage', async () => {
  api.mockResolvedValue({ task_id: 't1', status: 'failed', stage: 'transcribing' }); show()
  expect(await screen.findByText('处理未完成')).toBeVisible()
  expect(screen.queryByText('正在转写')).not.toBeInTheDocument()
})
it('polls saved-note readback after success and opens the matching saved result explicitly', async () => {
  vi.useFakeTimers()
  try {
    api.mockResolvedValue({ task_id: 't1', status: 'success', result: { title: '纪要', markdown: '正文' } })
    const saved = { ...note, status: 'done', title: '纪要', content: '正文' }
    library.loadNoteById.mockResolvedValueOnce(note).mockResolvedValueOnce(saved)
    const onSaved = vi.fn()
    const view = render(<MemoryRouter><MeetingTaskProgress note={note} returnTo='/note/n1' zh onSaved={onSaved} /></MemoryRouter>)
    await act(async () => {})
    expect(screen.queryByRole('button', { name: '查看已保存纪要' })).not.toBeInTheDocument()
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(screen.getByRole('button', { name: '查看已保存纪要' })).toBeVisible()
    expect(onSaved).not.toHaveBeenCalled()
    act(() => screen.getByRole('button', { name: '查看已保存纪要' }).click())
    expect(onSaved).toHaveBeenCalledWith(saved)
    expect(api).toHaveBeenCalledTimes(1)
    view.unmount()
  } finally { vi.useRealTimers() }
})
it('does not offer a stale saved result after navigating to another detail', async () => {
  api.mockResolvedValue({ task_id: 't1', status: 'success', result: { title: '纪要', markdown: '正文' } })
  let resolve!: (data: NoteRecord) => void
  library.loadNoteById.mockImplementation(() => new Promise(done => { resolve = done }))
  const onSaved = vi.fn()
  const view = render(<MemoryRouter><MeetingTaskProgress note={note} returnTo='/note/n1' zh onSaved={onSaved} /></MemoryRouter>)
  await waitFor(() => expect(library.loadNoteById).toHaveBeenCalled())
  view.rerender(<MemoryRouter><MeetingTaskProgress note={{ ...note, id: 'n2', taskId: 't2' }} returnTo='/note/n2' zh onSaved={onSaved} /></MemoryRouter>)
  await act(async () => resolve({ ...note, status: 'done', title: '纪要', content: '正文' }))
  expect(screen.queryByRole('button', { name: '查看已保存纪要' })).not.toBeInTheDocument()
  expect(onSaved).not.toHaveBeenCalled()
})
it('requires explicit draft discard before opening a saved result', async () => {
  api.mockResolvedValue({ task_id: 't1', status: 'success', result: { title: '纪要', markdown: '正文' } })
  library.loadNoteById.mockResolvedValue({ ...note, status: 'done', title: '纪要', content: '正文' })
  const onSaved = vi.fn()
  render(<MemoryRouter><MeetingTaskProgress note={note} returnTo='/note/n1' zh hasUnsavedChanges onSaved={onSaved} /></MemoryRouter>)
  const button = await screen.findByRole('button', { name: '查看已保存纪要' })
  act(() => button.click())
  expect(onSaved).not.toHaveBeenCalled()
  act(() => screen.getByRole('button', { name: '保留草稿' }).click())
  expect(onSaved).not.toHaveBeenCalled()
  act(() => button.click())
  act(() => screen.getByRole('button', { name: '放弃草稿并查看' }).click())
  expect(onSaved).toHaveBeenCalledTimes(1)
  expect(library.loadNoteById).toHaveBeenCalledWith('n1', { fresh: true })
})
