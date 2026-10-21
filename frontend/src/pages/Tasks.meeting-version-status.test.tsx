import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { Tasks } from './Tasks'
import { useAuthStore } from '@/stores/authStore'
import { meetingVersionOperationKey } from '@/lib/meetingVersion'
import { listPendingMeetings } from '@/lib/audioStorage'

const api = vi.hoisted(() => ({ json: vi.fn() }))
vi.mock('@/lib/api', () => ({ apiJson: api.json }))
vi.mock('@/hooks/useLibraryNotes', () => ({ useLibraryNotes: () => [], libraryNoteUrl: () => '/notes' }))
vi.mock('@/lib/audioStorage', () => ({ listPendingMeetings: vi.fn(async () => []) }))
vi.mock('@/lib/feishu', () => ({ deliveryStatus: vi.fn() }))
vi.mock('@/lib/mcpConnections', () => ({ listMCPRuns: vi.fn(), mcpRunLabel: {} }))

const pointer = meetingVersionOperationKey('owner', 'parent', 'parent-note')
function receipt(op: string, extra = {}) {
  return { operationId: op, id: `${op}-child`, owner: 'owner', parentTaskId: 'parent', summaryNoteId: 'parent-note',
    meeting: true, meetingVersion: true, independentGeneration: true, summaryOnly: true, asrMode: 'reuse',
    origin: 'https://frozen.invalid', modelConnection: { server_url: 'https://frozen.invalid' }, modelName: 'frozen-model',
    contentDepth: 'detailed', presentation: 'text', workspace: { scope: 'personal' }, mode: 'file',
    createdAt: '2026-10-20T16:00:00Z', submissionState: 'accepted',
    meetingVersionContext: { protocol: 1, parent_task_id: 'parent', context_revision: 'a'.repeat(64),
      source: { version: 'b'.repeat(64), type: 'video', title: '2026-10-19 18:02｜待生成纪要' } }, ...extra }
}
function keep(op: string, extra = {}) {
  localStorage.setItem(`vinote:source-receipt:owner:${op}`, JSON.stringify(receipt(op, extra)))
}
function snapshot() { return Object.fromEntries(Object.keys(localStorage).map(key => [key, localStorage.getItem(key)])) }
function show() { return render(<MemoryRouter initialEntries={['/tasks?tab=generation']}><Tasks /></MemoryRouter>) }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => {
  vi.resetAllMocks(); localStorage.clear()
  useAuthStore.setState({ user: { id: 'owner' } as never })
  localStorage.setItem(pointer, 'A')
  api.json.mockImplementation(async (path: string) => {
    const op = /source-requests\/([^/]+)$/.exec(path)?.[1]
    if (op) return { operation_id: op, task_id: `${op}-child`, state: 'accepted' }
    throw new Error(`Unexpected read: ${path}`)
  })
})
afterEach(() => { cleanup(); localStorage.clear() })

it('reads both original tasks and distinguishes generated-unsaved from failed without changing receipts or pointers', async () => {
  keep('A'); keep('B')
  const before = snapshot(); const fallback = api.json.getMockImplementation()!
  api.json.mockImplementation(async (path, init) => {
    if (path === '/api/task/A-child') return { task_id: 'A-child', status: 'success', result: { task_id: 'A-child', title: '真实会议主题', markdown: '# 真实会议主题\n\n正文' } }
    if (path === '/api/task/B-child') return { task_id: 'B-child', status: 'failed', failed_stage: 'summarizing', retryable: true }
    if (path === '/api/notes?scope=personal') return []
    return fallback(path, init)
  })
  show()
  const save = await screen.findByRole('link', { name: '查看原结果并恢复保存' })
  expect(save).toHaveAttribute('href', '/generate?mode=file&meeting=1&operation=A')
  expect(screen.getByRole('heading', { name: '真实会议主题 · 新版本' })).toBeVisible()
  expect(await screen.findByText('未完成 · 生成与事实复核')).toBeVisible()
  expect(screen.getByRole('link', { name: '查看失败处理记录' })).toHaveAttribute('href', '/generate?mode=file&meeting=1&operation=B')
  expect(screen.queryByText(/任务已接收，请查询原结果/)).toBeNull()
  expect(screen.queryByRole('heading', { name: /待生成纪要/ })).toBeNull()
  expect(api.json.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
  expect(api.json.mock.calls.every(([path]) => !path.includes('/workspace/'))).toBe(true)
  expect(snapshot()).toEqual(before)
})

it('refreshes the same original task and opens only its matching saved note', async () => {
  keep('A'); const before = snapshot(); let saved = false
  const fallback = api.json.getMockImplementation()!
  api.json.mockImplementation(async (path, init) => {
    if (path === '/api/task/A-child') return { task_id: 'A-child', status: 'success', result: { task_id: 'A-child', title: '结果主题', markdown: '# 结果主题' } }
    if (path === '/api/notes?scope=personal') return saved
      ? [{ id: 'saved-child-note', task_id: 'A-child', title: '实际保存主题' }, { id: 'parent-note', task_id: 'parent', title: '旧纪要' }]
      : [{ id: 'parent-note', task_id: 'parent', title: '旧纪要' }]
    return fallback(path, init)
  })
  show(); await screen.findByRole('link', { name: '查看原结果并恢复保存' })
  saved = true; fireEvent.click(screen.getByRole('button', { name: '刷新状态' }))
  expect(await screen.findByRole('link', { name: '查看已保存纪要' })).toHaveAttribute('href', '/note/saved-child-note')
  expect(screen.getByRole('heading', { name: '实际保存主题 · 新版本' })).toBeVisible()
  expect(api.json.mock.calls.filter(([path]) => path === '/api/task/A-child')).toHaveLength(2)
  expect(snapshot()).toEqual(before)
})

it.each(['transport', '404', 'reserved', 'foreign-op', 'foreign-child', 'incomplete-result', 'notes-unavailable'])(
  'keeps %s query-only and never promises a saveable result', async outcome => {
    keep('A', outcome === 'reserved' ? { submissionState: 'unknown', id: undefined } : {})
    const before = snapshot()
    api.json.mockImplementation(async path => {
      if (path === '/api/source-requests/A') {
        if (outcome === 'transport' || outcome === '404') throw new Error(outcome)
        return { operation_id: outcome === 'foreign-op' ? 'foreign' : 'A', task_id: 'A-child', state: outcome === 'reserved' ? 'reserved' : 'accepted' }
      }
      if (path === '/api/task/A-child') return { task_id: outcome === 'foreign-child' ? 'foreign' : 'A-child', status: 'success',
        result: outcome === 'incomplete-result' ? undefined : { task_id: 'A-child', title: '主题', markdown: '# 主题' } }
      if (path === '/api/notes?scope=personal') { if (outcome === 'notes-unavailable') throw new Error('offline'); return [] }
      throw new Error('Unexpected request')
    })
    show(); await waitFor(() => expect(screen.getByRole('button', { name: '刷新状态' })).toBeEnabled())
    expect(screen.queryByRole('link', { name: '查看原结果并恢复保存' })).toBeNull()
    expect(screen.queryByRole('link', { name: '查看已保存纪要' })).toBeNull()
    expect(api.json.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
    expect(snapshot()).toEqual(before)
  })

it('ignores a task response arriving after the owning account changes', async () => {
  keep('A'); const task = deferred<unknown>(); const fallback = api.json.getMockImplementation()!
  api.json.mockImplementation((path, init) => path === '/api/task/A-child' ? task.promise : fallback(path, init))
  show(); await waitFor(() => expect(api.json).toHaveBeenCalledWith('/api/task/A-child', expect.anything()))
  act(() => useAuthStore.setState({ user: { id: 'other' } as never }))
  await act(async () => task.resolve({ task_id: 'A-child', status: 'success', result: { task_id: 'A-child', title: '旧账号结果', markdown: '# 旧账号结果' } }))
  expect(screen.queryByText(/旧账号结果/)).toBeNull()
  expect(screen.queryByText('frozen-model')).toBeNull()
  expect(api.json.mock.calls.some(([path]) => path.startsWith('/api/notes'))).toBe(false)
  expect(localStorage.getItem(pointer)).toBe('A')
})

it('does not apply a late result after the operation receipt has been replaced', async () => {
  keep('A'); const task = deferred<unknown>(); const fallback = api.json.getMockImplementation()!
  api.json.mockImplementation((path, init) => path === '/api/task/A-child' ? task.promise : fallback(path, init))
  show(); await waitFor(() => expect(api.json).toHaveBeenCalledWith('/api/task/A-child', expect.anything()))
  keep('A', { id: 'changed-child' }); localStorage.setItem(pointer, 'newer-op'); const before = snapshot()
  await act(async () => task.resolve({ task_id: 'A-child', status: 'success', result: { task_id: 'A-child', title: '过期结果', markdown: '# 过期结果' } }))
  expect(screen.queryByText(/过期结果/)).toBeNull()
  expect(api.json.mock.calls.some(([path]) => path.startsWith('/api/notes'))).toBe(false)
  expect(snapshot()).toEqual(before)
})

it.each(['summary_result_unconfirmed', 'unknown_result', 'unknown_error', 'asr_incomplete_result'])(
  'keeps %s read-only even if the response includes partial result bytes and retryable=true', async errorCode => {
    keep('A'); const before = snapshot(); const fallback = api.json.getMockImplementation()!
    api.json.mockImplementation(async (path, init) => path === '/api/task/A-child'
      ? { task_id: 'A-child', status: 'failed', failed_stage: 'summarizing', error_code: errorCode, retryable: true,
        result: { task_id: 'A-child', title: '部分结果', markdown: '# 部分结果' } } : fallback(path, init))
    show()
    expect(await screen.findByText('结果待确认')).toBeVisible()
    expect(screen.getByRole('link', { name: '查看原任务与处理记录' })).toHaveAttribute('href', '/generate?mode=file&meeting=1&task=A-child')
    expect(screen.queryByText(/部分结果/)).toBeNull()
    expect(api.json.mock.calls.some(([path]) => path.startsWith('/api/notes'))).toBe(false)
    expect(snapshot()).toEqual(before)
  })

it.each(['local-child', 'result-child', 'task-op'])(
  'does not publish a status bound to a mismatching %s', async mismatch => {
    keep('A', mismatch === 'local-child' ? { id: 'different-child' } : {})
    const fallback = api.json.getMockImplementation()!
    api.json.mockImplementation(async (path, init) => path === '/api/task/A-child'
      ? { task_id: 'A-child', operation_id: mismatch === 'task-op' ? 'foreign' : 'A', status: 'success',
        result: { task_id: mismatch === 'result-child' ? 'foreign' : 'A-child', title: '错误绑定结果', markdown: '# 错误绑定结果' } } : fallback(path, init))
    show(); await waitFor(() => expect(screen.getByRole('button', { name: '刷新状态' })).toBeEnabled())
    expect(screen.queryByText(/错误绑定结果/)).toBeNull()
    expect(screen.queryByRole('link', { name: '查看原结果并恢复保存' })).toBeNull()
    expect(api.json.mock.calls.some(([path]) => path.startsWith('/api/notes'))).toBe(false)
  })

it('uses the frozen team destination for saved results', async () => {
  keep('A', { workspace: { scope: 'team', teamId: 'original-team' } })
  const fallback = api.json.getMockImplementation()!
  api.json.mockImplementation(async (path, init) => {
    if (path === '/api/task/A-child') return { task_id: 'A-child', status: 'success', result: { title: '团队主题', markdown: '# 团队主题' } }
    if (path === '/api/notes?scope=team&team_id=original-team') return [{ id: 'team-note', task_id: 'A-child', title: '团队已存主题' }]
    return fallback(path, init)
  })
  show()
  expect(await screen.findByRole('link', { name: '查看已保存纪要' })).toHaveAttribute('href', '/note/team-note')
  expect(api.json.mock.calls.some(([path]) => path === '/api/notes?scope=personal')).toBe(false)
})

it('shows the latest original processing stage without synthesizing a percentage', async () => {
  keep('A'); const fallback = api.json.getMockImplementation()!
  api.json.mockImplementation(async (path, init) => path === '/api/task/A-child'
    ? { task_id: 'A-child', status: 'summarizing', stage: 'analyzing_video' } : fallback(path, init))
  show()
  expect(await screen.findByText('整理共享画面与发言资料')).toBeVisible()
  expect(screen.queryByText(/\d+%/)).toBeNull()
})

it('aborts task readback when leaving the generation tab and ignores its late result', async () => {
  keep('A'); const task = deferred<unknown>(); const fallback = api.json.getMockImplementation()!
  api.json.mockImplementation((path, init) => path === '/api/task/A-child' ? task.promise : fallback(path, init))
  show(); await waitFor(() => expect(api.json).toHaveBeenCalledWith('/api/task/A-child', expect.anything()))
  const signal = api.json.mock.calls.find(([path]) => path === '/api/task/A-child')![1].signal
  fireEvent.mouseDown(screen.getByRole('tab', { name: '飞书' }), { button: 0, ctrlKey: false })
  await waitFor(() => expect(signal.aborted).toBe(true))
  await act(async () => task.resolve({ task_id: 'A-child', status: 'success', result: { title: '过期结果', markdown: '# 过期结果' } }))
  expect(api.json.mock.calls.some(([path]) => path.startsWith('/api/notes'))).toBe(false)
  expect(screen.queryByText(/过期结果/)).toBeNull()
})

it('does not label a completed recording as still processing or awaiting generation', async () => {
  vi.mocked(listPendingMeetings).mockResolvedValueOnce([{ id: 'recording', taskId: 'original-task', noteId: 'saved-note',
    processingStatus: 'completed', options: { title: '2026-10-19 18:02｜待生成纪要' } } as never])
  show()
  expect(await screen.findByRole('heading', { name: '2026-10-19 18:02 录制' })).toBeVisible()
  expect(screen.getByText('原录音已保留 · 纪要已保存')).toBeVisible()
  expect(screen.queryByText(/正在处理|待生成纪要/)).toBeNull()
})
