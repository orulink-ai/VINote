import { useEffect } from "react";
import { useAuthStore } from "@/stores/authStore";
import { useNoteLibraryStore } from "@/stores/noteLibraryStore";
import { useWorkspaceStore, type SyncOperation } from "@/stores/workspaceStore";

export type WorkspaceOperationState = 'local' | 'queued' | 'unknown' | 'conflict'
export function workspaceOperationState(op: SyncOperation, mode: 'local' | 'sync'): WorkspaceOperationState {
  if (op.conflict) return 'conflict'
  if (op.locallyQueued !== true) return 'unknown'
  return mode === 'local' ? 'local' : 'queued'
}
export function workspaceSyncGroups(pending: SyncOperation[], mode: (key: string) => 'local' | 'sync', deleted: (key: string) => boolean = () => false) {
  const groups: Record<WorkspaceOperationState, SyncOperation[]> = { local: [], queued: [], unknown: [], conflict: [] }
  for (const op of pending) {
    const kind = workspaceOperationState(op, mode(op.key))
    if (kind !== 'local' || !deleted(op.key)) groups[kind].push(op)
  }
  return { ...groups, active: pending.filter(op => workspaceOperationState(op, mode(op.key)) !== 'local') }
}

export function WorkspaceSync() {
  const owner = useAuthStore((s) => s.user?.id);
  useEffect(() => {
    if (!owner) return;
    let active = true;
    let debounce: ReturnType<typeof setTimeout> | undefined;
    const sync = () => {
      if (active && useAuthStore.getState().user?.id === owner && document.visibilityState !== "hidden")
        void useWorkspaceStore.getState().sync();
    };
    void useWorkspaceStore.getState().initialize(owner).then(sync);
    const unsubscribe = useNoteLibraryStore.subscribe((next, previous) => {
      const state = useWorkspaceStore.getState()
      // Local-only content changes do not request an upload. Regular foreground
      // checks still read permitted shared updates from the other devices.
      if (next.notes !== previous.notes && next.notes.some(note => state.itemSyncMode(note.id) === 'sync' && previous.notes.find(old => old.id === note.id) !== note)) {
        clearTimeout(debounce);
        debounce = setTimeout(sync, 1500);
      }
    });
    window.addEventListener("online", sync);
    window.addEventListener("focus", sync);
    const timer = setInterval(sync, 60000);
    return () => {
      active = false;
      clearInterval(timer);
      clearTimeout(debounce);
      unsubscribe();
      window.removeEventListener("online", sync);
      window.removeEventListener("focus", sync);
      useWorkspaceStore.getState().reset();
    };
  }, [owner]);
  return null;
}
