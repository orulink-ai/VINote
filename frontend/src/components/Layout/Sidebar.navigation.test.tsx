import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { SidebarProvider } from '@/components/ui/sidebar'
import { useNoteLibraryStore, type NoteRecord } from '@/stores/noteLibraryStore'
import { apiJson } from '@/lib/api'

vi.mock('@/lib/i18n', () => ({ useI18n: () => ({ locale: 'zh-CN' }) }))
vi.mock('@/lib/api', () => ({ apiJson: vi.fn() }))
vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: () => ({ user: { id: 'owner', email: 'user@example.invalid' }, signOut: vi.fn() }) }))
vi.mock('@/stores/meetingRecorderStore', () => ({ useMeetingRecorderStore: () => ({ phase: 'idle', hasRecoverableRecording: false, localRecordingSaved: false }) }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: (select: (state: { pending: unknown[] }) => unknown) => select({ pending: [] }) }))
const loadTeams = vi.hoisted(() => vi.fn())
vi.mock('@/stores/teamStore', () => ({ useTeamStore: () => ({ teams: [], currentWorkspace: { scope: 'personal' }, loadTeams, selectPersonalWorkspace: vi.fn(), selectTeamWorkspace: vi.fn() }) }))

function renderSidebar(path: string, returnTo?: string) {
  const url = new URL(path, 'https://vinote.invalid')
  render(<MemoryRouter initialEntries={[{ pathname: url.pathname, search: url.search, hash: url.hash, state: returnTo ? { returnTo } : undefined }]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><SidebarProvider><Sidebar onSearch={vi.fn()} /></SidebarProvider></MemoryRouter>)
}
beforeEach(() => { useNoteLibraryStore.getState().reset(); vi.clearAllMocks() })
afterEach(cleanup)

describe('Sidebar loaded note identity', () => {
  const note = (id: string, sourceType: string): NoteRecord => ({ id, sourceType, title: '同一个标题', content: '已保存正文', status: 'done', scope: 'personal', createdAt: '', updatedAt: '' })

  it.each([undefined, '/tasks?tab=generation', '/generate?meeting=1&operation=source', '/note/parent?view=transcript', '/files?type=video'])(
    'keeps a saved meeting selected after generation/recovery or reload regardless of return route %s', parent => {
      useNoteLibraryStore.setState({ notes: [note('saved-meeting', 'meeting_video')] })
      renderSidebar('/note/saved-meeting', parent)
      expect(screen.getByRole('link', { name: '会议' })).toHaveAttribute('aria-current', 'page')
      expect(screen.getByRole('link', { name: '笔记' })).not.toHaveAttribute('aria-current')
      expect(apiJson).not.toHaveBeenCalled()
    })

  it('updates when the exact note detail is loaded without issuing another request', () => {
    useNoteLibraryStore.setState({ notes: [note('unrelated', 'meeting_video')] })
    renderSidebar('/note/loaded-later', '/tasks?tab=generation')
    expect(screen.getByRole('link', { name: '笔记' })).toHaveAttribute('aria-current', 'page')
    act(() => useNoteLibraryStore.setState({ notes: [note('loaded-later', 'meeting_recording')] }))
    expect(screen.getByRole('link', { name: '会议' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: '笔记' })).not.toHaveAttribute('aria-current')
    expect(apiJson).not.toHaveBeenCalled()
  })

  it('uses the saved nonmeeting type even when opened from meetings', () => {
    useNoteLibraryStore.setState({ notes: [note('ordinary-note', 'video')] })
    renderSidebar('/note/ordinary-note', '/meetings?q=kept')
    expect(screen.getByRole('link', { name: '笔记' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: '会议' })).not.toHaveAttribute('aria-current')
  })

  it.each(['/meetings-invalid', 'https://outside.invalid/meetings'])(
    'does not classify an unknown note from an invalid meeting-prefix parent %s', parent => {
      renderSidebar('/note/not-loaded', parent)
      expect(screen.getByRole('link', { name: '笔记' })).toHaveAttribute('aria-current', 'page')
    })

  it('retains a validated meetings context while the exact note identity is loading', () => {
    renderSidebar('/note/not-loaded', '/meetings?q=kept')
    expect(screen.getByRole('link', { name: '会议' })).toHaveAttribute('aria-current', 'page')
  })
})

describe('Sidebar settings return context', () => {
  it('shows meetings and notes as separate navigation destinations', () => {
    renderSidebar('/meetings')
    expect(screen.getByRole('link', { name: '会议' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: '笔记' })).not.toHaveAttribute('aria-current')
    expect(screen.queryByRole('link', { name: '会议与笔记' })).not.toBeInTheDocument()
  })
  it('carries the current list query and hash into settings', () => {
    const parent = '/meetings?archived=1&q=pdf#selected'
    renderSidebar(parent)
    const target = new URL(screen.getByRole('link', { name: '设置' }).getAttribute('href')!, 'https://vinote.invalid')
    expect(target.pathname).toBe('/settings')
    expect(target.searchParams.get('returnTo')).toBe(parent)
  })

  it('reuses the original parent from a settings subpage instead of nesting settings', () => {
    const parent = '/notes?q=word#selected'
    renderSidebar('/settings?' + new URLSearchParams({ tab: 'models', returnTo: parent }).toString())
    const target = new URL(screen.getByRole('link', { name: '设置' }).getAttribute('href')!, 'https://vinote.invalid')
    expect(target.searchParams.get('returnTo')).toBe(parent)
    expect(target.searchParams.has('tab')).toBe(false)
  })

  it.each(['https://outside.invalid', '//outside.invalid', '/settings?tab=profile'])('rejects an unsafe or self-referential settings parent (%s)', parent => {
    renderSidebar('/settings?' + new URLSearchParams({ tab: 'profile', returnTo: parent }).toString())
    const target = new URL(screen.getByRole('link', { name: '设置' }).getAttribute('href')!, 'https://vinote.invalid')
    expect(target.searchParams.has('returnTo')).toBe(false)
  })

  it('keeps the external source through the storage section parent of the sync page', () => {
    const parent = '/meetings?archived=1&q=pdf#selected'
    const section = '/settings?' + new URLSearchParams({ tab: 'storage', returnTo: parent }).toString()
    renderSidebar('/settings/sync?' + new URLSearchParams({ returnTo: section }).toString())
    expect(new URL(screen.getByRole('link', { name: '设置' }).getAttribute('href')!, 'https://vinote.invalid').searchParams.get('returnTo')).toBe(parent)
  })

  it('carries the same context through the account menu and still permits draft protection to block navigation', async () => {
    const parent = '/meetings?archived=1&q=pdf#selected'
    renderSidebar(parent)
    const guarded = vi.fn((event: Event) => event.preventDefault())
    window.addEventListener('vinote:check-navigation', guarded)
    try {
      screen.getByRole('button', { name: '账号菜单' }).focus()
      await userEvent.keyboard('{Enter}')
      await userEvent.click(await screen.findByRole('menuitem', { name: '账号与个人资料' }))
      expect(guarded).toHaveBeenCalledTimes(1)
      const target = new URL((guarded.mock.calls[0][0] as CustomEvent<{ to: string }>).detail.to, 'https://vinote.invalid')
      expect(target.searchParams.get('tab')).toBe('profile')
      expect(target.searchParams.get('returnTo')).toBe(parent)
      expect(screen.getByRole('link', { name: '会议' })).toHaveAttribute('aria-current', 'page')
    } finally { window.removeEventListener('vinote:check-navigation', guarded) }
  })
})
