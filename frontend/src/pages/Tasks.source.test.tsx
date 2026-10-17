import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { Tasks } from './Tasks'
import { listPendingMeetings, type PendingMeeting } from '@/lib/audioStorage'
const api = vi.hoisted(() => ({ json: vi.fn(async (_path: string) => []) }))
vi.mock('@/lib/api', () => ({ apiJson: api.json }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 'owner' } }) }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: () => ({ details: {}, pending: [], items: [], lastSync: '' }) }))
vi.mock('@/hooks/useLibraryNotes', () => ({ useLibraryNotes: () => [], libraryNoteUrl: () => '/notes' }))
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }))
vi.mock('@/lib/feishu', () => ({ deliveryStatus: vi.fn(), loadPublishedDeliveries: vi.fn(async () => []) }))
vi.mock('@/lib/mcpConnections', () => ({ listMCPRuns: vi.fn(), mcpRunLabel: {} }))
beforeEach(() => { vi.clearAllMocks(); localStorage.clear() })
afterEach(() => { cleanup(); localStorage.clear() })
it('opens the exact retained recording from a failed recovery card without dispatching another task', async () => {
  vi.mocked(listPendingMeetings).mockResolvedValueOnce([{ id: 'real-record-id', options: { title: '失败录音' }, processingStatus: 'failed', processingError: '转写失败', startedAt: '2026-10-12T00:00:00Z' } as PendingMeeting])
  render(<MemoryRouter initialEntries={['/tasks?tab=generation&returnTo=%2Fmeetings%3Fq%3Dold']}><Tasks /></MemoryRouter>)
  const link = await screen.findByRole('link', { name: '查看原录音与恢复选项' })
  const url = new URL(link.getAttribute('href')!, 'https://vinote.invalid')
  expect(url.pathname).toBe('/files')
  expect(url.searchParams.get('file')).toBe('recording:real-record-id')
  expect(url.searchParams.get('type')).toBe('all')
  expect(url.searchParams.get('q')).toBe('')
  expect(url.searchParams.get('returnTo')).toBe('/tasks?tab=generation&returnTo=%2Fmeetings%3Fq%3Dold')
  expect(api.json.mock.calls.every(call => call[0] === '/api/workspace/jobs')).toBe(true)
})
it('finds owner-scoped unknown archived sources and links back with the original operation', async () => {
  const pending = { operationId: 'original-op', mode: 'url', meeting: false, submissionState: 'unknown' }
  localStorage.setItem('vinote:import-receipt:owner:note', JSON.stringify(pending))
  localStorage.setItem('vinote:source-receipt:owner:original-op', JSON.stringify(pending))
  localStorage.setItem('vinote:source-receipt:owner:reserved-op', JSON.stringify({ ...pending, operationId: 'reserved-op', submissionState: 'reserved' }))
  localStorage.setItem('vinote:source-receipt:other:private-op', JSON.stringify({ ...pending, operationId: 'private-op' }))
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  const links = await screen.findAllByRole('link', { name: '核验原提交' })
  expect(links.map(link => link.getAttribute('href'))).toEqual(['/generate?mode=url&operation=original-op', '/generate?mode=url&operation=reserved-op'])
  expect(screen.getByText(/已收到提交，排队状态待确认/)).toBeInTheDocument()
  await waitFor(() => expect(api.json).toHaveBeenCalledWith('/api/workspace/jobs'))
  expect(api.json).toHaveBeenCalledTimes(1)
})
it('keeps a failed archived task reachable when a different current source is selected', async () => {
  localStorage.setItem('vinote:source-receipt:owner:old-op', JSON.stringify({ operationId: 'old-op', id: 'old-task', meeting: false, mode: 'document', submissionState: 'accepted' }))
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: '查看原任务与处理记录' })).toHaveAttribute('href', '/generate?mode=file&operation=old-op')
})
it('keeps the originating filtered page when changing recovery categories', async () => {
  function LocationProbe() { return <output data-testid="location">{useLocation().search}</output> }
  render(<MemoryRouter initialEntries={['/tasks?returnTo=%2Ffiles%3Ftype%3Dvideo&tab=generation']}><Tasks /><LocationProbe /></MemoryRouter>)
  await waitFor(() => expect(api.json).toHaveBeenCalled())
  fireEvent.mouseDown(screen.getByRole('tab', { name: '飞书' }), { button: 0, ctrlKey: false })
  await waitFor(() => expect(screen.getByTestId('location').textContent).toContain('tab=feishu'))
  expect(screen.getByRole('link', { name: /返回文件库/ })).toHaveAttribute('href', '/files?type=video')
})

it('opens task-only archive directly without replacing a different active receipt', async () => {
  const current = JSON.stringify({ id: 'newer', meeting: true })
  localStorage.setItem('vinote:import-receipt:owner:meeting', current)
  localStorage.setItem('vinote:source-task-receipt:owner:old-task', JSON.stringify({ id: 'old-task', meeting: true, mode: 'file', submissionState: 'accepted' }))
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  const links = await screen.findAllByRole('link', { name: '查看原任务与处理记录' })
  expect(links.map(link => link.getAttribute('href'))).toContain('/generate?mode=file&meeting=1&task=old-task')
  expect(localStorage.getItem('vinote:import-receipt:owner:meeting')).toBe(current)
  expect(api.json.mock.calls.every(call => call[0] === '/api/workspace/jobs')).toBe(true)
})
