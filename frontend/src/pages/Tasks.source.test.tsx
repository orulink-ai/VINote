import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { Tasks } from './Tasks'
import { listPendingMeetings, type PendingMeeting } from '@/lib/audioStorage'
import { versionRejectionKey } from '@/lib/meetingVersionRecovery'
import { deliveryStatus } from '@/lib/feishu'
import { listMCPRuns } from '@/lib/mcpConnections'
import { useLibraryNotes } from '@/hooks/useLibraryNotes'
const api = vi.hoisted(() => ({ json: vi.fn(async (_path: string) => []) }))
vi.mock('@/lib/api', () => ({ apiJson: api.json }))
vi.mock('@/stores/authStore', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ user: { id: 'owner' } }) }))
vi.mock('@/stores/workspaceStore', () => ({ useWorkspaceStore: () => ({ details: {}, pending: [], items: [], lastSync: '' }) }))
vi.mock('@/hooks/useLibraryNotes', () => ({ useLibraryNotes: vi.fn(() => []), libraryNoteUrl: () => '/notes' }))
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }))
vi.mock('@/lib/feishu', () => ({ deliveryStatus: vi.fn(), loadPublishedDeliveries: vi.fn(async () => []) }))
vi.mock('@/lib/mcpConnections', () => ({ listMCPRuns: vi.fn(), mcpRunLabel: {} }))
beforeEach(() => { vi.clearAllMocks(); localStorage.clear() })
afterEach(() => { cleanup(); localStorage.clear() })
it('shows device receipts and refreshes without dispatching the cancelled workspace jobs API', async () => {
  api.json.mockRejectedValue(new Error('Not Found'))
  localStorage.setItem('vinote:source-receipt:owner:current-device', JSON.stringify({ operationId: 'current-device', meeting: true, submissionState: 'unknown' }))
  render(<MemoryRouter initialEntries={['/tasks?returnTo=%2Fgenerate%3Fmeeting%3D1%26operation%3DB']}><Tasks /></MemoryRouter>)
  await screen.findByRole('link', { name: '核验原提交' })
  await waitFor(() => expect(screen.getByRole('button', { name: '刷新状态' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  await waitFor(() => expect(listPendingMeetings).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(screen.getByRole('button', { name: '刷新状态' })).toBeEnabled())
  expect(api.json).not.toHaveBeenCalled()
  expect(screen.queryByText('Not Found')).toBeNull()
  expect(screen.getByRole('link', { name: '核验原提交' })).toHaveAttribute('href', '/generate?mode=file&meeting=1&operation=current-device')
  expect(localStorage.getItem('vinote:source-receipt:owner:current-device')).toBeTruthy()
})

it('still surfaces a genuine device history read error instead of hiding errors generally', async () => {
  vi.mocked(listPendingMeetings).mockRejectedValueOnce(new Error('Device history unavailable'))
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  expect(await screen.findByText('Device history unavailable')).toBeVisible()
  expect(screen.getByRole('button', { name: '重试' })).toBeVisible()
  expect(api.json).not.toHaveBeenCalled()
})

it('retains the explicit Feishu receipt read without any workspace job request', async () => {
  vi.mocked(useLibraryNotes).mockReturnValueOnce([{ id: 'saved-note', title: '已保存会议' } as never])
  vi.mocked(deliveryStatus).mockResolvedValueOnce({ status: 'completed' } as never)
  render(<MemoryRouter initialEntries={['/tasks?tab=feishu']}><Tasks /></MemoryRouter>)
  expect(await screen.findByText('已保存会议')).toBeVisible()
  expect(deliveryStatus).toHaveBeenCalledWith('saved-note')
  expect(screen.getByRole('link', { name: '打开交付记录并恢复失败步骤' })).toBeVisible()
  expect(api.json).not.toHaveBeenCalled()
})

it('retains the MCP read and its own 404 error instead of suppressing all Not Found results', async () => {
  vi.mocked(listMCPRuns).mockRejectedValueOnce(new Error('MCP Not Found'))
  render(<MemoryRouter initialEntries={['/tasks?tab=mcp']}><Tasks /></MemoryRouter>)
  expect(await screen.findByText('MCP Not Found')).toBeVisible()
  expect(listMCPRuns).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('button', { name: '重试' })).toBeVisible()
  expect(api.json).not.toHaveBeenCalled()
})

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
  expect(api.json).not.toHaveBeenCalled()
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
  await waitFor(() => expect(screen.queryByText('正在更新任务状态…')).toBeNull())
  expect(api.json).not.toHaveBeenCalled()
})
it('keeps a failed archived task reachable when a different current source is selected', async () => {
  localStorage.setItem('vinote:source-receipt:owner:old-op', JSON.stringify({ operationId: 'old-op', id: 'old-task', meeting: false, mode: 'document', submissionState: 'accepted' }))
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: '查看原任务与处理记录' })).toHaveAttribute('href', '/generate?mode=file&operation=old-op')
})
it('keeps the originating filtered page when changing recovery categories', async () => {
  function LocationProbe() { return <output data-testid="location">{useLocation().search}</output> }
  render(<MemoryRouter initialEntries={['/tasks?returnTo=%2Ffiles%3Ftype%3Dvideo&tab=generation']}><Tasks /><LocationProbe /></MemoryRouter>)
  await waitFor(() => expect(screen.queryByText('正在更新任务状态…')).toBeNull())
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
  expect(api.json).not.toHaveBeenCalled()
})

function version(operationId: string, title: string, model: string, extra = {}) {
  const origin = 'https://frozen.invalid'
  return { operationId, owner: 'owner', parentTaskId: 'parent', summaryNoteId: 'parent-note', meetingVersion: true,
    meeting: true, independentGeneration: true, asrMode: 'reuse', summaryOnly: true, origin,
    modelConnection: { server_url: origin }, modelName: model, contentDepth: 'concise', presentation: 'text',
    createdAt: '2026-10-20T12:00:00Z', submissionState: 'accepted', mode: 'file',
    meetingVersionContext: { protocol: 1, parent_task_id: 'parent', context_revision: 'a'.repeat(64),
      source: { version: 'b'.repeat(64), type: 'video', title } }, ...extra }
}

it('distinguishes concurrent typed versions by frozen title/model/form and submission time without querying models', async () => {
  localStorage.setItem('vinote:source-receipt:owner:A', JSON.stringify(version('A', '会议 A', 'Luna')))
  localStorage.setItem('vinote:source-receipt:owner:B', JSON.stringify(version('B', '会议 B', 'Deepseek',
    { presentation: 'infographic', contentDepth: 'detailed', createdAt: '2026-10-20T13:00:00Z' })))
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  const a = (await screen.findByRole('heading', { name: '会议 A · 新版本' })).closest('article')!
  const b = screen.getByRole('heading', { name: '会议 B · 新版本' }).closest('article')!
  expect(within(a).getByText('Luna')).toBeVisible()
  expect(within(b).getByText('Deepseek')).toBeVisible()
  expect(within(b).getByText('详细 · 信息图')).toBeVisible()
  expect(a.querySelector('time')).toHaveAttribute('datetime', '2026-10-20T12:00:00Z')
  expect(b.querySelector('time')).toHaveAttribute('datetime', '2026-10-20T13:00:00Z')
  expect(within(a).getByRole('link')).toHaveAttribute('href', '/generate?mode=file&meeting=1&operation=A')
  expect(api.json).not.toHaveBeenCalled()
})

it('retains typed nonacceptance audits in history with their original operation route', async () => {
  localStorage.setItem('vinote:source-receipt:owner:rejected', JSON.stringify(version('rejected', '未受理会议', 'Luna', {
    submissionState: 'not_accepted', preflightRejection: { protocol: 1, status: 409,
      code: 'meeting_version_context_changed', message: '重新核验。' },
  })))
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: '查看未受理记录' })).toHaveAttribute('href', '/generate?mode=file&meeting=1&operation=rejected')
  expect(screen.getByText(/本次未受理，未创建任务/)).toBeVisible()
  expect(localStorage.getItem('vinote:source-receipt:owner:rejected')).toBeTruthy()
})

it.each(['unknown', 'accepted', 'reserved'])('reads the separate audit without hiding current %s execution state', async state => {
  const key = 'vinote:source-receipt:owner:separate'
  const pending = JSON.stringify(version('separate', '独立审计会议', 'Luna', { submissionState: 'unknown' }))
  localStorage.setItem(key, state === 'unknown' ? pending : JSON.stringify(version('separate', '独立审计会议', 'Luna', { id: 'real-child', submissionState: state })))
  localStorage.setItem(versionRejectionKey('owner', 'separate'), JSON.stringify({ pending,
    rejection: { protocol: 1, status: 409, code: 'meeting_version_context_changed', message: 'changed' } }))
  const raw = localStorage.getItem(key)
  render(<MemoryRouter><Tasks /></MemoryRouter>)
  await screen.findByRole('heading', { name: '独立审计会议 · 新版本' })
  if (state === 'unknown') expect(screen.getByRole('link', { name: '查看未受理记录' })).toBeVisible()
  else expect(screen.queryByRole('link', { name: '查看未受理记录' })).toBeNull()
  expect(localStorage.getItem(key)).toBe(raw)
  expect(api.json).not.toHaveBeenCalled()
})

it.each([{ owner: 'other' }, { origin: 'https://changed.invalid' }, { createdAt: 'invalid' }])(
  'does not expose unverified version metadata for %j', async extra => {
    localStorage.setItem('vinote:source-receipt:owner:bad', JSON.stringify(version('bad', 'unverified title', 'unverified model', extra)))
    render(<MemoryRouter><Tasks /></MemoryRouter>)
    await screen.findByRole('link', { name: '查看原任务与处理记录' })
    expect(screen.queryByText(/unverified/)).toBeNull()
  })
