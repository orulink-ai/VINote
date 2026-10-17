export type FrozenModelCatalogEntry = {
  id: string; modelType: 'asr' | 'llm'; name?: string; providerName?: string
  providerId?: string; providerModel?: string
}

/** Public catalog metadata only. Routing IDs and current defaults are never labels. */
export function frozenModelDisplay(entries: FrozenModelCatalogEntry[], id: string, kind: 'asr' | 'llm') {
  const fallback = kind === 'asr' ? '原任务所选语音模型（名称暂不可读取）' : '原任务所选总结模型（名称暂不可读取）'
  const matches = entries.filter(value => value.id === id && value.modelType === kind)
  if (matches.length !== 1) return fallback
  const model = matches[0]
  const safe = (value: unknown) => typeof value === 'string' && value.trim() && value.trim() !== id && value.length <= 120 && !/[\u0000-\u001f\u007f]|https?:\/\//i.test(value) ? value.trim() : ''
  const name = safe(model.name)
  if (name) return name
  const publicModel = safe(model.providerModel)
  if (!publicModel) return fallback
  const provider = safe(model.providerName) || ({ aliyun: '阿里云', 'volcengine-asr': '豆包', volcengine: '豆包', codex: 'Codex' } as Record<string, string>)[model.providerId || '']
  return provider ? `${provider} · ${publicModel}` : publicModel
}

export function sameModelCatalogSource(current: unknown, frozen: string) {
  if (typeof current !== 'string') return false
  try {
    const left = new URL(current), right = new URL(frozen)
    return ['http:', 'https:'].includes(left.protocol) && ['http:', 'https:'].includes(right.protocol)
      && !left.username && !left.password && !left.search && !left.hash
      && !right.username && !right.password && !right.search && !right.hash
      && left.href.replace(/\/+$/, '') === right.href.replace(/\/+$/, '')
  } catch { return false }
}
