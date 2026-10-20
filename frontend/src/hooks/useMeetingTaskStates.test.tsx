import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useMeetingTaskStates } from './useMeetingTaskStates'
import type { LibraryNote } from './useLibraryNotes'
import { useAuthStore } from '@/stores/authStore'
import { useAppModeStore } from '@/stores/appModeStore'
import { apiJson } from '@/lib/api'
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }))
const mock = vi.mocked(apiJson)
const note = (taskId: string) => ({ id: taskId, taskId, status: 'done', updatedAt: 'one' }) as LibraryNote
beforeEach(() => { vi.resetAllMocks(); useAuthStore.setState({ user: { id: 'owner' } as never }); useAppModeStore.setState({ config: null }) })
afterEach(cleanup)
it('deduplicates exact task reads and uses actual failed status despite saved note done', async () => {
  mock.mockResolvedValue({ task_id: 'task', status: 'failed', failed_stage: 'transcribing', retryable: false })
  const { result } = renderHook(() => useMeetingTaskStates([note('task'), { ...note('task'), id: 'second' }], 'route'))
  expect(result.current.task).toBe('checking')
  await waitFor(() => expect(result.current.task).toBe('failed'))
  expect(mock).toHaveBeenCalledTimes(1)
  expect(mock.mock.calls[0][0]).toBe('/api/task/task')
  expect(mock.mock.calls.every(([, init]) => !init?.method)).toBe(true)
})
it('requires a complete task result and treats failed reads, not_found and wrong identities as unverified', async () => {
  mock.mockImplementation(async path => {
    if (path.endsWith('/offline')) throw new Error('offline')
    if (path.endsWith('/wrong')) return { task_id: 'other', status: 'success', result: { title: 'T', markdown: 'M' } }
    if (path.endsWith('/empty')) return { status: 'success' }
    if (path.endsWith('/missing')) return { status: 'not_found' }
    return { status: 'success', result: { title: 'T', markdown: 'M' } }
  })
  const { result } = renderHook(() => useMeetingTaskStates(['offline', 'wrong', 'empty', 'missing', 'ready'].map(note), 'route'))
  await waitFor(() => expect(result.current).toEqual({ offline: 'unverified', wrong: 'unverified', empty: 'unverified', missing: 'unverified', ready: 'complete' }))
})
it('ignores delayed task reads after owner ABA and route changes', async () => {
  const reads: ((value: unknown) => void)[] = []
  mock.mockImplementation(() => new Promise(resolve => reads.push(resolve)))
  const { result, rerender } = renderHook(({ route }) => useMeetingTaskStates([note('task')], route), { initialProps: { route: 'first' } })
  act(() => useAuthStore.setState({ user: { id: 'other' } as never }))
  act(() => useAuthStore.setState({ user: { id: 'owner' } as never }))
  rerender({ route: 'second' })
  await act(async () => reads[0]({ status: 'failed' }))
  expect(result.current.task).toBe('checking')
  await act(async () => reads.at(-1)!({ status: 'transcribing' }))
  expect(result.current.task).toBe('processing')
})
