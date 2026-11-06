import { beforeEach, expect, it } from 'vitest'
import { observeGeneration, readTrackedGenerations, trackGenerationNotification, notificationTarget } from './taskNotifications'
beforeEach(() => localStorage.clear())
it('baselines historical terminals and emits only once after an active observation', () => {
  const task = { taskId: 'task-a', meeting: true }
  expect(observeGeneration('a', task, 'success')).toBe(false)
  const next = { taskId: 'task-b', meeting: false }
  expect(observeGeneration('a', next, 'processing')).toBe(false)
  expect(observeGeneration('a', next, 'success')).toBe(true)
  expect(observeGeneration('a', next, 'success')).toBe(false)
})
it('explicit newly accepted work emits even if first poll already completed; persists and isolates owners', () => {
  const task = { taskId: 'task-a', operationId: 'op-a', meeting: true }
  trackGenerationNotification('a', task)
  expect(readTrackedGenerations('b')).toEqual([])
  expect(observeGeneration('a', task, 'failed')).toBe(true)
  expect(observeGeneration('a', task, 'failed')).toBe(false)
  expect(observeGeneration('b', task, 'failed')).toBe(false)
})
it('uses exact operation recovery and prefers saved result identity', () => {
  expect(notificationTarget({ taskId: 'task', operationId: 'op', meeting: true })).toBe('/generate?mode=file&meeting=1&operation=op')
  expect(notificationTarget({ taskId: 'task', meeting: false }, 'note')).toBe('/note/note')
})
it('deduplicates task and operation aliases without rearming completed work', () => {
  trackGenerationNotification('a', { taskId: 'task', meeting: true })
  trackGenerationNotification('a', { taskId: 'task', operationId: 'op', meeting: true })
  expect(readTrackedGenerations('a')).toHaveLength(1)
  expect(observeGeneration('a', { taskId: 'task', meeting: true }, 'success')).toBe(true)
  expect(observeGeneration('a', { taskId: 'task', operationId: 'op', meeting: true }, 'success')).toBe(false)
})
it('arms an explicitly accepted operation after a fast result was historically baselined, but never rearms a delivered terminal', () => {
  const task = { taskId: 'fast', operationId: 'op-fast', meeting: true }
  expect(observeGeneration('a', task, 'success')).toBe(false)
  trackGenerationNotification('a', task)
  expect(observeGeneration('a', task, 'success')).toBe(true)
  trackGenerationNotification('a', task)
  expect(observeGeneration('a', task, 'success')).toBe(false)
})
it('opens the retained recording workbench when no saved result exists', () => {
  const task = { taskId: 'task', recordingId: 'recording-1', meeting: true }
  expect(notificationTarget(task)).toBe('/meetings?locate_recording=recording-1&locate_focus=meeting')
  expect(notificationTarget(task, 'saved')).toBe('/note/saved')
})
it('never polls or notifies deleted task IDs while preserving their receipts', async () => {
  const { hideDeletedMeetingTasks } = await import('./deletedMeetingTasks')
  const { sourceNotificationTasks } = await import('./taskNotifications')
  const deleted = { taskId: 'removed', operationId: 'removed-op', meeting: true }
  trackGenerationNotification('a', deleted)
  localStorage.setItem('vinote:source-receipt:a:removed-op', JSON.stringify({ id: 'removed', operationId: 'removed-op', meeting: true }))
  localStorage.setItem('vinote:source-receipt:a:kept-op', JSON.stringify({ id: 'kept', operationId: 'kept-op', meeting: true }))
  hideDeletedMeetingTasks('a', ['removed'])
  expect(sourceNotificationTasks('a').map(task => task.taskId)).toEqual(['kept'])
  expect(readTrackedGenerations('a')).toEqual([])
  expect(observeGeneration('a', deleted, 'success')).toBe(false)
  expect(localStorage.getItem('vinote:source-receipt:a:removed-op')).not.toBeNull()
})
