import { apiFetch, apiJson } from './api'
import { portableMarkdown } from './workspace'
import { resolveContentUrl } from './videoLinks'

const reference = /^attachment:\/\/([a-f0-9]{64})$/
export const attachmentId = (url: string) => reference.exec(url)?.[1]

export async function boundedContentImage(response: Response) {
  const limit = 5 * 1024 * 1024
  if (Number(response.headers.get('content-length') || 0) > limit) throw new Error('正文截图超过 5 MB，请缩小后重试')
  if (!response.body) throw new Error('正文截图读取失败，请重试')
  const reader = response.body.getReader(), chunks: ArrayBuffer[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > limit) throw new Error('正文截图超过 5 MB，请缩小后重试')
      const copy = new Uint8Array(value.byteLength); copy.set(value); chunks.push(copy.buffer)
    }
  } catch (cause) { await reader.cancel().catch(() => {}); throw cause }
  finally { reader.releaseLock() }
  return new Blob(chunks, { type: response.headers.get('content-type') || 'application/octet-stream' })
}

/** Only read bounded images from our authenticated artifact routes. Never fetch
 * arbitrary hosts/file paths while synchronizing a user's Markdown. */
export async function prepareWorkspaceMarkdown(content: string, current: () => boolean = () => true) {
  let prepared = content
  const images = [...content.matchAll(/!\[([^\]]*)\]\(([^)]+)\)/g)]
  const completed = new Map<string, string>()
  for (const match of images) {
    const raw = match[2].trim().replace(/^<|>$/g, '')
    if (attachmentId(raw)) continue
    const parsed = new URL(resolveContentUrl(raw), window.location.origin)
    const apiOrigin = new URL(resolveContentUrl('/'), window.location.origin).origin
    const localHost = /^(localhost|127\..*|0\.0\.0\.0|\[::1\]|192\.168\..*|10\..*|172\.(1[6-9]|2\d|3[01])\..*)$/i.test(parsed.hostname)
    if (parsed.protocol === 'https:' && !localHost && parsed.origin !== apiOrigin) continue
    if (parsed.origin !== apiOrigin || !/^\/api\/task\/[^/]+\/artifacts\/.+\.(png|jpe?g|webp)$/i.test(parsed.pathname)) {
      throw new Error('正文含有无法跨端访问的图片，请替换为已保存的截图后重试；本机内容已保留。')
    }
    if (!current()) throw new Error('账号已切换，附件上传已停止')
    let target = completed.get(raw)
    if (!target) {
      const response = await apiFetch(parsed.pathname + parsed.search)
      if (!response.ok) throw new Error('正文截图读取失败，请保留内容后重试同步')
      const image = await boundedContentImage(response)
      if (!current()) throw new Error('账号已切换，附件上传已停止')
      const form = new FormData(); form.append('file', image, 'content-image')
      const uploaded = await apiJson<{ reference: string }>('/api/workspace/attachments', { method: 'POST', body: form })
      if (!attachmentId(uploaded.reference)) throw new Error('附件回执无效，请重试同步')
      target = uploaded.reference; completed.set(raw, target)
    }
    prepared = prepared.replace(match[0], `![${match[1]}](${target})`)
  }
  // Media jump links become readable text; the original media is never uploaded.
  return portableMarkdown(prepared)
}

export const attachmentAccess = (id: string) => apiJson<{ url: string; expires_in: number; authenticated: boolean }>(`/api/workspace/attachments/${id}/access`)
