import { deletedMeetingOperation, deletedMeetingTasks } from './deletedMeetingTasks'
export type GenerationNotificationTask = { taskId?: string; operationId?: string; recordingId?: string; meeting: boolean; mode?: string; title?: string }
type Entry = GenerationNotificationTask & { active?: boolean; terminal?: string; baseline?: boolean }
export const TASK_NOTIFICATION_EVENT = 'vinote:notification-work'
export const TASK_ACTIVITY_EVENT = 'vinote:task-activity'
const key = (owner: string) => `vinote:task-notifications:v1:${owner}`
const identity = (task: GenerationNotificationTask) => task.operationId || task.taskId || ''
const sameTask = (a: GenerationNotificationTask, b: GenerationNotificationTask) => identity(a) === identity(b) || !!a.taskId && a.taskId === b.taskId
export function readTrackedGenerations(owner: string): Entry[] {
  try { const deleted = deletedMeetingTasks(owner); const value = JSON.parse(localStorage.getItem(key(owner)) || '[]'); return Array.isArray(value) ? value.filter(item => item && typeof item.meeting === 'boolean' && identity(item) && (!item.taskId || !deleted.has(item.taskId)) && (!item.operationId || !deletedMeetingOperation(owner, item.operationId))) : [] } catch { return [] }
}
function save(owner: string, entries: Entry[]) {
  const next = JSON.stringify(entries)
  if (localStorage.getItem(key(owner)) === next) return
  localStorage.setItem(key(owner), next)
  window.dispatchEvent(new Event(TASK_ACTIVITY_EVENT))
}
export function trackGenerationNotification(owner: string, task: GenerationNotificationTask) {
  if (!owner || !identity(task) || task.taskId && deletedMeetingTasks(owner).has(task.taskId)) return
  const entries = readTrackedGenerations(owner)
  const previous = entries.find(item => sameTask(item, task))
  if (previous) {
    Object.assign(previous, task)
    // A newly accepted producer can race a receipt poll. Re-arm only a known
    // silent baseline, never a delivered or older unclassified terminal.
    if (previous.baseline === true) { delete previous.terminal; previous.active = true; previous.baseline = false }
  }
  else entries.push({ ...task, active: true })
  save(owner, entries)
  window.dispatchEvent(new Event(TASK_NOTIFICATION_EVENT))
}
/** A first historical terminal is only a baseline. Persist before delivering. */
export function observeGeneration(owner: string, task: GenerationNotificationTask, status: string): boolean {
  if (task.taskId && deletedMeetingTasks(owner).has(task.taskId)) return false
  const entries = readTrackedGenerations(owner)
  let entry = entries.find(item => sameTask(item, task))
  const terminal = ['success', 'failed', 'error'].includes(status)
  const notify = terminal && !!entry?.active && entry.terminal !== status
  if (!entry) { entry = { ...task, baseline: terminal }; entries.push(entry) }
  Object.assign(entry, task)
  if (terminal) { entry.terminal = status; entry.active = false; if (notify) entry.baseline = false }
  else entry.active = true
  save(owner, entries)
  return notify
}
export function notificationTarget(task: GenerationNotificationTask, noteId?: string) {
  if (noteId) return `/note/${encodeURIComponent(noteId)}`
  if (task.recordingId) return '/meetings?' + new URLSearchParams({ locate_recording: task.recordingId, locate_focus: 'meeting' })
  const query = new URLSearchParams({ mode: task.mode === 'url' ? 'url' : 'file' })
  if (task.meeting) query.set('meeting', '1')
  if (task.operationId) query.set('operation', task.operationId)
  else if (task.taskId) query.set('task', task.taskId)
  return '/generate?' + query
}
export function sourceNotificationTasks(owner: string): GenerationNotificationTask[] {
  const deleted = deletedMeetingTasks(owner)
  const tasks = new Map(readTrackedGenerations(owner).filter(item => !item.terminal).map(item => [identity(item), item]))
  for (let i = 0; i < localStorage.length; i++) {
    const name = localStorage.key(i) || ''
    if (![`vinote:source-receipt:${owner}:`, `vinote:source-task-receipt:${owner}:`, `vinote:import-receipt:${owner}:`].some(prefix => name.startsWith(prefix))) continue
    try {
      const item = JSON.parse(localStorage.getItem(name) || 'null')
      if (!item || (item.owner && item.owner !== owner) || typeof item.meeting !== 'boolean' || item.submissionState === 'not_accepted') continue
      if (item.id && deleted.has(item.id)) continue
      if (item.operationId && deletedMeetingOperation(owner, item.operationId)) continue
      const task = { taskId: item.id || undefined, operationId: item.operationId, meeting: item.meeting, mode: item.mode, title: item.sourceTitle || item.title || item.sourceUrl }
      if (identity(task) && !readTrackedGenerations(owner).find(old => identity(old) === identity(task))?.terminal) tasks.set(identity(task), task)
    } catch { /* A damaged receipt never triggers work. */ }
  }
  return [...tasks.values()]
}
export function backgroundNotificationsEnabled(owner: string) { return localStorage.getItem(`vinote:background-notifications:${owner}`) !== 'off' }
export function setBackgroundNotifications(owner: string, enabled: boolean) { localStorage.setItem(`vinote:background-notifications:${owner}`, enabled ? 'on' : 'off') }
