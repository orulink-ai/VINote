import { expect, it } from 'vitest'
import { serverTimestamp } from './serverTimestamp'

it('preserves the UTC instant when SQLite strips its offset', () => {
  expect(serverTimestamp('2026-10-11T22:16:08.123456').toISOString()).toBe('2026-10-11T22:16:08.123Z')
})
it('retains explicit provider offsets and UTC timestamps', () => {
  expect(serverTimestamp('2026-10-12T06:16:08+08:00').toISOString()).toBe('2026-10-11T22:16:08.000Z')
  expect(serverTimestamp('2026-10-11T22:16:08Z').toISOString()).toBe('2026-10-11T22:16:08.000Z')
})
it('does not invent a timestamp for an invalid or missing value', () => {
  expect(Number.isNaN(serverTimestamp('').getTime())).toBe(true)
  expect(Number.isNaN(serverTimestamp('missing').getTime())).toBe(true)
})
