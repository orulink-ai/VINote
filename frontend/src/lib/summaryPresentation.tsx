import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { renderToStaticMarkup } from 'react-dom/server'
import { apiFetch } from './api'

export type ContentDepth = 'brief' | 'concise' | 'detailed'
export type Presentation = 'text' | 'illustrated' | 'html' | 'comic' | 'infographic'
export type SummaryPresentation = {
  protocol: 1; task_id: string; parent_task_id: string; canonical_task_id: string
  content_depth: ContentDepth; presentation: Presentation; model_name: string
  source_version: string; transcript_version: string; visual_evidence_version?: string | null
}
export type SummaryContext = {
  parent_task_id: string; context_revision: string
  source: { version: string; type: string; title?: string }; can_regenerate_summary: boolean
  presentation_options?: Partial<Record<Presentation, { available: boolean; reason?: string | null }>>
}
export const depthLabels: Record<ContentDepth, string> = { brief: '摘要', concise: '精简', detailed: '详细' }
export const presentationLabels: Record<Presentation, string> = { text: '文字', illustrated: '图文', html: 'HTML', comic: '漫画', infographic: '信息图' }
const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/
const escapeHtml = (value: string) => value.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)

async function readImage(src: string): Promise<string> {
  const response = await apiFetch(src)
  if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== 'image/jpeg') throw new Error('截图不可用，未导出不完整的 HTML。')
  const blob = await response.blob()
  if (blob.size === 0 || blob.size > 2 * 1024 * 1024) throw new Error('截图大小无法核验。')
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('读取截图失败'))
    reader.readAsDataURL(blob)
  })
}

/** Never render model HTML. Only known Markdown syntax and embedded task screenshots. */
export async function buildSummaryHtml(markdown: string, title: string, taskId?: string,
  fetchImage: (src: string) => Promise<string> = readImage): Promise<string> {
  const allowedImage = (src: string) => !!taskId && uuid.test(taskId) && new RegExp(`^/api/task/${taskId}/artifacts/screenshots/summary-source-[0-7]\\.jpg$`).test(src)
  const sources = [...new Set([...markdown.matchAll(/!\[[^\]\n]*\]\(([^\s)]+)\)/g)].map(match => match[1]).filter(allowedImage))]
  const images = new Map<string, string>()
  for (const source of sources) {
    const data = await fetchImage(source)
    if (!/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(data) || data.length > 3 * 1024 * 1024) throw new Error('截图格式无法核验')
    images.set(source, data)
  }
  const body = renderToStaticMarkup(<ReactMarkdown skipHtml remarkPlugins={[remarkGfm]}
    urlTransform={(url, key) => key === 'src' ? (images.has(url) ? url : '') : /^https:\/\/[^\s\\]+$/i.test(url) ? url : ''}
    components={{
      img: ({ src, alt }) => src && images.has(src) ? <img src={images.get(src)} alt={alt || '原视频画面'} /> : null,
      a: ({ href, children }) => href ? <a href={href} rel="noreferrer noopener">{children}</a> : <span>{children}</span>,
      input: () => null,
    }}>{markdown}</ReactMarkdown>)
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><title>${escapeHtml(title)}</title><style>body{max-width:900px;margin:32px auto;padding:0 24px;font:16px/1.8 system-ui,sans-serif;color:#17202a;background:white;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{border-collapse:collapse;display:block;overflow:auto}th,td{border:1px solid #aaa;padding:8px}pre{white-space:pre-wrap}blockquote{border-left:3px solid #aaa;padding-left:16px}</style></head><body><main>${body}</main></body></html>`
}
