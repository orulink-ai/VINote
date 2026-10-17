import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
const api = vi.hoisted(() => ({ load: vi.fn(), remove: vi.fn(), loadNotes: vi.fn(), initialize: vi.fn(), archived: false, project: '' }))
vi.mock('@/stores/workspaceStore', async () => {
  const { create } = await import('zustand')
  return { useWorkspaceStore: create(() => ({ owner: 'owner-a', ready: true, busy: false, error: '', details: {}, items: [], mappings: {},
    loadDetail: api.load, changeDeleted: api.remove, initialize: api.initialize })) }
})
vi.mock('@/stores/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 'owner-a' } }) }))
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }))
vi.mock('@/stores/noteLibraryStore', () => ({ useNoteLibraryStore: () => ({ loading: false, error: '', loadNotes: api.loadNotes }) }))
vi.mock('@/stores/teamStore', () => ({ useTeamStore: () => ({ currentWorkspace: { scope: 'personal' } }) }))
vi.mock('@/hooks/useViewState', async () => {
  const { useState } = await import('react')
  return { useViewState: (_name: string, initial: unknown) => useState(initial) }
})
vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh', formatDate: () => '今天' }) }))
vi.mock('@/hooks/useLibraryNotes', async () => {
  const { useWorkspaceStore } = await import('@/stores/workspaceStore')
  return {
    libraryNoteUrl: (note: { id: string }) => `/workspace/${note.id}`,
    useLibraryNotes: () => {
      const details = useWorkspaceStore(s => s.details)
      return [
        { id: 'saved', title: '保存文档', workspaceKey: 'saved', sourceDevice: 'desktop' },
        { id: 'local', title: '导入文档', sourceDevice: 'mobile' },
      ].filter(note => !details[note.id]?.deleted).map(note => ({ ...note, status: 'done', sourceType: 'file', content: '正文',
        createdAt: '2026-10-12', archived: api.archived, project: api.project || undefined }))
    },
  }
})
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { Notes } from './Notes'
import { StorageSettings } from './StorageSettings'

const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollIntoView')
beforeEach(() => {
  vi.resetAllMocks()
  api.archived = false; api.project = ''
  useWorkspaceStore.setState({ owner: 'owner-a', ready: true, busy: false, details: {}, items: [], mappings: {}, error: '' })
})
afterEach(() => {
  cleanup()
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', originalScroll)
  else Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
})
function mount() { render(<MemoryRouter><Notes /></MemoryRouter>) }
function confirm(title = '保存文档') {
  fireEvent.click(screen.getByRole('button', { name: `删除《${title}》` }))
  expect(screen.getByRole('alertdialog')).toHaveTextContent(`将《${title}》移入回收站？`)
}
async function submit(label = '移入回收站') {
  await act(async () => fireEvent.click(screen.getByRole('button', { name: label })))
}
it('offers independent delete controls and cancellation keeps both records', () => {
  mount()
  expect(screen.getByRole('button', { name: '删除《保存文档》' }).parentElement?.closest('button')).toBeNull()
  confirm()
  expect(screen.getByRole('alertdialog')).toHaveTextContent('原文件与已发布飞书文档保留')
  fireEvent.click(screen.getByRole('button', { name: '保留笔记' }))
  expect(api.remove).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '删除《保存文档》' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '删除《导入文档》' })).toBeInTheDocument()
})
it('a confirmed tombstone removes only the selected content', async () => {
  api.remove.mockImplementation(async reference => {
    const receipt = { key: reference, deleted: true }
    useWorkspaceStore.setState({ details: { [reference]: receipt } as never })
    return receipt
  })
  mount(); confirm(); await submit()
  expect(api.remove).toHaveBeenCalledExactlyOnceWith('saved', true)
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '删除《保存文档》' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '删除《导入文档》' })).toBeInTheDocument()
  expect(api.load).not.toHaveBeenCalled()
})
it('passes the original local ID even when its mapping has no cached body', async () => {
  useWorkspaceStore.setState({ mappings: { local: { key: 'desktop-local', revision: 0, fingerprint: '' } } })
  api.remove.mockResolvedValue({ key: 'desktop-local', deleted: true })
  mount(); confirm('导入文档'); await submit()
  expect(api.remove).toHaveBeenCalledExactlyOnceWith('local', true)
  expect(api.load).not.toHaveBeenCalled()
})
it('a persistence failure keeps the target and retries only after another explicit click', async () => {
  api.remove.mockRejectedValueOnce(new Error('本机保存未落盘')).mockResolvedValueOnce({ key: 'local', deleted: true })
  mount(); confirm('导入文档'); await submit()
  expect(screen.getByRole('alert')).toHaveTextContent('本机保存未落盘')
  expect(screen.getByRole('alertdialog')).toHaveTextContent('将《导入文档》移入回收站？')
  expect(screen.getByRole('button', { name: '重试移入回收站' })).toBeEnabled()
  expect(api.remove).toHaveBeenCalledTimes(1)
  await submit('重试移入回收站')
  expect(api.remove.mock.calls).toEqual([['local', true], ['local', true]])
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
})
it('does not close the dialog or hide content without a confirmed deleted result', async () => {
  api.remove.mockResolvedValue(null)
  mount(); confirm(); await submit()
  expect(screen.getByRole('alert')).toHaveTextContent('移入回收站未完成')
  fireEvent.click(screen.getByRole('button', { name: '保留笔记' }))
  expect(screen.getByRole('button', { name: '删除《保存文档》' })).toBeInTheDocument()
  expect(api.remove).toHaveBeenCalledTimes(1)
})
it('blocks duplicate submissions until the first device write settles', async () => {
  let finish!: (value: { key: string; deleted: boolean }) => void
  api.remove.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  mount(); confirm()
  const action = screen.getByRole('button', { name: '移入回收站' })
  fireEvent.click(action); fireEvent.click(action)
  expect(api.remove).toHaveBeenCalledExactlyOnceWith('saved', true)
  expect(screen.getByRole('button', { name: '正在移入…' })).toBeDisabled()
  expect(screen.getByRole('button', { name: '保留笔记' })).toBeDisabled()
  await act(async () => finish({ key: 'saved', deleted: true }))
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
})
it('disables deletion while another device write is busy', () => {
  useWorkspaceStore.setState({ busy: true })
  mount()
  expect(screen.getByRole('button', { name: '删除《保存文档》' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '删除《保存文档》' }))
  expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  expect(api.remove).not.toHaveBeenCalled()
})
it('opens the canonical storage trash, focuses it and returns to the actual archived project and anchor', async () => {
  const scroll = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scroll })
  api.archived = true; api.project = '保留项目'
  const origin = '/notes?archived=1&project=保留项目#results'
  function Location() { const location = useLocation(); return <output aria-label="页面位置">{location.pathname + location.search + location.hash}</output> }
  await act(async () => {
    render(<MemoryRouter initialEntries={[origin]}><Location /><Routes>
      <Route path="/notes" element={<Notes />} />
      <Route path="/settings/storage" element={<StorageSettings />} />
    </Routes></MemoryRouter>)
  })
  const href = screen.getByRole('link', { name: '回收站' }).getAttribute('href')!
  const target = new URL(href, 'https://vinote.invalid')
  expect(target.pathname).toBe('/settings/storage')
  expect(target.hash).toBe('#trash')
  expect(decodeURIComponent(target.searchParams.get('returnTo')!)).toBe(origin)
  fireEvent.click(screen.getByRole('link', { name: '回收站' }))
  await waitFor(() => expect(screen.getByRole('heading', { name: '内容回收站' })).toHaveFocus())
  expect(scroll).toHaveBeenCalledWith({ block: 'start' })
  fireEvent.click(screen.getByRole('link', { name: '返回笔记' }))
  expect(decodeURIComponent(screen.getByLabelText('页面位置').textContent || '')).toBe(origin)
  expect(api.remove).not.toHaveBeenCalled()
  expect(api.initialize).not.toHaveBeenCalled()
})
