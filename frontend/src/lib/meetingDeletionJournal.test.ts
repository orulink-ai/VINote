import { expect, it } from 'vitest';
import { readMeetingDeletion, writeMeetingDeletion, clearMeetingDeletion } from './meetingDeletionJournal';
it('retains an owner-scoped deletion intent until cleanup completes', () => {
  const values = new Map<string, string>();
  Object.defineProperty(window, 'localStorage', { configurable: true, value: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) } });
  const entry = { canonical: 'task-a', recordings: ['recording-a'], entries: [{ key: 'desktop-note', revision: 3 }] };
  writeMeetingDeletion('owner-a', entry);
  expect(readMeetingDeletion('owner-a')).toEqual(entry);
  expect(readMeetingDeletion('owner-b')).toBeNull();
  clearMeetingDeletion('owner-a');
  expect(readMeetingDeletion('owner-a')).toBeNull();
});
