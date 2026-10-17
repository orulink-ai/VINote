import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
const api = vi.hoisted(() => ({ save: vi.fn() }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: (select: (s: unknown) => unknown) => select({ user: { id: 'owner-a' } }) }))
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand')
  return { useWorkspaceStore: create(() => ({ ready: true, busy: false, details: {}, pending: [], save: api.save })) }
})
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { WriteNote } from './WriteNote'
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear()
  useWorkspaceStore.setState({ ready: true, busy: false, pending: [], details: {} })
})
afterEach(cleanup)

it('a durable local save opens the same content and clears its protected draft only after persistence', async () => {
  api.save.mockImplementation(async (key, body) => {
    useWorkspaceStore.setState({ pending: [{ key, body, locallyQueued: true }], details: { [key]: { key, ...body, revision: 0 } } } as never)
    expect(localStorage.getItem('vinote:draft:owner-a:write-note')).toContain('保留这份原始内容')
    return { key, ...body, revision: 0 }
  })
  render(<MemoryRouter initialEntries={['/write']}><Routes><Route path="/write" element={<WriteNote />} /><Route path="/workspace/:key" element={<LocationReceipt />} /></Routes></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('正文'), { target: { value: '保留这份原始内容' } })
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '保存笔记' })))
  expect(api.save).toHaveBeenCalledTimes(1)
  const [key, body] = api.save.mock.calls[0]
  expect(body.title).toMatch(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}｜待整理/)
  expect(screen.getByText('/workspace/' + key + '?' + new URLSearchParams({ returnTo: '/notes' }))).toBeInTheDocument()
  expect(localStorage.getItem('vinote:draft:owner-a:write-note')).toBeNull()
})

it('a local cache candidate does not clear the draft before failed persistence rolls it back', async () => {
  api.save.mockImplementation(async (key, body) => {
    await act(async () => useWorkspaceStore.setState({ pending: [{ key, body, locallyQueued: true }], details: { [key]: { key, ...body, revision: 0 } } } as never))
    expect(localStorage.getItem('vinote:draft:owner-a:write-note')).toContain('保留这份原始内容')
    useWorkspaceStore.setState({ details: {}, pending: [] })
    throw new Error('本机保存未落盘')
  })
  mount()
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '保存笔记' })))
  expect(screen.getByText('本机保存未落盘')).toBeInTheDocument()
  expect(localStorage.getItem('vinote:draft:owner-a:write-note')).toContain('保留这份原始内容')
  expect(screen.getByLabelText('正文')).toBeEnabled()
})
function LocationReceipt() { const location = useLocation(); return <p>{location.pathname + location.search + location.hash}</p> }
function mount() {
  render(<MemoryRouter initialEntries={['/write']}><Routes><Route path="/write" element={<WriteNote />} /><Route path="/tasks" element={<p>处理记录页</p>} /></Routes></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('正文'), { target: { value: '保留这份原始内容' } })
}
it('an unconfirmed save preserves its original request and sends the user to recovery', async () => {
  api.save.mockImplementation(async (key, body) => {
    useWorkspaceStore.setState({ pending: [{ key, body, error: 'Network timeout' }] })
    return null
  })
  mount()
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '保存笔记' })))
  expect(api.save).toHaveBeenCalledTimes(1)
  expect(screen.getByLabelText('正文')).toBeDisabled()
  expect(localStorage.getItem('vinote:draft:owner-a:write-note')).toContain('保留这份原始内容')
  fireEvent.click(screen.getByRole('button', { name: '查看保存结果与重试' }))
  expect(screen.getByText('处理记录页')).toBeInTheDocument()
  expect(api.save).toHaveBeenCalledTimes(1)
})
it.each(['/notes?project=release&q=review#selected', 'https://outside.invalid/notes'])('preserves a validated writing parent on leave: %s', parent => {
  const expected = parent.startsWith('/') ? parent : '/notes'
  render(<MemoryRouter initialEntries={['/write?' + new URLSearchParams({ returnTo: parent })]}><Routes><Route path="/write" element={<WriteNote />} /><Route path="/notes" element={<LocationReceipt />} /></Routes></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('正文'), { target: { value: 'offline draft' } })
  fireEvent.click(screen.getByRole('button', { name: '保存草稿并返回' }))
  expect(screen.getByText(expected)).toBeInTheDocument()
  expect(localStorage.getItem('vinote:draft:owner-a:write-note')).toContain('offline draft')
})
it('a saved detail carries the original filtered parent through its URL', async () => {
  const parent = '/notes?project=release&q=review#selected'
  api.save.mockResolvedValue({ key: 'saved-a' })
  render(<MemoryRouter initialEntries={['/write?' + new URLSearchParams({ returnTo: parent })]}><Routes><Route path="/write" element={<WriteNote />} /><Route path="/workspace/:key" element={<LocationReceipt />} /></Routes></MemoryRouter>)
  fireEvent.change(screen.getByLabelText('正文'), { target: { value: 'saved text' } })
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '保存笔记' })))
  expect(screen.getByText('/workspace/saved-a?' + new URLSearchParams({ returnTo: parent }))).toBeInTheDocument()
})
it('a later receipt becomes a saved note instead of offering a second submission', async () => {
  api.save.mockImplementation(async (key, body) => { useWorkspaceStore.setState({ pending: [{ key, body }] }); return null })
  mount()
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '保存笔记' })))
  const operation = useWorkspaceStore.getState().pending[0]
  act(() => useWorkspaceStore.setState({ pending: [], details: { [operation.key]: {
    key: operation.key, title: operation.body.title, content: operation.body.content, source_type: 'text', source_device: 'desktop',
    revision: 1, deleted: false, archived: false, version_count: 1, metadata: {}, transcript: null, versions: [], next_versions_offset: null,
    created_at: '2026-10-11', updated_at: '2026-10-11',
  } } }))
  expect(screen.getByRole('button', { name: '打开已保存笔记' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: '保存笔记' })).not.toBeInTheDocument()
  expect(localStorage.getItem('vinote:draft:owner-a:write-note')).toBeNull()
  expect(api.save).toHaveBeenCalledTimes(1)
})
