import { renderToStaticMarkup } from 'react-dom/server'
import { apiFetch } from './api'
import { SummaryVisualSvg } from '@/components/Notes/visual/SummaryVisualSvg'
import { validateSummaryVisual, visualFramePath, type SummaryVisual } from './summaryVisual'

export async function readVisualJpeg(path: string): Promise<string> {
  // No caller-controlled Origin, path suffix, query or resource type is allowed.
  if (!/^\/api\/task\/[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\/artifacts\/screenshots\/summary-source-[0-7]\.jpg$/.test(path)) throw new Error('截图引用无效')
  const response = await apiFetch(path, { redirect: 'error' })
  if (!response.ok || response.headers.get('content-type')?.split(';')[0] !== 'image/jpeg') throw new Error('原始截图不可用，未导出不完整图形。')
  const limit = 2 * 1024 * 1024
  const length = Number(response.headers.get('content-length'))
  if (length > limit) { await response.body?.cancel(); throw new Error('截图大小无法核验。') }
  let blob: Blob
  if (response.body) {
    const reader = response.body.getReader(), chunks: ArrayBuffer[] = []
    let size = 0
    try {
      while (true) {
        const chunk = await reader.read()
        if (chunk.done) break
        size += chunk.value.byteLength
        if (size > limit) throw new Error('截图大小无法核验。')
        chunks.push(new Uint8Array(chunk.value).buffer)
      }
    } finally { await reader.cancel().catch(() => undefined); reader.releaseLock() }
    blob = new Blob(chunks, { type: 'image/jpeg' })
  } else blob = await response.blob()
  if (!blob.size || blob.size > limit) throw new Error('截图大小无法核验。')
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('截图读取失败。'))
    reader.readAsDataURL(blob)
  })
}

export async function buildSummaryVisualSvg(visual: SummaryVisual, savedBody: string, title: string,
  readImage: (path: string) => Promise<string> = readVisualJpeg): Promise<string> {
  const checked = await validateSummaryVisual(visual, visual.task_id, visual.presentation, savedBody)
  if (!checked.ok) throw new Error(checked.reason)
  if (Array.from(title).length > 240) throw new Error('导出标题过长，请缩短后重试。')
  const images = new Map<string, string>()
  for (const scene of checked.value.scenes) {
    if (images.has(scene.frame_id)) continue
    const frame = checked.value.frames.find(frame => frame.id === scene.frame_id)!
    const data = await readImage(visualFramePath(visual.task_id, frame.screenshot_index))
    if (!/^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(data) || data.length > 3 * 1024 * 1024) throw new Error('截图格式无法核验。')
    images.set(frame.id, data)
  }
  return '<?xml version="1.0" encoding="UTF-8"?>' + renderToStaticMarkup(<SummaryVisualSvg visual={checked.value} title={title} images={images} />)
}

/** This takes only our generated SVG; it never renders model HTML or model SVG. */
export async function buildSummaryVisualPng(visual: SummaryVisual, savedBody: string, title: string,
  readImage: (path: string) => Promise<string> = readVisualJpeg): Promise<Blob> {
  const source = await buildSummaryVisualSvg(visual, savedBody, title, readImage)
  const svg = new DOMParser().parseFromString(source, 'image/svg+xml').documentElement
  const width = Number(svg.getAttribute('width')), height = Number(svg.getAttribute('height'))
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1 || width * height > 16_000_000 || height > 16384) throw new Error('图形尺寸超出 PNG 导出范围，可导出 SVG。')
  const url = URL.createObjectURL(new Blob([source], { type: 'image/svg+xml' }))
  try {
    const image = new Image()
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('图形准备超时，请重试。')), 20000)
      image.onload = () => { clearTimeout(timeout); resolve() }
      image.onerror = () => { clearTimeout(timeout); reject(new Error('图形解码失败，未导出空白图片。')) }
      image.src = url
    })
    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height
    const context = canvas.getContext('2d')
    if (!context) throw new Error('此窗口暂不支持 PNG 导出，可导出 SVG。')
    context.drawImage(image, 0, 0)
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob?.size ? resolve(blob) : reject(new Error('PNG 导出失败。')), 'image/png'))
  } finally { URL.revokeObjectURL(url) }
}
