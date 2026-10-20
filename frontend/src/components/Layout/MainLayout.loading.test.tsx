import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
vi.mock('./Sidebar', () => ({ Sidebar: () => null }))
vi.mock('./WorkspaceSearchDialog', () => ({ WorkspaceSearchDialog: () => null }))
vi.mock('./SessionConnection', () => ({ SessionConnection: () => null }))
vi.mock('./SourceTaskProgress', () => ({ SourceTaskProgress: () => null }))
vi.mock('../MeetingRecorder/MeetingRecorderDock', () => ({ MeetingRecorderDock: () => null }))
vi.mock('@/hooks/useMeetingReturnScroll', () => ({ useMeetingReturnScroll: () => {} }))
vi.mock('@/components/ui/motion', () => ({ ProcessingWave: () => null, FadeUp: ({ children }: { children: ReactNode }) => <>{children}</> }))
vi.mock('@/components/ui/sidebar', () => ({ SidebarProvider: ({ children }: { children: ReactNode }) => <div>{children}</div>, SidebarTrigger: () => null }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: (selector: (value: unknown) => unknown) => selector({ user: { id: 'owner' } }) }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: { getState: () => ({ initialize: async () => {}, reset: () => {} }) } }))
vi.mock('../../stores/appModeStore', () => ({ APP_MODE_EVENT: 'fixture-mode', useAppModeStore: { getState: () => ({ reset: () => {}, load: async () => {} }) } }))
import { MainLayout } from './MainLayout'
const pending = new Promise<never>(() => {})
function SuspendedPage(): never { throw pending }
afterEach(cleanup)
it.each([
  ['?task=selected-task', undefined, '返回任务与恢复', '/tasks?tab=generation'],
  ['?meeting=1&mode=file&task=selected-task', undefined, '返回会议', '/meetings'],
  ['?task=selected-task&returnTo=%2Ffiles%3Fq%3Dkept', undefined, '返回文件库', '/files?q=kept'],
  ['?task=selected-task&returnTo=https%3A%2F%2Foutside.invalid', '/meetings?q=kept', '返回会议', '/meetings?q=kept'],
  ['?task=selected-task&returnTo=https%3A%2F%2Foutside.invalid', '//outside.invalid', '返回任务与恢复', '/tasks?tab=generation'],
  ['?mode=file', undefined, '返回笔记', '/notes'],
])('the actual suspended layout keeps the correct parent for %s', (search, returnTo, label, target) => {
  render(<MemoryRouter initialEntries={[{ pathname: '/generate', search, state: { returnTo } }]}><Routes><Route element={<MainLayout />}><Route path="/generate" element={<SuspendedPage />} /></Route></Routes></MemoryRouter>)
  expect(screen.getByText('正在打开页面…')).toBeVisible()
  expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', target)
  expect(screen.getAllByRole('link')).toHaveLength(1)
})
