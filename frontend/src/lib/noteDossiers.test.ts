import { describe, expect, it } from 'vitest';
import type { LibraryNote } from '@/hooks/useLibraryNotes';
import { groupNoteDossiers } from './noteDossiers';

const note = (id: string, originalId?: string, ownerId = 'alice'): LibraryNote => ({
  id, title: 'Same title', content: id, status: 'done', scope: 'personal',
  createdAt: '2026-11-04T00:00:00Z', updatedAt: `2026-11-04T0${id === 'new' ? 2 : 1}:00:00Z`,
  ...(originalId ? { originalSource: { ownerId, originalId, canonicalTaskId: 'source-task' } } : {}),
});

describe('ordinary note dossiers', () => {
  it('keeps all versions under their verified original and opens the newest', () => {
    const old = note('old', 'task:one'); const newer = note('new', 'task:one');
    const groups = groupNoteDossiers([old, newer]);
    expect(groups).toHaveLength(1);
    expect(groups[0].representative.id).toBe('new');
    expect(groups[0].versions.map(version => version.id)).toEqual(['new', 'old']);
  });
  it('never groups same title, URL or unverified task IDs', () => {
    expect(groupNoteDossiers([note('one'), note('two')])).toHaveLength(2);
  });
  it('separates owners, team scopes and distinct originals', () => {
    expect(groupNoteDossiers([note('one', 'task:one'), note('two', 'task:one', 'bob'),
      { ...note('three', 'task:one'), scope: 'team', teamId: 'team' }, note('four', 'task:two')])).toHaveLength(4);
  });
});
