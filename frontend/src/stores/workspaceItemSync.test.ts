import { beforeEach, expect, it, vi } from 'vitest';
const f = vi.hoisted(() => ({ cache: vi.fn(), read: vi.fn(), api: vi.fn(), remote: vi.fn(), owner: 'owner-a' }));
vi.mock('@/lib/workspaceCache', () => ({ readWorkspaceCache: f.read, writeWorkspaceCache: f.cache }));
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: f.api }));
vi.mock('@/lib/workspace', async original => ({ ...await original<typeof import('@/lib/workspace')>(),
  putWorkspaceNote: f.remote, getWorkspaceNote: f.remote, workspaceStatus: f.remote, listWorkspacePage: f.remote }));
vi.mock('./authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: f.owner } }) } }));
import { useWorkspaceStore } from './workspaceStore';
import { useNoteLibraryStore } from './noteLibraryStore';
import { webcrypto } from 'node:crypto';
const fixtureReset = { owner: 'synthetic-cleanup-owner', cloudKeys: ['synthetic-cleared-key'], id: 'synthetic-cleanup-operation' };
import type { WorkspaceNote, WorkspaceWrite } from '@/lib/workspace';
const write = (operation = 'one', content = '正文', base = 0): WorkspaceWrite => ({
  operation_id: operation, base_revision: base, title: '标题', content, source_type: 'text', source_device: 'desktop' });
const note = (key = 'saved'): WorkspaceNote => ({ key, title: '原标题', content: '云基线', source_type: 'file', source_device: 'desktop',
  revision: 4, acknowledged_revision: 4, created_at: '2026-10-12T01:00:00Z', updated_at: '2026-10-12T02:00:00Z',
  deleted: false, archived: false, versions: [{ id: 'real-get-version', title: '历史', content: '旧正文', created_at: '2026-10-12',
    evidence_revision: 4, model: '', parent_id: '' }], version_count: 8, next_versions_offset: 50,
  transcript: null, metadata: { original_file_id: 'file-retained', source_url: 'https://example.com/source' } });
const oldCache = (n = note()) => ({ items: [n], details: { [n.key]: n }, mappings: {}, pending: [], itemPolicies: {}, lastSync: '', deviceId: 'device' });
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; };
beforeEach(() => {
  vi.resetAllMocks(); vi.stubGlobal('crypto', webcrypto); f.owner = 'owner-a'; useNoteLibraryStore.getState().reset(); useWorkspaceStore.getState().reset();
  f.cache.mockResolvedValue(undefined); f.read.mockResolvedValue(undefined);
  f.remote.mockRejectedValue(new Error('Remote workspace forbidden'));
  f.api.mockImplementation(async (path: string) => { throw new Error(`Unexpected API ${path}`); });
  useWorkspaceStore.setState({ owner: f.owner, ready: true });
});
const initialize = async (owner: string) => { useWorkspaceStore.setState({ ready: false }); await useWorkspaceStore.getState().initialize(owner); };
const noRemote = () => { expect(f.remote).not.toHaveBeenCalled(); expect(f.api.mock.calls.some(c => c[0].startsWith('/api/workspace'))).toBe(false); };

it('supports durable create/edit/read/export body, delete and restore with no HTTP or pending', async () => {
  const store = useWorkspaceStore.getState();
  const first = await store.save('stable', write());
  const second = await store.save('stable', write('two', '修改正文', first!.revision));
  expect(second).toMatchObject({ key: 'stable', content: '修改正文', revision: 2 });
  expect(second!.versions.map(v => v.content)).toEqual(expect.arrayContaining(['正文', '修改正文']));
  const deleted = await store.changeDeleted('stable', true);
  expect(deleted!.deleted).toBe(true);
  const restored = await store.changeDeleted('stable', false);
  expect(restored!.deleted).toBe(false);
  expect((await store.loadDetail('stable', true)).content).toBe('修改正文');
  expect(restored!.versions).toEqual(second!.versions);
  expect(useWorkspaceStore.getState().pending).toEqual([]);
  await store.sync(); await store.sync(); expect(f.api).not.toHaveBeenCalled(); noRemote();
});
it('migrates unknown body, remaining history, conflict and baseline durably without replay', async () => {
  const n = note(); const conflict = { ...n, revision: 5, content: '另一端稿' };
  const op = { key: n.key, localId: 'original', body: write('unknown', '最新未保存正文', 4), locallyQueued: false,
    baseline: n, conflict, remainingVersions: [[{ id: 'remaining', title: '后批', content: '后批历史', created_at: n.created_at }]] };
  f.read.mockResolvedValue({ ...oldCache(n), pending: [op] });
  await initialize(f.owner);
  const state = useWorkspaceStore.getState();
  expect(state.pending).toEqual([]); expect(state.retainedSyncOperations).toEqual([op]);
  expect(state.cloudBaselines![n.key].map(v => v.content)).toEqual(expect.arrayContaining(['云基线', '另一端稿']));
  const recovered = await state.loadDetail(n.key, true);
  expect(recovered.content).toBe('最新未保存正文');
  expect(recovered.versions.map(v => v.content)).toEqual(expect.arrayContaining(['旧正文', '云基线', '另一端稿', '后批历史', '最新未保存正文']));
  await state.save(n.key, { ...write('next', '继续编辑', recovered.revision), metadata: recovered.metadata });
  await state.changeDeleted(n.key, true); await state.changeDeleted(n.key, false); noRemote();
  expect(f.cache.mock.calls[0][1].retainedSyncOperations).toEqual([op]);
});
it('does not revive a cloud tombstone because an old unknown restore exists', async () => {
  const n = note(); f.read.mockResolvedValue({ ...oldCache(n), items: [{ ...n, deleted: true }],
    pending: [{ key: n.key, action: 'restore', body: write('restore', '保留草稿', 4) }] });
  await initialize(f.owner);
  expect(useWorkspaceStore.getState().items[0].deleted).toBe(true);
  expect((await useWorkspaceStore.getState().loadDetail(n.key)).content).toBe('保留草稿');
  await expect(useWorkspaceStore.getState().save(n.key, write('new', '不能越过删除', 4))).rejects.toThrow('先恢复');
  noRemote();
});
it('purges confirmed reset IDs from active body/history/trash, including queued drafts', async () => {
  f.owner = fixtureReset.owner;
  const key = fixtureReset.cloudKeys[0]; const old = note(key); const fresh = note('new-user-note');
  f.read.mockResolvedValue({ ...oldCache(old), clearedContentKeys: [key], items: [old, fresh], details: { [key]: old, [fresh.key]: fresh },
    pending: [{ key, baseline: old, body: write('newest', '清理对象保留的新草稿', 4) }] });
  await initialize(f.owner);
  const state = useWorkspaceStore.getState();
  expect(state.items.some(item => item.key === key)).toBe(false);
  expect(state.details[key]).toBeUndefined(); expect(state.cloudBaselines![key]).toBeUndefined();
  expect(state.retainedSyncOperations!.some(op => op.key === key)).toBe(false);
  expect(state.details[`recovered-cleared-${key}`]).toBeUndefined();
  expect(state.details[fresh.key].deleted).toBe(false);
  await expect(state.loadDetail(key)).rejects.toThrow('历史内容已清理');
  await expect(state.changeDeleted(key, false)).rejects.toThrow('历史内容已清理');
  await expect(state.save(key, write('reuse', '不得复活', 0))).rejects.toThrow('历史内容已清理');
  expect(f.api).not.toHaveBeenCalled(); noRemote();
});
it('purges an already-migrated cache and clears old history counts without recovering backup-identical text', async () => {
  f.owner = fixtureReset.owner; const key = fixtureReset.cloudKeys[0]; const old = note(key);
  f.read.mockResolvedValue({ ...oldCache(old), localOnlyVersion: 1, appliedContentResets: [fixtureReset.id],
    clearedContentKeys: [key], cloudBaselines: { [key]: [old] },
    retainedSyncOperations: [{ key, body: { ...write('old', old.content, 4), title: old.title } }] });
  await initialize(f.owner);
  expect(useWorkspaceStore.getState().items).toEqual([]); expect(useWorkspaceStore.getState().details).toEqual({});
  expect(useWorkspaceStore.getState().mappings).toEqual({}); expect(useWorkspaceStore.getState().cloudBaselines).toEqual({});
  const persisted = f.cache.mock.calls.at(-1)![1];
  useWorkspaceStore.getState().reset(); f.read.mockResolvedValue(persisted);
  await useWorkspaceStore.getState().initialize(f.owner);
  expect(useWorkspaceStore.getState().items).toEqual([]); expect(useWorkspaceStore.getState().contentResetCleanupVersion).toBe(2);
  noRemote();
});
it('does not infer a deletion without this account ledger', async () => {
  const n = note(fixtureReset.cloudKeys[0]); f.read.mockResolvedValue(oldCache(n));
  await initialize('owner-a');
  expect(useWorkspaceStore.getState().details[n.key].deleted).toBe(false); noRemote();
});
it('retains different bodies with colliding historical IDs instead of discarding a version', async () => {
  const n = note(); f.read.mockResolvedValue({ ...oldCache(n), pending: [{ key: n.key, body: { ...write('collision', '稿', 4),
    versions: [{ ...n.versions[0], content: '同ID另一个正文' }] } }] });
  await initialize(f.owner);
  expect(useWorkspaceStore.getState().details[n.key].versions.map(v => v.content)).toEqual(expect.arrayContaining(['旧正文', '同ID另一个正文'])); noRemote();
});
it('rolls back save and tombstone on persistence failure without changing originals', async () => {
  const n = note(); useWorkspaceStore.setState({ details: { [n.key]: n }, items: [n] });
  f.cache.mockRejectedValueOnce(new Error('Disk unavailable'));
  await expect(useWorkspaceStore.getState().save(n.key, write('failed', '不能丢原稿', 4))).rejects.toThrow('Disk unavailable');
  expect(useWorkspaceStore.getState().details[n.key]).toBe(n);
  f.cache.mockRejectedValueOnce(new Error('Disk unavailable'));
  await expect(useWorkspaceStore.getState().changeDeleted(n.key, true)).rejects.toThrow('Disk unavailable');
  expect(useWorkspaceStore.getState().details[n.key]).toBe(n);
  expect(n.metadata.original_file_id).toBe('file-retained'); expect(f.api).not.toHaveBeenCalled(); noRemote();
});
it('leaves old persistent pending intact if migration cannot commit', async () => {
  const cached = { ...oldCache(), pending: [{ key: 'saved', body: write('old', '待保存稿', 4) }] };
  f.read.mockResolvedValue(cached); f.cache.mockRejectedValueOnce(new Error('No disk'));
  await initialize(f.owner);
  expect(useWorkspaceStore.getState().ready).toBe(false); expect(cached.pending[0].body.content).toBe('待保存稿'); noRemote();
});
it('does not publish a delayed account-A cache in account B', async () => {
  const wait = deferred<ReturnType<typeof oldCache>>(); f.read.mockReturnValueOnce(wait.promise);
  useWorkspaceStore.setState({ ready: false }); const loading = useWorkspaceStore.getState().initialize('owner-a');
  f.owner = 'owner-b'; await useWorkspaceStore.getState().initialize('owner-b'); wait.resolve(oldCache()); await loading;
  expect(useWorkspaceStore.getState().owner).toBe('owner-b'); expect(useWorkspaceStore.getState().items).toEqual([]); noRemote();
});
it('does not publish a delayed save acknowledgement after reset', async () => {
  const wait = deferred<void>(); f.cache.mockReturnValueOnce(wait.promise);
  const saving = useWorkspaceStore.getState().save('old-account', write());
  f.owner = 'owner-b'; useWorkspaceStore.getState().reset(); useWorkspaceStore.setState({ owner: 'owner-b', ready: true });
  wait.resolve(); await expect(saving).rejects.toThrow('账号已变化');
  expect(useWorkspaceStore.getState().details).toEqual({}); noRemote();
});
it('reads a retained desktop source and all existing desktop versions without workspace requests', async () => {
  const source = { id: 'original', title: '旧笔记', content: '旧正文', scope: 'personal' as const, status: 'done',
    createdAt: '2026-10-11', updatedAt: '2026-10-12', taskId: 'task-real', sourceType: 'file' };
  useNoteLibraryStore.setState({ notes: [source] }); f.api.mockResolvedValue([{ id: 'history-real', title: '历史', content: '历史正文', created_at: '2026-10-11' }]);
  const n = await useWorkspaceStore.getState().loadDetail('desktop-original', true);
  expect(n.metadata.task_id).toBe('task-real'); expect(n.versions.map(v => v.content)).toContain('历史正文');
  expect(f.api.mock.calls.map(c => c[0])).toEqual(['/api/notes/original/versions']);
  await useWorkspaceStore.getState().changeDeleted('original', true);
  await useWorkspaceStore.getState().changeDeleted('original', false); noRemote();
});
it('does not substitute unrelated content for an uncached cloud key', async () => {
  const load = vi.spyOn(useNoteLibraryStore.getState(), 'loadNoteById').mockResolvedValueOnce(null);
  await expect(useWorkspaceStore.getState().loadDetail('uncached-cloud-key', true)).rejects.toThrow('未保存在当前设备');
  expect(load).toHaveBeenCalledWith('uncached-cloud-key'); expect(f.api).not.toHaveBeenCalled(); noRemote();
});
it('rejects stale edit baselines without blocking future fresh edits', async () => {
  const first = await useWorkspaceStore.getState().save('stable', write());
  await expect(useWorkspaceStore.getState().save('stable', write('stale', '过期', 0))).rejects.toThrow('重新读取');
  const next = await useWorkspaceStore.getState().save('stable', write('fresh', '正确', first!.revision));
  expect(next!.content).toBe('正确'); noRemote();
});
it('never re-enables network synchronization through old controls', async () => {
  await expect(useWorkspaceStore.getState().setItemSync('any', true)).rejects.toThrow('已移除');
  expect(useWorkspaceStore.getState().itemSyncMode('any')).toBe('local');
  await useWorkspaceStore.getState().setItemSync('any', false); noRemote();
});

it('retries a failed save and survives restart with the same ID and complete retained history', async () => {
  const first = await useWorkspaceStore.getState().save('retry-stable', write());
  f.cache.mockRejectedValueOnce(new Error('Disk temporarily unavailable'));
  await expect(useWorkspaceStore.getState().save(first!.key, write('retry-edit', '重试修改', first!.revision))).rejects.toThrow('保存未完成');
  expect(useWorkspaceStore.getState().details[first!.key].content).toBe('正文');
  const second = await useWorkspaceStore.getState().save(first!.key, write('retry-edit', '重试修改', first!.revision));
  const persisted = f.cache.mock.calls.at(-1)![1];
  useWorkspaceStore.getState().reset(); f.read.mockResolvedValue(persisted);
  await useWorkspaceStore.getState().initialize(f.owner);
  const reopened = await useWorkspaceStore.getState().loadDetail(first!.key, true);
  expect(reopened).toEqual(second); expect(reopened.versions.map(v => v.content)).toContain('正文');
  await useWorkspaceStore.getState().changeDeleted(first!.key, true);
  await useWorkspaceStore.getState().changeDeleted(first!.key, false);
  expect(useWorkspaceStore.getState().details[first!.key].content).toBe('重试修改'); noRemote();
});

it('keeps old and mapped deletion aliases stable across repeated persistent reloads', async () => {
  const key = 'opaque-cleared'; const old = note(key);
  const cached = { ...oldCache(old), clearedContentKeys: ['recovered-cleared-recovered-cleared-local-source'],
    mappings: { 'local-source': { key, revision: 4, fingerprint: '' } },
    pending: [{ key, localId: 'local-source', action: 'restore', body: write('old-restore', '不得复活', 4) }] };
  f.read.mockResolvedValue(cached); await initialize(f.owner);
  const first = f.cache.mock.calls.at(-1)![1];
  expect(first.details).toEqual({}); expect(first.pending).toEqual([]);
  expect(first.retainedSyncOperations).toEqual([]); expect(first.mappings).toEqual({});
  expect(first.clearedContentKeys).toEqual(expect.arrayContaining([key, 'local-source', 'desktop-local-source',
    'recovered-cleared-recovered-cleared-local-source']));
  for (let i = 0; i < 2; i++) {
    useWorkspaceStore.getState().reset(); f.read.mockResolvedValue(f.cache.mock.calls.at(-1)![1]);
    await useWorkspaceStore.getState().initialize(f.owner);
    expect(useWorkspaceStore.getState().clearedContentKeys).toEqual(first.clearedContentKeys);
  }
  for (const alias of [key, 'local-source', 'desktop-local-source']) {
    await expect(useWorkspaceStore.getState().loadDetail(alias)).rejects.toThrow('历史内容已清理');
    await expect(useWorkspaceStore.getState().changeDeleted(alias, false)).rejects.toThrow('历史内容已清理');
    await expect(useWorkspaceStore.getState().save(alias, write('reuse'))).rejects.toThrow('历史内容已清理');
  }
  expect(cached.details[key]).toBe(old); expect(f.api).not.toHaveBeenCalled(); noRemote();
});
it('fails closed on a historical cleanup stamp without a durable deletion ledger', async () => {
  const cached = { ...oldCache(), appliedContentResets: ['synthetic-old-cleanup'] };
  f.read.mockResolvedValue(cached); await initialize(f.owner);
  expect(useWorkspaceStore.getState().ready).toBe(false);
  expect(useWorkspaceStore.getState().error).toBe('无法保存资料：历史内容整理尚未完成，请在原设备重试；已有资料已保留');
  expect(f.cache).not.toHaveBeenCalled(); expect(cached.details.saved).toBeDefined(); noRemote();
});
it('retains the permanent ledger when migration storage fails and never exposes it as ready', async () => {
  const n = note('permanently-cleared');
  const cached = { ...oldCache(n), clearedContentKeys: [n.key] };
  f.read.mockResolvedValue(cached); f.cache.mockRejectedValueOnce(new Error('No disk'));
  await initialize(f.owner);
  expect(useWorkspaceStore.getState().ready).toBe(false);
  expect(cached.clearedContentKeys).toEqual([n.key]); expect(cached.details[n.key]).toBe(n); noRemote();
});
it('blocks a raw local source ID through its desktop alias after mappings were removed', async () => {
  f.read.mockResolvedValue({ ...oldCache(note('local-only-id')), mappings: {}, clearedContentKeys: ['local-only-id'] });
  await initialize(f.owner);
  await expect(useWorkspaceStore.getState().loadDetail('desktop-local-only-id')).rejects.toThrow('历史内容已清理');
  await expect(useWorkspaceStore.getState().save('desktop-local-only-id', write())).rejects.toThrow('历史内容已清理');
  const persisted = f.cache.mock.calls.at(-1)![1]; useWorkspaceStore.getState().reset(); f.read.mockResolvedValue(persisted);
  await useWorkspaceStore.getState().initialize(f.owner);
  expect(useWorkspaceStore.getState().clearedContentKeys).toEqual(persisted.clearedContentKeys); noRemote();
});
it('does not carry an account A ledger into account B with the same content key', async () => {
  const n = note('same-account-local-key');
  f.read.mockImplementation(async owner => owner === 'owner-a'
    ? { ...oldCache(n), clearedContentKeys: [n.key] } : oldCache(n));
  await initialize('owner-a'); expect(useWorkspaceStore.getState().items).toEqual([]);
  f.owner = 'owner-b'; await useWorkspaceStore.getState().initialize('owner-b');
  expect(useWorkspaceStore.getState().details[n.key].deleted).toBe(false);
  expect(useWorkspaceStore.getState().clearedContentKeys).toEqual([]); noRemote();
});
it('clears optional legacy cleanup stamps on reset and when initializing a marker-free account', async () => {
  const n = note('cleared-for-a');
  f.read.mockResolvedValue({ ...oldCache(n), appliedContentResets: ['synthetic-applied'], clearedContentKeys: [n.key] });
  await initialize('owner-a');
  expect(useWorkspaceStore.getState().appliedContentResets).toEqual(['synthetic-applied']);
  useWorkspaceStore.getState().reset();
  expect(useWorkspaceStore.getState().appliedContentResets).toEqual([]);
  expect(useWorkspaceStore.getState().clearedContentKeys).toEqual([]);
  expect(useWorkspaceStore.getState().contentResetCleanupVersion).toBeUndefined();
  f.owner = 'owner-b'; f.read.mockResolvedValue(undefined);
  await useWorkspaceStore.getState().initialize('owner-b');
  expect(useWorkspaceStore.getState().ready).toBe(true);
  await expect(useWorkspaceStore.getState().save('b-new-content', write())).resolves.toMatchObject({ content: '正文' });
  expect(f.cache.mock.calls.at(-1)![1].appliedContentResets).toEqual([]); noRemote();
});
