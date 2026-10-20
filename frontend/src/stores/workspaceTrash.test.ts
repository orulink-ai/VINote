import { beforeEach, expect, it, vi } from 'vitest';
const f = vi.hoisted(() => ({ cache: vi.fn(), read: vi.fn(), api: vi.fn(), owner: 'alice' }));
vi.mock('@/lib/workspaceCache', () => ({ readWorkspaceCache: f.read, writeWorkspaceCache: f.cache }));
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: f.api, apiFetch: f.api }));
vi.mock('./authStore', () => ({ useAuthStore: { getState: () => ({ user: { id: f.owner } }) } }));
import { useWorkspaceStore } from './workspaceStore';
import { useNoteLibraryStore } from './noteLibraryStore';
import type { WorkspaceNote } from '@/lib/workspace';

const note = (key = 'desktop-saved', deleted = true): WorkspaceNote => ({ key, deleted,
  title: 'Synthetic body', content: 'Body retained until confirmed', revision: 4,
  created_at: '2026-10-20', updated_at: '2026-10-20', archived: false,
  source_type: 'meeting_recording', source_device: 'desktop', transcript: null,
  metadata: { original_file_id: 'never-delete-this-file', task_id: 'never-delete-this-task' },
  versions: [{ id: 'history', title: 'Old', content: 'Old body', created_at: '2026-10-19' }],
  version_count: 1, next_versions_offset: null });
const deferred = () => { let resolve!: (response: Response) => void; const promise = new Promise<Response>(r => { resolve = r; }); return { promise, resolve }; };

beforeEach(() => {
  vi.resetAllMocks(); f.owner = 'alice';
  useWorkspaceStore.getState().reset(); useNoteLibraryStore.getState().reset();
  const target = note(), other = note('unrelated', false);
  useWorkspaceStore.setState({ owner: f.owner, ready: true, localOnlyVersion: 1, contentResetCleanupVersion: 2,
    items: [target, other], details: { [target.key]: target, [other.key]: other },
    mappings: { saved: { key: target.key, revision: 4, fingerprint: 'old' } },
    cloudBaselines: { [target.key]: [target] },
    retainedSyncOperations: [{ key: target.key, localId: 'saved', body: { operation_id: 'old-unknown' } } as never] });
  f.cache.mockResolvedValue(undefined); f.api.mockImplementation(async () => new Response(null, { status: 204 }));
});

it('permanently removes the exact deleted body/history and backing DB note, never originals or old unknown POSTs', async () => {
  await useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  const state = useWorkspaceStore.getState();
  expect(f.api.mock.calls).toEqual([['/api/notes/saved?personal_only=true', { method: 'DELETE' }]]);
  expect(state.items.map(item => item.key)).toEqual(['unrelated']);
  expect(state.details['desktop-saved']).toBeUndefined();
  expect(state.cloudBaselines!['desktop-saved']).toBeUndefined();
  expect(state.retainedSyncOperations).toEqual([]);
  expect(state.mappings.saved).toBeUndefined();
  expect(state.clearedContentKeys).toEqual(expect.arrayContaining(['desktop-saved', 'saved']));
  expect(f.cache).toHaveBeenCalledWith('alice', expect.objectContaining({ items: state.items }));
  expect(state.busy).toBe(false);
});

it('supports cache-only trashed content with no backend or cloud request', async () => {
  const local = note('text-only');
  useWorkspaceStore.setState({ items: [local], details: { [local.key]: local }, mappings: {},
    retainedSyncOperations: [], cloudBaselines: {} });
  await useWorkspaceStore.getState().purgeDeleted(local.key, 'alice', local.revision);
  expect(f.api).not.toHaveBeenCalled();
  expect(useWorkspaceStore.getState().items).toEqual([]);
});

it('removes matching old pending bodies without dispatching them and preserves unrelated receipts', async () => {
  const own = { key: 'desktop-saved', localId: 'saved', body: { content: 'discard this old unknown body' } } as never;
  const other = { key: 'unrelated', body: { content: 'keep this unrelated receipt' } } as never;
  useWorkspaceStore.setState({ pending: [own, other], retainedSyncOperations: [own, other] });
  await useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  expect(useWorkspaceStore.getState().pending).toEqual([other]);
  expect(useWorkspaceStore.getState().retainedSyncOperations).toEqual([other]);
  expect(JSON.stringify(f.cache.mock.calls.at(-1)![1])).not.toContain('discard this old unknown body');
  expect(f.api).toHaveBeenCalledTimes(1);
});

it.each(['pending', 'retainedSyncOperations'] as const)('deletes explicit backing localId recorded only in %s, never replays its unknown POST', async field => {
  const target = note('workspace-key');
  useWorkspaceStore.setState({ items: [target], details: { [target.key]: target }, mappings: {},
    pending: [], retainedSyncOperations: [], [field]: [{ key: target.key, localId: 'saved-db-id', body: { operation_id: 'unknown' } }] as never });
  await useWorkspaceStore.getState().purgeDeleted(target.key, 'alice', 4);
  expect(f.api.mock.calls).toEqual([['/api/notes/saved-db-id?personal_only=true', { method: 'DELETE' }]]);
  expect(useWorkspaceStore.getState().items).toEqual([]);
});

it('rejects an alias collision with active content before touching its backing DB note', async () => {
  const active = note('saved', false);
  useWorkspaceStore.setState(s => ({ items: [...s.items, active], details: { ...s.details, [active.key]: active } }));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('关联内容仍在使用');
  expect(f.api).not.toHaveBeenCalled(); expect(f.cache).not.toHaveBeenCalled();
});

it('removes only personal backing note projections after durable cleanup', async () => {
  useNoteLibraryStore.setState({ notes: [{ id: 'saved', scope: 'personal' }, { id: 'saved', scope: 'team' },
    { id: 'other-note', scope: 'personal' }] as never });
  await useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  expect(useNoteLibraryStore.getState().notes).toEqual([{ id: 'saved', scope: 'team' }, { id: 'other-note', scope: 'personal' }]);
});

it.each(['owner', 'active', 'revision', 'unknown'] as const)('blocks stale %s confirmation before DELETE', async change => {
  if (change === 'active') useWorkspaceStore.setState({ items: [note(undefined, false)], details: { 'desktop-saved': note(undefined, false) } });
  await expect(useWorkspaceStore.getState().purgeDeleted(change === 'unknown' ? 'unknown' : 'desktop-saved',
    change === 'owner' ? 'bob' : 'alice', change === 'revision' ? 3 : 4)).rejects.toThrow();
  expect(f.api).not.toHaveBeenCalled(); expect(f.cache).not.toHaveBeenCalled();
});

it('keeps the trashed body and versions on failure, and retries only the same explicit DELETE', async () => {
  f.api.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Temporary disk failure' }), { status: 507 }));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('Temporary disk failure');
  expect(useWorkspaceStore.getState().details['desktop-saved'].versions[0].content).toBe('Old body');
  expect(f.api).toHaveBeenCalledTimes(1);
  await useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  expect(f.api.mock.calls[0]).toEqual(f.api.mock.calls[1]);
  expect(useWorkspaceStore.getState().items).toHaveLength(1);
});

it('keeps a recoverable cache copy if cache writing fails after confirmed DELETE, then manually finishes without a second DELETE', async () => {
  f.cache.mockRejectedValueOnce(new Error('IndexedDB unavailable'));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('IndexedDB unavailable');
  expect(useWorkspaceStore.getState().details['desktop-saved'].content).toBe('Body retained until confirmed');
  await useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  expect(useWorkspaceStore.getState().details['desktop-saved']).toBeUndefined();
  expect(f.api).toHaveBeenCalledTimes(1);
});

it('never treats a concealed owner/scope-change 404 as a successful deletion', async () => {
  f.api.mockResolvedValueOnce(new Response(null, { status: 404 }));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('无法确认删除结果');
  expect(useWorkspaceStore.getState().details['desktop-saved'].versions[0].content).toBe('Old body');
  expect(useWorkspaceStore.getState().clearedContentKeys).toEqual([]);
  expect(f.cache).not.toHaveBeenCalled();
});

it.each([200, 202, 205])('HTTP %s never confirms deletion or grants a cache-cleanup proof', async status => {
  f.api.mockResolvedValueOnce(new Response(null, { status }));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('未收到明确的删除确认');
  f.api.mockResolvedValueOnce(new Response(null, { status: 404 }));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('无法确认删除结果');
  expect(f.api).toHaveBeenCalledTimes(2);
  expect(f.cache).not.toHaveBeenCalled();
  expect(useWorkspaceStore.getState().details['desktop-saved']).toBeDefined();
});

it('records each actual 204, preserves pending bodies on a later timeout, and manually retries only remaining IDs', async () => {
  useWorkspaceStore.setState(s => ({ mappings: { ...s.mappings, second: { key: 'desktop-saved', revision: 4, fingerprint: '' } } }));
  f.api.mockResolvedValueOnce(new Response(null, { status: 204 })).mockRejectedValueOnce(new Error('Synthetic timeout'));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('Synthetic timeout');
  expect(f.api.mock.calls.map(call => call[0])).toEqual(['/api/notes/saved?personal_only=true', '/api/notes/second?personal_only=true']);
  expect(useWorkspaceStore.getState().retainedSyncOperations).toHaveLength(1);
  expect(useWorkspaceStore.getState().details['desktop-saved']).toBeDefined();
  expect(f.cache).not.toHaveBeenCalled();
  await useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  expect(f.api.mock.calls.map(call => call[0])).toEqual(['/api/notes/saved?personal_only=true', '/api/notes/second?personal_only=true', '/api/notes/second?personal_only=true']);
  expect(useWorkspaceStore.getState().details['desktop-saved']).toBeUndefined();
});

it('rejects changed backing IDs rather than reusing a prior response as proof for a different mapping', async () => {
  f.cache.mockRejectedValueOnce(new Error('IndexedDB unavailable'));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('IndexedDB unavailable');
  useWorkspaceStore.setState(s => ({ mappings: { ...s.mappings, third: { key: 'desktop-saved', revision: 4, fingerprint: '' } } }));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('关联内容已变化');
  expect(f.api).toHaveBeenCalledTimes(1);
  expect(useWorkspaceStore.getState().details['desktop-saved']).toBeDefined();
});

it('does not trust a disk claim or retain success proof across reset/reload when a DELETE returns ambiguous 404', async () => {
  f.cache.mockRejectedValueOnce(new Error('IndexedDB unavailable'));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('IndexedDB unavailable');
  const saved = { ...useWorkspaceStore.getState(), confirmedDeletes: { saved: true } };
  useWorkspaceStore.getState().reset(); useWorkspaceStore.setState(saved);
  f.api.mockResolvedValueOnce(new Response(null, { status: 404 }));
  await expect(useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4)).rejects.toThrow('无法确认删除结果');
  expect(useWorkspaceStore.getState().details['desktop-saved']).toBeDefined();
  expect(f.api).toHaveBeenCalledTimes(2);
});

it('does not resurrect a purged local draft, retained unknown operation or DB alias after reload', async () => {
  await useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  const saved = structuredClone(f.cache.mock.calls.at(-1)![1]);
  useWorkspaceStore.getState().reset(); f.read.mockResolvedValue(saved);
  await useWorkspaceStore.getState().initialize('alice');
  expect(useWorkspaceStore.getState().items.map(item => item.key)).toEqual(['unrelated']);
  await expect(useWorkspaceStore.getState().loadDetail('desktop-saved')).rejects.toThrow('已清理');
  expect(f.api).toHaveBeenCalledTimes(1);
});

it('never applies an old DELETE response to another account with the same cached key', async () => {
  const waiting = deferred(); f.api.mockReturnValueOnce(waiting.promise);
  const pending = useWorkspaceStore.getState().purgeDeleted('desktop-saved', 'alice', 4);
  f.owner = 'bob'; useWorkspaceStore.getState().reset();
  const bob = { ...note(), content: 'Bob must keep this body' };
  useWorkspaceStore.setState({ owner: 'bob', ready: true, items: [bob], details: { [bob.key]: bob } });
  waiting.resolve(new Response(null, { status: 204 }));
  await expect(pending).rejects.toThrow('账号');
  expect(useWorkspaceStore.getState().details[bob.key].content).toBe('Bob must keep this body');
  expect(f.cache).not.toHaveBeenCalled();
});
