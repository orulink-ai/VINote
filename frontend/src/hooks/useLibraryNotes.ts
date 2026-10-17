import { useMemo } from "react";
import {
  useNoteLibraryStore,
  type NoteRecord,
} from "@/stores/noteLibraryStore";
import { useWorkspaceStore } from "@/stores/workspaceStore";
import { useTeamStore } from "@/stores/teamStore";

export type LibraryNote = NoteRecord & {
  dateLabel?: string;
  workspaceKey?: string;
  localId?: string;
  sourceDevice?: string;
  archived?: boolean;
  syncLabel?: string;
  recordingStartedAt?: string;
  duration?: number;
  project?: string;
  tags?: string[];
  /** Identity evidence only; never grants access to a local media file. */
  sourceIds?: string[];
  meetingIdentity?: string[];
  localSources?: LibraryNote[];
};
const appTask = (id: string) => /^app-(.+?)(?:-v\d+)?$/.exec(id)?.[1];
export function libraryNoteIdentities(note: LibraryNote): string[] {
  const scope = `${note.scope || 'personal'}:${note.teamId || ''}:`;
  const ids = [note.id, note.localId, ...(note.sourceIds || [])].filter((id): id is string => !!id);
  return [...new Set([
    ...ids.map(id => `${scope}note:${id}`),
    ...ids.flatMap(id => appTask(id) ? [`${scope}task:${appTask(id)}`] : []),
    ...(note.workspaceKey ? [`${scope}workspace:${note.workspaceKey}`] : []),
    ...(note.taskId ? [`${scope}task:${note.taskId}`] : []),
    ...(note.meetingIdentity || []).map(id => scope + id),
  ])];
}
export const libraryNoteUrl = (note: LibraryNote) =>
  note.workspaceKey
    ? `/workspace/${encodeURIComponent(note.workspaceKey)}`
    : `/note/${encodeURIComponent(note.id)}`;
export function useLibraryNotes() {
  const local = useNoteLibraryStore((s) => s.notes);
  const personal = useTeamStore((s) => s.currentWorkspace.scope === "personal");
  const { items, details, mappings, clearedContentKeys } = useWorkspaceStore();
  return useMemo<LibraryNote[]>(() => {
    if (!personal) return local;
    // Older synced records use the stable desktop source ID even when the local
    // cache mapping has not been restored. Match identity, never title/content.
    const sourceKey = (id: string) => mappings[id]?.key || `desktop-${id}`;
    const identityCache = new Map<string, string[]>();
    const sourceIds = (key: string): string[] => {
      const cached = identityCache.get(key);
      if (cached) return cached;
      const ids = Object.entries(mappings).filter(([, mapping]) => mapping.key === key).map(([id]) => id);
      const wrapped = /^(?:desktop|mobile)-(.+)$/.exec(key)?.[1];
      if (wrapped) ids.push(wrapped);
      for (const note of local) {
        if (details[key]?.versions?.some(version =>
          version.id === note.id || version.id.startsWith(`${note.id}-`) || version.id.startsWith(`source-attachments-${note.id}-`))) ids.push(note.id);
      }
      const result = [...new Set(ids)];
      identityCache.set(key, result);
      return result;
    };
    const localOnly: LibraryNote[] = local
      .filter((n) => {
        if ((clearedContentKeys?.includes(sourceKey(n.id)) || clearedContentKeys?.includes(n.id)) &&
            details[sourceKey(n.id)]?.deleted !== false && details[n.id]?.deleted !== false) return false;
        const shared = items.find(item => item.key === sourceKey(n.id) || sourceIds(item.key).includes(n.id));
        // A newer local edit is a retained draft, not a disposable mirror.
        return !shared || !shared.deleted && n.updatedAt > shared.updated_at;
      })
      .map((n) => ({ ...n, syncLabel: '已保存' }));
    return [
      ...localOnly,
      ...items
        .filter((n) => !n.deleted)
        .map((n) => {
          const metadata = details[n.key]?.metadata ?? {};
          const ids = sourceIds(n.key);
          const localId = Object.entries(mappings).find(
            ([, mapping]) => mapping.key === n.key,
          )?.[0];
          const source = local.find((note) => note.id === localId || sourceKey(note.id) === n.key || ids.includes(note.id));
          const resolvedLocalId = localId || source?.id;
          return {
            id: n.key,
            workspaceKey: n.key,
            title: n.title,
            content: details[n.key]?.content ?? "",
            sourceType: n.source_type,
            sourceDevice: n.source_device,
            dateLabel:
              typeof metadata.source_created_at === "string" ||
              source?.createdAt
                ? "源笔记保存于"
                : "保存于",
            localId: resolvedLocalId,
            taskId: source?.taskId,
            sourceIds: ids,
            // Keep local-only history reachable even when the list uses a shared
            // representative. Projection does not migrate or delete versions.
            localSources: local.filter(note => note.id === localId || sourceKey(note.id) === n.key || ids.includes(note.id)),
            meetingIdentity: [
              ...ids.flatMap(id => appTask(id) ? [`task:${appTask(id)}`] : []),
              ...(['task_id', 'media_id'].flatMap(field => typeof metadata[field] === 'string' && metadata[field] ? [`task:${metadata[field]}`] : [])),
              // App migrations retain deterministic version source IDs even if
              // their media_id was absent. Only this documented format is parsed.
              ...(details[n.key]?.versions || []).flatMap(version => {
                const id = /^(app-.+)-(?:generated|edit)-[^-]+$/.exec(version.id)?.[1];
                return id && appTask(id) ? [`task:${appTask(id)}`] : [];
              }),
            ],
            generationClient: source?.generationClient,
            recordingStartedAt:
              typeof metadata.recording_started_at === "string"
                ? metadata.recording_started_at
                : undefined,
            duration:
              typeof metadata.duration === "number"
                ? metadata.duration
                : undefined,
            project:
              typeof metadata.project === "string"
                ? metadata.project
                : undefined,
            tags: Array.isArray(metadata.tags)
              ? metadata.tags.filter((t): t is string => typeof t === "string")
              : [],
            status: "done",
            scope: "personal" as const,
            createdAt:
              typeof metadata.source_created_at === "string"
                ? metadata.source_created_at
                : source?.createdAt || n.created_at,
            updatedAt: n.updated_at,
            archived: n.archived,
            syncLabel: details[n.key] ? '已保存' : '正文未保存',
          };
        }),
    ].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }, [local, personal, items, details, mappings, clearedContentKeys]);
}
