import { describe, expect, it } from 'vitest'
import { recordedAudioDescription, recordedAudioReady } from './recordedAudioPolicy'

const model = { runtimeStatus: 'available', capabilities: { recordedAudio: {
  protocol: 1, supported: true, strategy: 'adaptive_pause', policySource: 'service_budget', maxSessionAudioBytes: 2097152,
} } }

describe('recorded audio applicability', () => {
  it('describes adaptive recording support without inventing a model duration limit', () => {
    expect(recordedAudioReady(model)).toBe(true)
    expect(recordedAudioDescription(model, true)).toBe('录音转写 · 按停顿自动分段')
  })
  it('distinguishes an old service from an incapable model', () => {
    expect(recordedAudioReady({ runtimeStatus: 'available' })).toBe(false)
    expect(recordedAudioDescription({ runtimeStatus: 'available' }, true)).toContain('服务需更新')
  })
  it('rejects malformed budgets and reports authorization separately', () => {
    expect(recordedAudioReady({ ...model, capabilities: { recordedAudio: {
      ...model.capabilities.recordedAudio, maxSessionAudioBytes: 641,
    } } })).toBe(false)
    expect(recordedAudioDescription({ ...model, availability: { status: 'auth_failed' } }, true)).toBe('服务授权待处理')
  })
})
