import { create } from "zustand";
import { apiJson } from "@/lib/api";
import type { WorkspaceNote, WorkspaceStatus, WorkspaceSummary, WorkspaceVersion, WorkspaceWrite } from "@/lib/workspace";
import { readWorkspaceCache, writeWorkspaceCache } from "@/lib/workspaceCache";
import { useAuthStore } from "./authStore";
import { useNoteLibraryStore, type NoteRecord } from "./noteLibraryStore";
import type { ItemSyncPolicies } from '@/lib/itemSyncPolicy';
import { contentResetReceipt } from '@/lib/contentResetReceipt';

type Mapping = { key: string; revision: number; fingerprint: string };
// Kept only to recover pre-removal requests. These records are never dispatched.
export type SyncOperation = {
  key: string; localId?: string; fingerprint?: string; body: WorkspaceWrite;
  error?: string; conflict?: WorkspaceNote; remainingVersions?: WorkspaceVersion[][];
  action?: 'delete' | 'restore'; locallyQueued?: boolean; serviceOrigin?: string;
  baseline?: WorkspaceNote; validationRejection?: { status: 422; message: string };
};
type CachedState = {
  itemPolicies: ItemSyncPolicies; serviceId?: string; items: WorkspaceSummary[];
  details: Record<string, WorkspaceNote>; mappings: Record<string, Mapping>;
  pending: SyncOperation[]; lastSync: string; deviceId: string;
  localOnlyVersion?: 1;
  retainedSyncOperations?: SyncOperation[];
  cloudBaselines?: Record<string, WorkspaceNote[]>;
  appliedContentResets?: string[];
  clearedContentKeys?: string[];
  contentResetCleanupVersion?: 1 | 2;
};
interface State extends CachedState {
  itemSyncMode: (reference: string) => 'local' | 'sync';
  setItemSync: (reference: string, enabled: boolean) => Promise<void>;
  owner: string; ready: boolean; busy: boolean; error: string; status: WorkspaceStatus | null;
  initialize: (owner: string) => Promise<void>; reset: () => void;
  /** Compatibility refresh: no network or timer is started. */
  sync: () => Promise<void>;
  loadDetail: (key: string, allVersions?: boolean) => Promise<WorkspaceNote>;
  save: (key: string, body: WorkspaceWrite) => Promise<WorkspaceNote | null>;
  resolve: (operationId: string, content: string, title: string, comparedRevision?: number, expectedOwner?: string) => Promise<void>;
  changeDeleted: (key: string, deleted: boolean) => Promise<WorkspaceNote | null>;
}
const blank = (): CachedState => ({ itemPolicies: {}, items: [], details: {}, mappings: {}, pending: [],
  lastSync: '', deviceId: crypto.randomUUID(), localOnlyVersion: 1, retainedSyncOperations: [], cloudBaselines: {} });
let epoch = 0;
const snapshot = (s: CachedState): CachedState => ({ itemPolicies: s.itemPolicies, serviceId: s.serviceId,
  items: s.items, details: s.details, mappings: s.mappings, pending: s.pending, lastSync: s.lastSync,
  deviceId: s.deviceId, localOnlyVersion: s.localOnlyVersion, retainedSyncOperations: s.retainedSyncOperations,
  cloudBaselines: s.cloudBaselines, appliedContentResets: s.appliedContentResets, clearedContentKeys: s.clearedContentKeys,
  contentResetCleanupVersion: s.contentResetCleanupVersion });
const message = (e: unknown) => e instanceof Error ? e.message : '保存失败，请重试';
const sameOwner = (owner: string) => !!owner && useAuthStore.getState().user?.id === owner;

// Keep conflicting historical IDs as distinct records, never discard either body.
function retainedVersions(versions: WorkspaceVersion[]): WorkspaceVersion[] {
  const result = new Map<string, WorkspaceVersion>();
  for (const version of versions) {
    const value = (v: WorkspaceVersion) => JSON.stringify([v.title, v.content, v.created_at, v.kind ?? 'imported', v.model ?? '', v.parent_id ?? '', v.evidence_revision ?? null]);
    let id = version.id;
    let suffix = 1;
    while (result.has(id) && value(result.get(id)!) !== value(version)) id = `${version.id}:retained:${suffix++}`;
    if (!result.has(id)) result.set(id, id === version.id ? version : { ...version, id });
  }
  return [...result.values()];
}
const currentVersion = (note: WorkspaceNote): WorkspaceVersion => ({ id: `retained:${note.key}:${note.revision}`,
  title: note.title, content: note.content, created_at: note.updated_at, kind: 'imported' });

/** Pure, repeatable migration. The old operations/baselines remain recoverable;
 * pending is no longer an active queue and cloud tombstones are respected. */
function localize(source: CachedState, owner: string): CachedState {
  const details = { ...source.details };
  const summaries = new Map(source.items.map(item => [item.key, item]));
  const baselines = { ...(source.cloudBaselines || {}) };
  const archive = [...(source.retainedSyncOperations || [])];
  const mappings = { ...source.mappings };
  const applyReset = owner === contentResetReceipt.owner && !(source.appliedContentResets || []).includes(contentResetReceipt.id);
  const clearedKeys = new Set<string>(applyReset ? [...contentResetReceipt.cloudKeys,
    ...contentResetReceipt.desktopIds,
    ...contentResetReceipt.desktopIds.map(id => mappings[id]?.key || `desktop-${id}`)] : []);
  const retainBaseline = (note: WorkspaceNote) => {
    const list = baselines[note.key] || [];
    if (!list.some(old => JSON.stringify(old) === JSON.stringify(note))) baselines[note.key] = [...list, note];
  };
  if (source.localOnlyVersion !== 1) {
    for (const note of Object.values(details)) {
      retainBaseline(note);
      const versions = retainedVersions([...note.versions, currentVersion(note)]);
      details[note.key] = { ...note, deleted: note.deleted || summaries.get(note.key)?.deleted === true,
        versions, version_count: versions.length, next_versions_offset: null };
    }
  }
  for (const key of clearedKeys) {
    const note = details[key];
    if (note) { retainBaseline(note); details[key] = { ...note, deleted: true }; }
    const item = summaries.get(key);
    if (item) summaries.set(key, { ...item, deleted: true });
  }
  for (const op of source.pending) {
    if (!archive.some(old => JSON.stringify(old) === JSON.stringify(op))) archive.push(op);
    if (op.baseline) retainBaseline(op.baseline);
    if (op.conflict) retainBaseline(op.conflict);
    const old = details[op.key];
    const summary = summaries.get(op.key);
    const fallback = old || op.baseline || op.conflict;
    const now = fallback?.updated_at || summary?.updated_at || new Date().toISOString();
    const versions = retainedVersions([
      ...(old?.versions || []), ...(op.baseline?.versions || []), ...(op.conflict?.versions || []),
      ...(fallback ? [currentVersion(fallback)] : []),
      ...(op.baseline ? [currentVersion(op.baseline)] : []), ...(op.conflict ? [currentVersion(op.conflict)] : []),
      ...(op.body.versions || []), ...(op.remainingVersions || []).flat(),
      { id: `recovered:${op.body.operation_id}`, title: op.body.title, content: op.body.content, created_at: now, kind: 'edit' },
    ]);
    // A cached cloud deletion is not undone by an old unknown restore/edit.
    const tombstone = clearedKeys.has(op.key) || source.items.find(item => item.key === op.key)?.deleted === true || source.details[op.key]?.deleted === true;
    details[op.key] = { ...(fallback || {}), key: op.key, title: op.body.title, content: op.body.content,
      source_type: op.body.source_type, source_device: op.body.source_device,
      revision: fallback?.revision ?? summary?.revision ?? op.body.base_revision,
      created_at: fallback?.created_at || summary?.created_at || now, updated_at: now,
      archived: op.body.archived ?? fallback?.archived ?? summary?.archived ?? false,
      deleted: tombstone || op.action === 'delete' || (op.action === 'restore' ? false : old?.deleted ?? false),
      metadata: op.body.metadata ?? fallback?.metadata ?? {}, transcript: op.body.transcript === undefined ? fallback?.transcript ?? null : op.body.transcript,
      versions, version_count: versions.length, next_versions_offset: null };
    if (op.localId && !mappings[op.localId]) mappings[op.localId] = { key: op.key, revision: op.body.base_revision, fingerprint: op.fingerprint || '' };
    summaries.set(op.key, details[op.key]);
  }
  for (const note of Object.values(details)) summaries.set(note.key, { ...note, deleted: note.deleted || summaries.get(note.key)?.deleted === true });
  return { ...source, details, items: [...summaries.values()], mappings, pending: [],
    itemPolicies: Object.fromEntries([...Object.keys(source.itemPolicies || {}), ...summaries.keys(), ...Object.keys(mappings)].map(key => [key, 'local'])),
    localOnlyVersion: 1, retainedSyncOperations: archive, cloudBaselines: baselines,
    appliedContentResets: applyReset ? [...(source.appliedContentResets || []), contentResetReceipt.id] : source.appliedContentResets,
    clearedContentKeys: [...new Set([...(source.clearedContentKeys || []), ...clearedKeys])] };
}

type Scope = { owner: string; epoch: number };

function purgeResetContent(source: CachedState, owner: string): CachedState {
  if (owner !== contentResetReceipt.owner) return source;
  const keys = new Set<string>([...contentResetReceipt.cloudKeys, ...contentResetReceipt.desktopIds,
    ...contentResetReceipt.desktopIds.map(id => `desktop-${id}`), ...(source.clearedContentKeys || [])]);
  for (const [id, mapping] of Object.entries(source.mappings)) if (keys.has(id)) keys.add(mapping.key);
  for (const key of [...keys]) keys.add(`recovered-cleared-${key}`);
  const details = { ...source.details };
  const histories = source.retainedSyncOperations || [];
  for (const key of keys) {
    delete details[key];
  }
  return { ...source, details,
    items: [...source.items.filter(item => !keys.has(item.key)).map(item => details[item.key] || item),
      ...Object.values(details).filter(note => !source.items.some(item => item.key === note.key))],
    mappings: Object.fromEntries(Object.entries(source.mappings).filter(([id, mapping]) => !keys.has(id) && !keys.has(mapping.key))),
    itemPolicies: Object.fromEntries(Object.entries(source.itemPolicies).filter(([key]) => !keys.has(key))),
    cloudBaselines: Object.fromEntries(Object.entries(source.cloudBaselines || {}).filter(([key]) => !keys.has(key))),
    retainedSyncOperations: histories.filter(op => !keys.has(op.key)),
    clearedContentKeys: [...keys], contentResetCleanupVersion: 2 };
}

export const useWorkspaceStore = create<State>((set, get) => {
  const scopeFor = (): Scope => ({ owner: get().owner, epoch });
  const currentScope = (scope: Scope) => epoch === scope.epoch && get().owner === scope.owner && sameOwner(scope.owner);
  const guard = (scope: Scope) => { if (!currentScope(scope)) throw new Error('账号已变化，请重新打开；原稿保留'); };
  const requireReady = (scope: Scope) => { guard(scope); if (!get().ready) throw new Error('资料尚未读取，请稍后重试'); };
  const persist = async (scope: Scope) => {
    guard(scope);
    await writeWorkspaceCache(scope.owner, structuredClone(snapshot(get())));
    guard(scope);
  };
  const accept = (note: WorkspaceNote) => set(s => ({ details: { ...s.details, [note.key]: note },
    items: [note, ...s.items.filter(n => n.key !== note.key)].sort((a, b) => b.updated_at.localeCompare(a.updated_at)) }));
  const canonicalKey = (reference: string) => get().mappings[reference]?.key ||
    (get().details[reference] || get().items.some(item => item.key === reference) ? reference :
      useNoteLibraryStore.getState().notes.some(note => note.id === reference && note.scope === 'personal') ? `desktop-${reference}` : reference);
  const commit = async (scope: Scope, mutate: () => void) => {
    const previous = snapshot(get());
    try { mutate(); await persist(scope); }
    catch (cause) { if (currentScope(scope)) set(previous); throw cause; }
  };
  const read = async (reference: string, scope: Scope): Promise<WorkspaceNote> => {
    requireReady(scope);
    const key = canonicalKey(reference);
    if (get().contentResetCleanupVersion === 2 && get().clearedContentKeys?.includes(key)) throw new Error('这份历史内容已清理，原文件仍在文件库');
    const cached = get().details[key];
    if (cached) return cached;
    const id = Object.entries(get().mappings).find(([, mapping]) => mapping.key === key)?.[0] ||
      (key.startsWith('desktop-') ? key.slice(8) : key);
    // This is the existing desktop note database, never the shared workspace.
    const legacy: NoteRecord | null = await useNoteLibraryStore.getState().loadNoteById(id);
    guard(scope);
    if (!legacy || legacy.scope !== 'personal') throw new Error('这份内容未保存在当前设备，无法读取；已有资料未删除');
    const history = await apiJson<WorkspaceVersion[]>(`/api/notes/${encodeURIComponent(id)}/versions`);
    guard(scope);
    const summary = get().items.find(item => item.key === key);
    const versions = retainedVersions([...history, { id: `source:${id}:${legacy.updatedAt}`, title: legacy.title,
      content: legacy.content, created_at: legacy.updatedAt, kind: 'imported' }]);
    const note: WorkspaceNote = { key, title: legacy.title, content: legacy.content, source_type: legacy.sourceType || 'text',
      source_device: 'desktop', revision: summary?.revision ?? 0, created_at: legacy.createdAt, updated_at: legacy.updatedAt,
      archived: summary?.archived ?? false, deleted: summary?.deleted ?? get().clearedContentKeys?.includes(key) ?? false, metadata: { source_created_at: legacy.createdAt, ...(legacy.videoUrl ? { source_url: legacy.videoUrl } : {}), ...(legacy.taskId ? { task_id: legacy.taskId } : {}) },
      transcript: null, versions, version_count: versions.length, next_versions_offset: null };
    await commit(scope, () => { accept(note); set(s => ({ mappings: { ...s.mappings, [id]: { key, revision: note.revision, fingerprint: '' } } })); });
    return note;
  };
  return {
    ...blank(), owner: '', ready: false, busy: false, error: '', status: null,
    itemSyncMode: () => 'local',
    setItemSync: async (_reference, enabled) => { if (enabled) throw new Error('同步功能已移除，内容仍可保存和编辑'); },
    initialize: async owner => {
      if (get().owner === owner && get().ready && (owner !== contentResetReceipt.owner || get().contentResetCleanupVersion === 2)) return;
      const run = ++epoch;
      set({ ...blank(), owner, ready: false, busy: false, error: '', status: null });
      try {
        if (!sameOwner(owner)) throw new Error('账号已变化，请重新打开');
        const cached = await readWorkspaceCache<CachedState>(owner);
        if (run !== epoch || !sameOwner(owner)) return;
        // Do not fill the migration version from blank() before checking an old cache.
        const recovered = purgeResetContent(localize(cached ? { ...blank(), ...cached, localOnlyVersion: cached.localOnlyVersion } : blank(), owner), owner);
        if (run !== epoch || !sameOwner(owner)) return;
        // Recovery is durable before exposing an empty pending queue.
        await writeWorkspaceCache(owner, structuredClone(recovered));
        if (run !== epoch || !sameOwner(owner)) return;
        set({ ...recovered, ready: true });
      } catch (cause) { if (run === epoch) set({ error: `无法保存资料：${message(cause)}`, ready: false }); }
    },
    reset: () => { epoch++; set({ ...blank(), owner: '', ready: false, busy: false, error: '', status: null }); },
    // Left as a no-network compatibility method for callers being removed.
    sync: async () => {
      const scope = scopeFor();
      if (!get().ready || get().busy || !currentScope(scope)) return;
      if (!get().pending.length && get().localOnlyVersion === 1) return;
      set({ busy: true });
      try { await commit(scope, () => set(localize(snapshot(get()), scope.owner))); }
      catch (cause) { if (currentScope(scope)) set({ error: message(cause) }); }
      finally { if (currentScope(scope)) set({ busy: false }); }
    },
    loadDetail: async (reference, _allVersions) => {
      const scope = scopeFor(); requireReady(scope);
      if (get().pending.length || get().localOnlyVersion !== 1) {
        if (get().busy) throw new Error('正在保存，请稍后重试读取');
        await commit(scope, () => set(localize(snapshot(get()), scope.owner)));
      }
      return read(reference, scope);
    },
    save: async (reference, body) => {
      const scope = scopeFor(); requireReady(scope);
      if (get().busy) throw new Error('正在保存，请稍后重试；草稿保留');
      set({ busy: true });
      try {
        let note!: WorkspaceNote;
        await commit(scope, () => {
          set(localize(snapshot(get()), scope.owner));
          const key = canonicalKey(reference);
          if (get().contentResetCleanupVersion === 2 && get().clearedContentKeys?.includes(key)) throw new Error('这份历史内容已清理，请新建笔记保存修改');
          const old = get().details[key];
          if (old?.deleted || get().items.find(item => item.key === key)?.deleted) throw new Error('请先恢复这份内容，再保存修改');
          if (old && body.base_revision !== old.revision) throw new Error('正文已发生修改，请重新读取后保存；草稿保留');
          const replay = old?.versions.find(v => v.id === `local:${body.operation_id}`);
          if (replay) {
            if (replay.title !== body.title || replay.content !== body.content) throw new Error('保存标识已用于另一份修改，请保留草稿并重新保存');
            note = old!; return;
          }
          const savedAt = new Date().toISOString();
          const versions = retainedVersions([...(old?.versions || []), ...(old ? [currentVersion(old)] : []), ...(body.versions || []),
            { id: `local:${body.operation_id}`, title: body.title, content: body.content, created_at: savedAt, kind: 'edit' }]);
          note = { ...(old || {}), key, title: body.title, content: body.content, source_type: body.source_type,
            source_device: body.source_device, revision: (old?.revision ?? body.base_revision) + 1,
            created_at: old?.created_at || savedAt, updated_at: savedAt, deleted: false,
            archived: body.archived ?? old?.archived ?? false, metadata: body.metadata ?? old?.metadata ?? {},
            transcript: body.transcript === undefined ? old?.transcript ?? null : body.transcript,
            versions, version_count: versions.length, next_versions_offset: null };
          accept(note);
        });
        return note;
      } catch (cause) { throw new Error(`保存未完成：${message(cause)}。请保留草稿后重试。`); }
      finally { if (currentScope(scope)) set({ busy: false }); }
    },
    changeDeleted: async (reference, deleted) => {
      const scope = scopeFor(); requireReady(scope);
      if (get().busy) throw new Error('正在保存，请完成后再操作');
      set({ busy: true });
      try {
        // Fold even unknown old writes before changing the local tombstone.
        if (get().pending.length || get().localOnlyVersion !== 1) await commit(scope, () => set(localize(snapshot(get()), scope.owner)));
        const note = await read(reference, scope);
        const next = note.deleted === deleted ? note : { ...note, deleted, revision: note.revision + 1, updated_at: new Date().toISOString() };
        await commit(scope, () => accept(next));
        return next;
      } finally { if (currentScope(scope)) set({ busy: false }); }
    },
    resolve: async (operationId, content, title, comparedRevision, expectedOwner) => {
      const scope = scopeFor(); requireReady(scope);
      if (expectedOwner && scope.owner !== expectedOwner) throw new Error('账号已变化，原稿保留在原账号');
      const operation = [...get().pending, ...(get().retainedSyncOperations || [])].find(op => op.body.operation_id === operationId);
      if (!operation) throw new Error('原修改不存在，请重新打开正文');
      if (comparedRevision !== undefined && operation.conflict && comparedRevision !== operation.conflict.revision) throw new Error('请重新比较原修改；草稿保留');
      const note = await get().loadDetail(operation.key, true);
      guard(scope);
      await get().save(note.key, { ...operation.body, operation_id: crypto.randomUUID(), base_revision: note.revision, title, content });
    },
  };
});
