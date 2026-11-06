const key = (owner: string) => `vinote:deleted-meeting-tasks:v1:${owner}`;
const operationsKey = (owner: string) => `vinote:deleted-meeting-operations:v1:${owner}`;
export const MEETING_TASKS_DELETED = 'vinote:meeting-tasks-deleted';
export function deletedMeetingTasks(owner: string): Set<string> {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(key(owner)) || '[]');
    return new Set(Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : []);
  } catch { return new Set(); }
}
export function hideDeletedMeetingTasks(owner: string, taskIds: string[]) {
  const raw = window.localStorage.getItem(key(owner));
  const previous: unknown = raw ? JSON.parse(raw) : [];
  if (!Array.isArray(previous) || !previous.every(id => typeof id === 'string')) throw new Error('已删除任务记录无法读取，请检查本地资料。');
  const ids = new Set<string>(previous);
  for (const id of taskIds) ids.add(id);
  window.localStorage.setItem(key(owner), JSON.stringify([...ids]));
  window.dispatchEvent(new Event(MEETING_TASKS_DELETED));
}
export function deletedMeetingOperation(owner: string, operation: string): boolean {
  try {
    const value = JSON.parse(window.localStorage.getItem(operationsKey(owner)) || '{}');
    return !!value && typeof value === 'object' && !Array.isArray(value) && typeof value[operation] === 'string' && deletedMeetingTasks(owner).has(value[operation]);
  } catch { return false; }
}
export function rememberDeletedMeetingOperation(owner: string, operation: string, taskId: string) {
  if (!deletedMeetingTasks(owner).has(taskId)) return;
  const raw = window.localStorage.getItem(operationsKey(owner));
  const value: unknown = raw ? JSON.parse(raw) : {};
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('任务关联记录无法读取。');
  const mapping = value as Record<string, unknown>;
  if (mapping[operation] !== undefined && mapping[operation] !== taskId) throw new Error('任务关联已变化。');
  mapping[operation] = taskId;
  window.localStorage.setItem(operationsKey(owner), JSON.stringify(mapping));
  window.dispatchEvent(new Event(MEETING_TASKS_DELETED));
}
