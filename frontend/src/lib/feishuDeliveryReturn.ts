import { publishScope, readPublishDraft } from './feishuPublishReceipt'
import { resolvePageParent } from './navigation'

const pending = new Map<string, { path: string; note: string; operation?: string; valid: () => void }>()
const parameter = 'feishuDeliveryReturn'
const processed = new Set<string>()

/** Memory-only, single-use intent. A copied URL or reload cannot reopen a panel. */
export function feishuSettingsReturn(path: string, owner: string, note: string, operation?: string) {
  const parent = resolvePageParent(path, '')
  if (!parent || !/^\/(note|workspace)\//.test(parent)) throw new Error('请从已保存内容打开飞书设置')
  const token = crypto.randomUUID()
  pending.clear()
  const url = new URL(parent, 'https://vinote.invalid')
  url.searchParams.delete(parameter)
  pending.set(token, { path: url.pathname + url.search + url.hash, note, operation, valid: publishScope(owner) })
  url.searchParams.set(parameter, token)
  return '/settings/feishu?' + new URLSearchParams({ returnTo: url.pathname + url.search + url.hash })
}

export function takeFeishuDeliveryReturn(path: string, owner: string | undefined, note: string, disabled: boolean) {
  const url = new URL(path, 'https://vinote.invalid')
  const token = url.searchParams.get(parameter)
  if (!token) return null
  if (processed.has(token)) return null
  processed.add(token)
  if (processed.size > 64) processed.delete(processed.values().next().value!)
  url.searchParams.delete(parameter)
  const clean = url.pathname + url.search + url.hash
  const intent = pending.get(token)
  pending.delete(token)
  let reopen = false
  try {
    if (intent && owner && !disabled && intent.path === clean && intent.note === note) {
      intent.valid()
      const saved = readPublishDraft(owner, note)
      reopen = (saved?.operationId === intent.operation)
    }
  } catch { /* Preserve the original draft; stale or unreadable context is not restored. */ }
  return { clean, reopen }
}
