import { beforeEach, expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ write: vi.fn(), put: vi.fn() }))
vi.mock('@/lib/workspaceCache', () => ({ readWorkspaceCache: vi.fn(), writeWorkspaceCache: api.write }))
vi.mock('@/lib/workspace', async original => ({ ...await original<typeof import('@/lib/workspace')>(), putWorkspaceNote: api.put }))
vi.mock('./authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: 'owner-a' } }) } }))
import { useWorkspaceStore } from './workspaceStore'
beforeEach(() => { vi.clearAllMocks(); useWorkspaceStore.getState().reset(); useWorkspaceStore.setState({ owner: 'owner-a', ready: true }) })
it('never submits a new note if durable request storage fails', async () => {
  api.write.mockRejectedValueOnce(new Error('Disk unavailable'))
  await expect(useWorkspaceStore.getState().save('text-test', {
    base_revision: 0, operation_id: 'operation-test', title: '草稿', content: '内容', source_type: 'text', source_device: 'desktop',
  })).rejects.toThrow('保存未完成')
  expect(api.put).not.toHaveBeenCalled()
  expect(useWorkspaceStore.getState().pending).toEqual([])
  expect(useWorkspaceStore.getState().busy).toBe(false)
})

it('never promotes a merge baseline beyond the revision the user compared', async () => {
  const pending = { key: 'review', body: { operation_id: 'review-op', content: '本机稿', title: '验收' }, conflict: { revision: 4, content: '新远端稿' } } as never;
  useWorkspaceStore.setState({ pending: [pending] });
  await expect(useWorkspaceStore.getState().resolve('review-op', '人工合并', '验收', 3, 'owner-a')).rejects.toThrow('重新比较');
  expect(useWorkspaceStore.getState().pending[0]).toBe(pending);
  expect(api.put).not.toHaveBeenCalled(); expect(api.write).not.toHaveBeenCalled();
})

it('blocks a merge retained by the previous account before writing or submitting', async () => {
  useWorkspaceStore.setState({ pending: [{ key: 'review', body: { operation_id: 'review-op' }, conflict: { revision: 3 } } as never] });
  await expect(useWorkspaceStore.getState().resolve('review-op', '旧账号稿', '验收', 3, 'previous-owner')).rejects.toThrow('账号已变化');
  expect(api.put).not.toHaveBeenCalled(); expect(api.write).not.toHaveBeenCalled();
})
