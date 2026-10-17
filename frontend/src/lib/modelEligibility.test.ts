import { test, expect } from 'vitest'
import { modelEligible, modelEligibility } from './modelEligibility'
const now = 1791792000000
const transient = (status: string, retryAt: number | null = now) => ({ runtimeStatus: 'not_available', availability: { status, retryAt } })
test('available or expired transient permits only an explicit attempt', () => {
  expect(modelEligibility({ runtimeStatus: 'available' }, now)).toBe('available')
  for (const status of ['service_error', 'rate_limited']) {
    expect(modelEligibility(transient(status), now)).toBe('retryable')
    expect(modelEligible(transient(status, now - 1), now)).toBe(true)
    expect(modelEligible(transient(status, now + 1), now)).toBe(false)
  }
})
test('auth quota disabled unknown and invalid retry deadlines fail closed', () => {
  for (const status of ['auth_failed', 'permission_denied', 'quota_exhausted', 'disabled', 'unknown', 'available']) {
    expect(modelEligible(transient(status), now)).toBe(false)
  }
  for (const retryAt of [null, undefined, NaN, Infinity, -Infinity, '1791792000000']) {
    expect(modelEligible({ runtimeStatus: 'not_available', availability: { status: 'service_error', retryAt: retryAt as number } }, now)).toBe(false)
  }
  for (const runtimeStatus of ['disabled', 'unavailable', 'missing_api_key', 'unknown']) expect(modelEligible({ ...transient('service_error'), runtimeStatus }, now)).toBe(false)
  expect(modelEligible({ runtimeStatus: 'not_available' }, now)).toBe(false)
  expect(modelEligible({ runtimeStatus: 'available', availability: { status: 'quota_exhausted' } }, now)).toBe(false)
})
