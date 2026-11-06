import { afterEach, expect, it, vi } from 'vitest'
import { withMeetingDeletionLock } from './meetingDeletionLock'

afterEach(() => vi.unstubAllGlobals())

it('fails closed when cross-window locking is unavailable', async () => {
  vi.stubGlobal('navigator', {})
  const work = vi.fn()
  await expect(withMeetingDeletionLock('owner', work)).rejects.toThrow('无法安全协调')
  expect(work).not.toHaveBeenCalled()
})

it('allows only one deletion for the same owner across windows and releases on completion', async () => {
  const held = new Set<string>()
  vi.stubGlobal('navigator', { locks: { request: async (name: string, _options: unknown, callback: (lock: object | null) => Promise<unknown>) => {
    if (held.has(name)) return callback(null)
    held.add(name)
    try { return await callback({ name }) } finally { held.delete(name) }
  } } })
  let resolve!: () => void
  const waiting = new Promise<void>(done => { resolve = done })
  const first = withMeetingDeletionLock('owner', () => waiting)
  const second = vi.fn()
  await expect(withMeetingDeletionLock('owner', second)).rejects.toThrow('正在删除')
  expect(second).not.toHaveBeenCalled()
  resolve(); await first
  await withMeetingDeletionLock('owner', async () => { second() })
  expect(second).toHaveBeenCalledOnce()
})
