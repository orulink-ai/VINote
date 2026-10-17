import { modelEligible, type ModelEligibilityInput } from './modelEligibility'

export type RecordedAudioModel = ModelEligibilityInput & {
  capabilities?: { recordedAudio?: {
    protocol?: number; supported?: boolean; strategy?: string
    maxSessionAudioBytes?: number; reasonCode?: string; policySource?: string
  } }
}

export function recordedAudioReady(model: RecordedAudioModel): boolean {
  const policy = model.capabilities?.recordedAudio
  const bytes = policy?.maxSessionAudioBytes
  return modelEligible(model) && policy?.protocol === 1 && policy.supported === true &&
    policy.strategy === 'adaptive_pause' && policy.policySource === 'service_budget' && typeof bytes === 'number' &&
    Number.isSafeInteger(bytes) && bytes >= 640 && bytes <= 64 * 1024 * 1024 && bytes % 2 === 0
}

export function recordedAudioDescription(model: RecordedAudioModel, zh: boolean): string {
  const status = model.availability?.status
  if (!modelEligible(model)) {
    if (status === 'auth_failed' || status === 'permission_denied') return zh ? '服务授权待处理' : 'Service authorization required'
    if (status === 'quota_exhausted') return zh ? '服务额度不足' : 'Service quota exhausted'
    if (status === 'disabled') return zh ? '服务已停用' : 'Service disabled'
    return zh ? '服务暂不可用，可刷新状态' : 'Service unavailable; refresh status'
  }
  if (recordedAudioReady(model)) return zh ? '录音转写 · 按停顿自动分段' : 'Recordings · adaptive pause segmentation'
  if (model.capabilities?.recordedAudio?.supported === false) return zh ? '录音处理配置待修复' : 'Recording configuration requires repair'
  return zh ? '服务需更新录音处理规则' : 'Update the service recording policy'
}
