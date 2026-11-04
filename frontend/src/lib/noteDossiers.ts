import type { LibraryNote } from '@/hooks/useLibraryNotes';
import { serverTimestamp } from './serverTimestamp';

export type NoteDossier = {
  id: string;
  representative: LibraryNote;
  versions: LibraryNote[];
};

/** Group only server-verified originals. A shared title/URL is never identity. */
export function groupNoteDossiers(notes: LibraryNote[]): NoteDossier[] {
  const groups = new Map<string, LibraryNote[]>();
  for (const note of notes) {
    const source = note.originalSource;
    const scope = [note.scope, note.teamId || ''];
    const key = JSON.stringify(source?.ownerId && source.originalId
      ? [...scope, 'original', source.ownerId, source.originalId]
      : [...scope, 'note', note.workspaceKey || note.localId || note.id]);
    const versions = groups.get(key) || [];
    versions.push(note);
    groups.set(key, versions);
  }
  const time = (note: LibraryNote) => {
    const value = serverTimestamp(note.updatedAt || note.createdAt).getTime();
    return Number.isFinite(value) ? value : 0;
  };
  return [...groups].map(([id, versions]) => {
    versions.sort((a, b) => time(b) - time(a) || a.id.localeCompare(b.id));
    return { id, representative: versions[0], versions };
  });
}
