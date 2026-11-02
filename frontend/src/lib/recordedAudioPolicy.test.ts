import { describe, expect, it } from 'vitest'
import { meetingReady, recordedAudioDescription, recordedAudioReady, transcriptionReady } from './recordedAudioPolicy'

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

const meetingCapabilities = {
  recordedAudio: { protocol: 1, supported: true, strategy: 'single_request', policySource: 'provider_model' },
  useCases: ['recording', 'meeting'],
  protocols: ['asr-recording'],
  audioFormats: ['wav'],
  audioDelivery: 'public',
  maxAudioSeconds: 10800,
  maxAudioBytes: 536870912,
  speakerDiarization: true,
  utteranceTimestamps: true,
}
const meetingModel = { runtimeStatus: 'available', capabilities: meetingCapabilities }
const without = (patch: Record<string, unknown>) => ({
  ...meetingModel,
  capabilities: { ...meetingCapabilities, ...patch },
})

describe('meeting readiness', () => {
  it('accepts only the complete whole-file contract', () => {
    expect(meetingReady(meetingModel)).toEqual({ ready: true, reason: '' })
    expect(recordedAudioDescription(meetingModel, true)).toContain('整段识别')
  })

  it('names each missing capability instead of blaming the model name', () => {
    expect(meetingReady(without({ speakerDiarization: false })).reason).toContain('说话人分离')
    expect(meetingReady(without({ utteranceTimestamps: false })).reason).toContain('时间戳')
    expect(meetingReady(without({ useCases: ['recording'] })).reason).toContain('会议录音用途')
    expect(meetingReady(without({ protocols: ['asr-streaming'] })).reason).toContain('整段录音协议')
    expect(meetingReady(without({ audioDelivery: 'private' })).reason).toContain('音频地址')
    expect(meetingReady(without({ audioFormats: ['mp3'] })).reason).toContain('WAV')
    expect(meetingReady(without({ maxAudioSeconds: 0 })).reason).toContain('录音时长')
    expect(meetingReady(without({ maxAudioBytes: undefined })).reason).toContain('录音大小')
  })

  it('keeps adaptive segmentation usable for recordings without claiming meetings', () => {
    const adaptive = { runtimeStatus: 'available', capabilities: { recordedAudio: {
      protocol: 1, supported: true, strategy: 'adaptive_pause', policySource: 'service_budget', maxSessionAudioBytes: 2097152,
    } } }
    expect(meetingReady(adaptive).ready).toBe(false)
    expect(transcriptionReady(adaptive)).toBe(true)
    expect(transcriptionReady(meetingModel)).toBe(true)
    expect(transcriptionReady({ runtimeStatus: 'available' })).toBe(false)
  })
})
