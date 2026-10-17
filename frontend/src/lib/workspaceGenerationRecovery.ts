export type SavedGenerationRequest = {
  operation_id: string
  instructions: string
  template: string
  base_revision: number
  generatedContent?: string
  error?: string
}
export function generationRecoveryKey(owner: string, noteKey: string) {
  return `vinote:${owner}:generate-text:${encodeURIComponent(noteKey)}`
}
export function readGenerationRecovery(owner: string, noteKey: string): SavedGenerationRequest | null {
  const value = localStorage.getItem(generationRecoveryKey(owner, noteKey))
  if (!value) return null
  const saved = JSON.parse(value) as SavedGenerationRequest
  if (!saved.operation_id || !Number.isSafeInteger(saved.base_revision) || saved.base_revision < 0 || !['minutes', 'summary', 'actions'].includes(saved.template) || typeof saved.instructions !== 'string') throw new Error('生成恢复记录无法读取；请保留缓存并检查存储。')
  return saved
}
export function writeGenerationRecovery(owner: string, noteKey: string, request: SavedGenerationRequest) {
  localStorage.setItem(generationRecoveryKey(owner, noteKey), JSON.stringify(request))
}
export function clearGenerationRecovery(owner: string, noteKey: string) {
  localStorage.removeItem(generationRecoveryKey(owner, noteKey))
}
