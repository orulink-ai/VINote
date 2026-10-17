// retryAt is the catalog's Unix timestamp in milliseconds. This permits an explicit attempt, not a health claim.
export type ModelEligibilityInput = {
  runtimeStatus: string
  availability?: { status?: string; retryAt?: number | null }
}
export function modelEligibility(model: ModelEligibilityInput, now = Date.now()): 'available' | 'retryable' | 'blocked' {
  const status = model.availability?.status
  if (status && ['auth_failed', 'permission_denied', 'quota_exhausted', 'disabled'].includes(status)) return 'blocked'
  if (model.runtimeStatus === 'available') return 'available'
  const retryAt = model.availability?.retryAt
  return model.runtimeStatus === 'not_available' &&
    (status === 'service_error' || status === 'rate_limited') &&
    typeof retryAt === 'number' && Number.isFinite(retryAt) && Number.isFinite(now) && retryAt <= now
    ? 'retryable' : 'blocked'
}
export function modelEligible(model: ModelEligibilityInput, now = Date.now()): boolean {
  return modelEligibility(model, now) !== 'blocked'
}
