import { invoke } from '@tauri-apps/api/core'
import { apiFetch } from './api'
import { resolveContentUrl } from './videoLinks'
import { isTauriRuntime } from './desktopMicrophonePermission'

export type DownloadResult = 'saved' | 'cancelled' | 'browser_started'
export function downloadResultMessage(result: DownloadResult, zh = true) {
  if (result === 'saved') return zh ? '原文件已保存到所选位置。' : 'Original saved to the selected location.'
  if (result === 'cancelled') return zh ? '已取消导出，原文件保留。' : 'Export cancelled. Original retained.'
  return zh ? '已交给浏览器下载，请在下载列表查看保存进度和位置。' : 'Download handed to your browser. Check its downloads for progress and location.'
}

export async function downloadRecording(source: Blob | (() => Promise<Blob | ReadableStream<Uint8Array>>), title: string, filename?: string, current = () => true, browserUrl?: string): Promise<DownloadResult> {
  const native = isTauriRuntime()
  let session: string | null = null
  const safeName = (filename || title).replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').slice(0, 160) || '会议录制'
  try {
    // Choose before fetching large media. A cancelled picker performs no download.
    if (native) {
      session = await invoke<string | null>('choose_original_destination', { filename: filename ? safeName : `${safeName}.webm` })
      if (!session) return 'cancelled'
    }
    if (!current()) return 'cancelled'
    if (!native && browserUrl) { clickDownload(browserUrl, safeName); return 'browser_started' }
    const blob = typeof source === 'function' ? await source() : source
    if (!current()) { if ('getReader' in blob) await blob.cancel().catch(() => undefined); return 'cancelled' }
    if (native) {
      const send = async (chunk: Uint8Array) => {
        for (let offset = 0; offset < chunk.length; offset += 1024 * 1024) {
          if (!current()) return
          await invoke('append_original_bytes', { id: session, bytes: Array.from(chunk.subarray(offset, offset + 1024 * 1024)) })
        }
      }
      if ('getReader' in blob) {
        const reader = blob.getReader()
        try {
          while (current()) {
            const chunk = await reader.read()
            if (chunk.done) break
            if (!current()) break
            await send(chunk.value)
          }
        } finally { await reader.cancel().catch(() => undefined); reader.releaseLock() }
      } else {
        // IndexedDB recordings are already Blobs; only one bounded slice crosses IPC.
        for (let offset = 0; current() && offset < blob.size; offset += 1024 * 1024) {
          await send(new Uint8Array(await blob.slice(offset, offset + 1024 * 1024).arrayBuffer()))
        }
      }
      if (!current()) return 'cancelled'
      await invoke('finish_original_download', { id: session })
      session = null
      return 'saved'
    }
    if ('getReader' in blob) throw new Error('浏览器下载需要原文件地址。')
    const extension = blob.type.includes('mp4') ? 'mp4' : 'webm'
    const url = URL.createObjectURL(blob)
    try {
      clickDownload(url, filename ? safeName : `${safeName}.${extension}`)
    } finally { setTimeout(() => URL.revokeObjectURL(url), 60000) }
    return 'browser_started'
  } finally {
    if (session) await invoke('cancel_original_download', { id: session }).catch(() => undefined)
  }
}


function clickDownload(url: string, filename: string) {
  const anchor = document.createElement('a')
  anchor.href = url; anchor.download = filename
  // A cross-origin browser may ignore download; preserve the current product page.
  anchor.target = '_blank'; anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  try { anchor.click() } finally { anchor.remove() }
}

/** Auth stays in the existing API client; native code never receives cookies or URLs. */
export async function downloadOriginalFile(path: string, filename: string, current = () => true, signal?: AbortSignal): Promise<DownloadResult> {
  const parts = path.split('?')
  const decoded = decodeURIComponent(parts[0])
  if (parts.length > 2 || (parts[1] && parts[1] !== 'download=true') || decoded.includes('\\') || decoded.includes('#') || decoded.includes('//') || decoded.split('/').some(part => part === '.' || part === '..') || !/^\/api\/(?:notes\/[^/]+\/media|task\/[^/]+\/artifacts\/.+|files\/[^/]+\/content)$/.test(decoded)) {
    throw new Error('原文件下载地址未通过核验。')
  }
  const valid = () => current() && !signal?.aborted
  try {
    if (!valid()) return 'cancelled'
    if (!isTauriRuntime()) {
      // GET instead of HEAD: use the same authenticated route as the real original.
      // A server ignoring Range is acceptable, but never consume its full response.
      const probe = await apiFetch(path, { method: 'GET', headers: { Range: 'bytes=0-0' }, redirect: 'error', signal })
      try {
        if (![200, 206].includes(probe.status) || !probe.body) throw new Error('原文件导出失败，请检查登录和原文件状态后重试。')
      } finally { await probe.body?.cancel() }
      if (!valid()) return 'cancelled'
    }
    return await downloadRecording(async () => {
      const response = await apiFetch(path, { redirect: 'error', signal })
      if (!response.ok || !response.body) throw new Error('原文件导出失败，请检查原文件状态后重试。')
      return response.body
    }, filename, filename, valid, resolveContentUrl(path))
  } catch (cause) { if (!valid()) return 'cancelled'; throw cause }
}
