import { ApiError } from '@/lib/api'

export const VISUAL_SLIDES_PROTOCOL = 'visual-slides/1'
export const CANONICAL_TASK_UUID_RE =
  /^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/
const SLIDE_ID_RE = /^[A-Za-z0-9_-]{1,120}$/
const PNG_FILENAME_RE = /^[A-Za-z0-9_-]{1,120}\.png$/
const HEX_SHA_RE = /^[a-f0-9]{16,64}$/i
const MAX_SLIDES = 20
export const MAX_VISUAL_SLIDE_PNG_BYTES = 12 * 1024 * 1024

export type RawVisualSlidesStatus =
  | 'idle'
  | 'queued'
  | 'generating'
  | 'ready'
  | 'empty'
  | 'failed'

export type SlideDownloadErrorCode =
  | 'fetch_failed'
  | 'invalid_type'
  | 'invalid_size'
  | 'scope_changed'
  | 'unknown'

export interface VisualSlideItem {
  index: number
  id: string
  title: string
  caption: string
  targetHeading: string
  pngFilename: string
  imageUrl: string
  width: number
  height: number
  pngSha256: string | null
}

export interface ParsedVisualSlidesPayload {
  status: RawVisualSlidesStatus
  errorCode: string | null
  slides: VisualSlideItem[]
}

function isValidStatus(value: unknown): value is RawVisualSlidesStatus {
  return (
    value === 'idle' ||
    value === 'queued' ||
    value === 'generating' ||
    value === 'ready' ||
    value === 'empty' ||
    value === 'failed'
  )
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function parseVisualSlidesPayload(
  raw: unknown,
  taskId: string,
): ParsedVisualSlidesPayload | null {
  if (!CANONICAL_TASK_UUID_RE.test(taskId)) return null
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const record = raw as Record<string, unknown>
  if (record.protocol !== VISUAL_SLIDES_PROTOCOL || record.task_id !== taskId) return null
  if (!isValidStatus(record.status) || !Array.isArray(record.slides)) return null

  const rawSlides = record.slides.slice(0, MAX_SLIDES)
  const slides: VisualSlideItem[] = []
  const seenIds = new Set<string>()
  const seenFiles = new Set<string>()

  for (const item of rawSlides) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const slide = item as Record<string, unknown>
    const id = typeof slide.id === 'string' ? slide.id : ''
    const pngFilename = typeof slide.png_filename === 'string' ? slide.png_filename : ''
    const imageUrl = typeof slide.image_url === 'string' ? slide.image_url : ''
    const title = typeof slide.title === 'string' ? slide.title.trim() : ''
    const caption = typeof slide.caption === 'string' ? slide.caption.trim() : ''
    const index = slide.index
    const expectedUrl = `/api/task/${taskId}/artifacts/visuals/${pngFilename}`

    if (
      !SLIDE_ID_RE.test(id) ||
      !PNG_FILENAME_RE.test(pngFilename) ||
      seenIds.has(id) ||
      seenFiles.has(pngFilename) ||
      imageUrl !== expectedUrl ||
      !title ||
      typeof index !== 'number' ||
      !Number.isInteger(index) ||
      index <= 0
    ) {
      continue
    }

    seenIds.add(id)
    seenFiles.add(pngFilename)

    const rawWidth = slide.width
    const rawHeight = slide.height
    const width =
      typeof rawWidth === 'number' && Number.isInteger(rawWidth) && rawWidth > 0 && rawWidth <= 16384
        ? rawWidth
        : 3200
    const height =
      typeof rawHeight === 'number' && Number.isInteger(rawHeight) && rawHeight > 0 && rawHeight <= 16384
        ? rawHeight
        : 1800
    const pngSha256 =
      typeof slide.png_sha256 === 'string' && HEX_SHA_RE.test(slide.png_sha256)
        ? slide.png_sha256
        : null
    const targetHeading =
      typeof slide.target_heading === 'string' ? slide.target_heading.trim() : ''

    slides.push({
      index,
      id,
      title,
      caption: caption || title,
      targetHeading,
      pngFilename,
      imageUrl,
      width,
      height,
      pngSha256,
    })
  }

  slides.sort((left, right) => left.index - right.index)

  if (record.status === 'ready' && slides.length === 0) {
    return null
  }

  return {
    status: record.status,
    errorCode: typeof record.error_code === 'string' && record.error_code ? record.error_code : null,
    slides,
  }
}

export function slideImagePath(slide: VisualSlideItem): string {
  return slide.pngSha256 ? `${slide.imageUrl}?v=${slide.pngSha256.slice(0, 12)}` : slide.imageUrl
}

export function allSlidesEmbedded(slides: VisualSlideItem[], content: string): boolean {
  if (slides.length === 0 || !content) return false
  return slides.every((slide) => {
    const pattern = new RegExp(
      `!\\[[^\\]\\r\\n]*\\]\\(${escapeRegExp(slide.imageUrl)}(?:\\s+"[^"\\r\\n]*")?\\)`,
    )
    return pattern.test(content)
  })
}

export function buildSlideDownloadFilename(noteTitle: string, pngFilename: string): string {
  const maxPrefix = Math.min(80, Math.max(0, 159 - pngFilename.length))
  const cleaned = noteTitle
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')
    .trim()
    .replace(/^\.+/, '')
    .trim()
    .slice(0, maxPrefix)
  if (!cleaned) {
    return pngFilename.slice(0, 160)
  }
  return `${cleaned}-${pngFilename}`
}

export function isPngContentType(header: string): boolean {
  return header.split(';', 1)[0].trim().toLowerCase() === 'image/png'
}

export function apiErrorStatus(cause: unknown): number | null {
  if (typeof ApiError === 'function' && cause instanceof ApiError) {
    return cause.status
  }
  if (
    cause &&
    typeof cause === 'object' &&
    'status' in cause &&
    typeof (cause as { status?: unknown }).status === 'number'
  ) {
    return (cause as { status: number }).status
  }
  return null
}

export function mapVisualSlideErrorCode(errorCode: string | null, zh: boolean): string {
  switch (errorCode) {
    case 'renderer_unavailable':
      return zh
        ? '当前环境缺少本地浏览器或渲染服务，无法渲染视觉幻灯片。'
        : 'Visual slide renderer is unavailable in this environment.'
    case 'llm_unavailable':
      return zh
        ? '当前笔记缺少可用的总结模型配置，暂无法生成视觉幻灯片。'
        : 'No eligible language model is available for visual slide generation.'
    case 'llm_plan_failed':
      return zh
        ? '模型未能规划出有效的幻灯片方案，请稍后重试。'
        : 'Could not generate a valid visual slide plan. Please retry.'
    case 'render_failed':
      return zh
        ? '幻灯片渲染失败，请重试。'
        : 'Slide rendering failed. Please retry.'
    default:
      return zh
        ? '视觉幻灯片生成失败，请重试。'
        : 'Visual slide generation failed. Please retry.'
  }
}

export function mapSlideDownloadError(code: SlideDownloadErrorCode, zh: boolean): string {
  switch (code) {
    case 'invalid_type':
      return zh ? '返回内容不是有效的 PNG 图片。' : 'Response is not a valid PNG image.'
    case 'invalid_size':
      return zh ? '幻灯片文件大小异常。' : 'Unexpected slide file size.'
    case 'scope_changed':
      return zh ? '账号或页面状态已变化，已取消下载。' : 'Account or session changed. Download cancelled.'
    case 'fetch_failed':
    case 'unknown':
    default:
      return zh ? '幻灯片下载失败，请重试。' : 'Slide download failed. Please retry.'
  }
}
