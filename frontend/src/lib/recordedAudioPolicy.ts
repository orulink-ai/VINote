import { modelEligible, type ModelEligibilityInput } from './modelEligibility'

export type RecordedAudioModel = ModelEligibilityInput & {
  capabilities?: {
    recordedAudio?: {
      protocol?: number; supported?: boolean; strategy?: string
      maxSessionAudioBytes?: number; reasonCode?: string; policySource?: string
    }
    useCases?: unknown
    protocols?: unknown
    audioFormats?: unknown
    audioDelivery?: unknown
    maxAudioSeconds?: unknown
    maxAudioBytes?: unknown
    speakerDiarization?: unknown
    utteranceTimestamps?: unknown
  }
}

const strings = (value: unknown): string[] | null =>
  Array.isArray(value) && value.every(item => typeof item === 'string') ? value as string[] : null

export function recordedAudioReady(model: RecordedAudioModel): boolean {
  const policy = model.capabilities?.recordedAudio
  const bytes = policy?.maxSessionAudioBytes
  return modelEligible(model) && policy?.protocol === 1 && policy.supported === true &&
    policy.strategy === 'adaptive_pause' && policy.policySource === 'service_budget' && typeof bytes === 'number' &&
    Number.isSafeInteger(bytes) && bytes >= 640 && bytes <= 64 * 1024 * 1024 && bytes % 2 === 0
}

export type MeetingReadiness = { ready: boolean; reason: string }

/**
 * A meeting recording is one complete audio file, not a live stream. The
 * service must declare the whole contract; a model name never implies it.
 */
export function meetingReady(model: RecordedAudioModel): MeetingReadiness {
  const capabilities = model.capabilities
  const policy = capabilities?.recordedAudio
  if (!modelEligible(model)) {
    const status = model.availability?.status
    if (status === 'auth_failed' || status === 'permission_denied') return { ready: false, reason: '服务授权待处理' }
    if (status === 'quota_exhausted') return { ready: false, reason: '服务额度不足' }
    if (status === 'disabled') return { ready: false, reason: '服务已停用' }
    return { ready: false, reason: '服务暂不可用' }
  }
  // A retryable model is an explicit attempt, not a health claim: the declared
  // whole-file contract still has to hold before any meeting audio is sent.
  if (!policy || policy.protocol !== 1) return { ready: false, reason: '服务尚未提供录音处理规则，请更新服务' }
  if (policy.supported !== true) return { ready: false, reason: '服务的录音处理配置待修复' }
  const useCases = strings(capabilities?.useCases)
  if (capabilities?.useCases !== undefined && !useCases) return { ready: false, reason: '录音模型的用途声明无效' }
  if (!useCases?.includes('meeting')) return { ready: false, reason: '该模型未声明会议录音用途，只能用于实时转写' }
  const protocols = strings(capabilities?.protocols)
  if (capabilities?.protocols !== undefined && !protocols) return { ready: false, reason: '录音模型的协议声明无效' }
  if (!protocols?.includes('asr-recording')) return { ready: false, reason: '该模型未提供整段录音协议' }
  const formats = strings(capabilities?.audioFormats)
  if (capabilities?.audioFormats !== undefined && !formats) return { ready: false, reason: '录音模型的格式声明无效' }
  if (!formats?.includes('wav')) return { ready: false, reason: '该模型不支持 WAV 录音' }
  if (capabilities?.audioDelivery !== 'public') {
    return { ready: false, reason: '当前服务没有可被语音服务访问的音频地址，会议转写暂不可用' }
  }
  if (policy.strategy !== 'single_request' || policy.policySource !== 'provider_model') {
    return { ready: false, reason: '该模型不支持整段识别，只能用于实时转写' }
  }
  if (capabilities?.speakerDiarization !== true) {
    return { ready: false, reason: '该模型没有说话人分离能力，不能用于会议纪要' }
  }
  if (capabilities?.utteranceTimestamps !== true) {
    return { ready: false, reason: '该模型不返回发言时间戳，不能用于会议转写' }
  }
  const seconds = capabilities?.maxAudioSeconds
  if (typeof seconds !== 'number' || !Number.isSafeInteger(seconds) || seconds <= 0) {
    return { ready: false, reason: '该模型未声明可处理的录音时长' }
  }
  const bytes = capabilities?.maxAudioBytes
  if (typeof bytes !== 'number' || !Number.isSafeInteger(bytes) || bytes <= 0) {
    return { ready: false, reason: '该模型未声明可处理的录音大小' }
  }
  return { ready: true, reason: '' }
}

/** Any ASR model that can take this task: segmented streaming or one meeting file. */
export function transcriptionReady(model: RecordedAudioModel): boolean {
  return recordedAudioReady(model) || meetingReady(model).ready
}

export function recordedAudioDescription(model: RecordedAudioModel, zh: boolean): string {
  const status = model.availability?.status
  if (!modelEligible(model)) {
    if (status === 'auth_failed' || status === 'permission_denied') return zh ? '服务授权待处理' : 'Service authorization required'
    if (status === 'quota_exhausted') return zh ? '服务额度不足' : 'Service quota exhausted'
    if (status === 'disabled') return zh ? '服务已停用' : 'Service disabled'
    return zh ? '服务暂不可用，可刷新状态' : 'Service unavailable; refresh status'
  }
  const meeting = meetingReady(model)
  if (meeting.ready) {
    const speakers = model.capabilities?.speakerDiarization === true
    const timestamps = model.capabilities?.utteranceTimestamps === true
    if (!zh) return 'Meeting audio · whole-file transcription' + (speakers ? ' · speaker separation' : '')
    return '会议录音 · 整段识别' + (speakers ? ' · 带说话人分离' : '') + (timestamps ? ' · 带时间戳' : '')
  }
  if (recordedAudioReady(model)) return zh ? '录音转写 · 按停顿自动分段' : 'Recordings · adaptive pause segmentation'
  if (model.capabilities?.recordedAudio?.supported === false) return zh ? '录音处理配置待修复' : 'Recording configuration requires repair'
  if (model.capabilities?.recordedAudio?.protocol === 1) {
    return zh ? meeting.reason : 'Meeting audio needs a whole-file model reachable by the speech service'
  }
  return zh ? '服务需更新录音处理规则' : 'Update the service recording policy'
}
