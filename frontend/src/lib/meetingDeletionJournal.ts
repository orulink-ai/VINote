export type MeetingDeletionIntent = { canonical: string; recordings: string[]; entries: { key: string; revision: number }[] };
const storageKey = (owner: string) => `vinote:meeting-deletion:${owner}`;
const validId = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,160}$/.test(value);
export function readMeetingDeletion(owner: string): MeetingDeletionIntent | null {
  const raw = window.localStorage.getItem(storageKey(owner));
  if (!raw) return null;
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== 'object') throw new Error('待完成的会议删除记录无效，请检查本地资料。');
  const intent = value as MeetingDeletionIntent;
  if (!validId(intent.canonical) || !Array.isArray(intent.recordings) || !intent.recordings.every(validId) || !Array.isArray(intent.entries) || !intent.entries.every(entry => entry && typeof entry.key === 'string' && entry.key.length > 0 && entry.key.length <= 512 && Number.isSafeInteger(entry.revision) && entry.revision >= 0)) throw new Error('待完成的会议删除记录无效，请检查本地资料。');
  return intent;
}
export function writeMeetingDeletion(owner: string, intent: MeetingDeletionIntent) {
  const existing = readMeetingDeletion(owner);
  if (existing && existing.canonical !== intent.canonical) throw new Error('请先完成上一场会议的删除。');
  window.localStorage.setItem(storageKey(owner), JSON.stringify(intent));
}
export function clearMeetingDeletion(owner: string) { window.localStorage.removeItem(storageKey(owner)); }
